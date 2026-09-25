"""Distributed round-1 gating: prove one shard of the vocabulary on a throwaway runner.

The 2.3b build's cost is round 1 of the prune/gate fixpoint — the full ~3,244-word certify gate.
Because a verdict is a pure function of a word's depth-2 neighbourhood (captured by
:func:`~tools.conceptnet_build.gate.dependency_key`) and nothing else, that round-1 gate list can
be partitioned across machines and the resulting verdict caches merged:
:mod:`tools.conceptnet_build.merge_verdicts` concatenates them and the local build then finishes in
minutes, every round-1 key a cache hit.

This module gates ``round1_plan(...)[1][shard::num_shards]`` against the trial KB from that *same*
``round1_plan`` — so a shard's dependency keys are byte-identical to the build's by construction,
never by coincidence — and writes rows in the exact :class:`~tools.conceptnet_build.verdicts.\
VerdictCache` on-disk format. It reuses the durable cache for its own slice too, so a shard killed
at the 6h runner cap simply resumes from its own partial rows on re-run.

SOUNDNESS: a stored verdict is trusted by key *without re-proof* (see ``verdicts.py``), so a shard's
verdicts are mergeable only if the runner computes the *same* verdict this machine would. That
requires the pinned toolchain (Python 3.12, ``z3-solver==4.13.4``, ``clingo==5.8.2`` — the sole
third-party deps; ``z3_rlimit`` makes each check machine-independent) and it is *verified*, not
assumed: ``merge_verdicts validate`` diffs shared keys against locally-proven ground truth before
any cloud verdict is trusted. A single ``(passed, reason)`` disagreement is a hard stop.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from .build import round1_plan
from .gate import GATE_VERSION, Verdict, gate_words
from .stream import read_edge_cache
from .verdicts import VerdictCache

_DEFAULT_CACHE = os.path.join(os.path.dirname(__file__), ".cache", "edges.tsv.gz")


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _write_through(cache: VerdictCache, keys: Mapping[str, str]):
    """A gate callback recording each verdict durably the instant it lands."""

    def put(word: str, verdict: Verdict) -> None:
        cache.put(keys[word], verdict, word)

    return put


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.conceptnet_build.shard",
        description="Gate one shard of the round-1 vocabulary and write a mergeable verdict cache.",
    )
    p.add_argument("--shard", type=int, required=True, help="this shard's index, 0..num-shards-1")
    p.add_argument("--num-shards", type=int, required=True, help="total number of shards")
    p.add_argument("--out", required=True, help="verdict-cache file to write for this shard")
    p.add_argument("--edge-cache", default=_DEFAULT_CACHE, help="committed filtered-edge cache")
    p.add_argument("--weight-min", type=float, default=1.0, help="must match the build")
    p.add_argument("--cap", type=int, default=3500, help="must match the build")
    p.add_argument("--max-hops", type=int, default=2, help="must match the build")
    p.add_argument("--max-out-edges", type=int, default=6, help="must match the build")
    p.add_argument("--min-out-edges", type=int, default=1, help="must match the build")
    p.add_argument("--isa-hops", type=int, default=3, help="must match the build")
    p.add_argument("--seeds", type=int, default=9, help="must match the build")
    p.add_argument("--z3-rlimit", type=int, default=8_000_000, help="must match the build")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="worker processes")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not (0 <= args.shard < args.num_shards):
        raise SystemExit(f"--shard {args.shard} is out of range [0, {args.num_shards})")

    edges = read_edge_cache(args.edge_cache, dump_sha=None, weight_min=args.weight_min)
    if edges is None:
        raise SystemExit(
            f"no usable edge cache at {args.edge_cache}: the committed edges.tsv.gz is the only "
            "data input a shard needs (no 497MB dump) — check the path and --weight-min"
        )

    # The same code path the real build runs, so this shard's trial KB and dependency keys are
    # byte-identical to build_records' round 1 — the precondition for merging shard verdicts back.
    records, to_gate, keys = round1_plan(
        edges,
        cap=args.cap,
        max_hops=args.max_hops,
        max_out_edges=args.max_out_edges,
        min_out_edges=args.min_out_edges,
        isa_hops=args.isa_hops,
    )
    mine = to_gate[args.shard :: args.num_shards]
    _log(
        f"  shard {args.shard}/{args.num_shards}: {len(mine):,} of {len(to_gate):,} round-1 keys "
        f"(rlimit={args.z3_rlimit}, seeds={args.seeds}, jobs={args.jobs})"
    )

    cache = VerdictCache(
        args.out, seeds=args.seeds, gate_version=f"{GATE_VERSION}-rl{args.z3_rlimit}"
    )
    with cache:
        # Skip keys this shard already proved on an earlier (killed) run: pure resume, no re-proof.
        pending = [word for word in mine if cache.get(keys[word]) is None]
        resumed = len(mine) - len(pending)
        _log(f"  shard {args.shard}: {len(pending):,} to prove, {resumed:,} resumed")
        gate_words(
            records,
            pending,
            seeds=args.seeds,
            jobs=args.jobs,
            z3_rlimit=args.z3_rlimit,
            progress_every=max(1, len(pending) // 20),
            on_verdict=_write_through(cache, keys),
        )
    _log(f"  shard {args.shard}: done: {cache.writes:,} newly proven, {cache.hits:,} resumed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
