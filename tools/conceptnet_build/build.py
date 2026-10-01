"""The offline build: pinned dump -> certify-gated, closed, canonical artifact records.

The whole pipeline is one deterministic function of the dump and the CLI parameters. Its heart is
the **prune/gate fixpoint** — the one genuinely circular dependency in the design:

* pruning to a closed subgraph decides which words *exist*, which decides each word's neighbourhood,
  which decides what it invents;
* the certify gate decides which words *survive*, and dropping a word removes it from every other
  word's neighbourhood — which can dangle an edge (re-prune) or change an invented puzzle (re-gate).

So the loop alternates ``restrict`` (removal-only closure + min-degree) and ``gate_words`` until a
round drops nobody. It is monotone — ``allowed`` only ever shrinks — so it terminates, and the
result is the greatest closed, certify-passing subset of the selected pool. Truncation to the size
band is folded into the same loop (drop the lowest-ranked survivors, then re-close and re-gate),
so the emitted artifact is closed and fully gated *after* truncation, never before.

Re-gating every survivor each round would be wasteful, so verdicts are memoized on
:func:`~tools.conceptnet_build.gate.dependency_key` — a word is actually re-run only when its own
depth-2 neighbourhood changed. Correctness does not depend on the memo (it only skips provably
identical work); determinism does not either (results are keyed and consumed in sorted order).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence

from . import emit
from .affordance_rules import derive
from .gate import GATE_VERSION, Verdict, curated_view, dependency_key, gate_words, merged_view
from .prune import Record, closed_out_edges, restrict, to_records
from .runlock import RunLock
from .select import OutEdgeMap, hop_map, neighbour_map, select_pool, strengths
from .stream import (
    cached_dump_sha,
    collect_edges,
    dump_sha256,
    read_edge_cache,
    write_edge_cache,
)
from .verdicts import VerdictCache

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_OUT = os.path.join(_ROOT, "src", "spie", "conceptnet_data.py")
_DEFAULT_NOTICE = os.path.join(_ROOT, "NOTICE")
_DEFAULT_CACHE = os.path.join(os.path.dirname(__file__), ".cache", "edges.tsv.gz")
_DEFAULT_VERDICTS = os.path.join(os.path.dirname(__file__), ".cache", "verdicts.tsv")
_DEFAULT_LOCK = os.path.join(os.path.dirname(__file__), ".cache", "build.lock")


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _load_edges(args: argparse.Namespace) -> tuple[dict[tuple[str, str, str], float], str]:
    """The filtered edge set and the source dump's sha256, reusing the edge cache when valid."""
    dump_sha = ""
    if args.dump:
        dump_sha = cached_dump_sha(args.edge_cache) or ""
        if not dump_sha:
            _log(f"  hashing dump {os.path.basename(args.dump)} ...")
            dump_sha = dump_sha256(args.dump)
    cached = read_edge_cache(args.edge_cache, dump_sha=dump_sha or None, weight_min=args.weight_min)
    if cached is not None:
        if not dump_sha:
            dump_sha = cached_dump_sha(args.edge_cache) or ""
        return cached, dump_sha
    if not args.dump:
        raise SystemExit(
            "no usable edge cache and no --dump given: pass --dump PATH to the "
            "conceptnet-assertions-5.7.0.csv.gz dump"
        )
    _log(f"  streaming {os.path.basename(args.dump)} (weight_min={args.weight_min}) ...")
    edges = collect_edges(args.dump, weight_min=args.weight_min, limit_lines=args.limit_lines)
    if not args.limit_lines:  # a truncated scan must never be cached as if it were complete
        write_edge_cache(args.edge_cache, edges, dump_sha=dump_sha, weight_min=args.weight_min)
    return edges, dump_sha


def _rank_key(
    hops: Mapping[str, int], weight: Mapping[str, float]
) -> Callable[[str], tuple[int, float, str]]:
    """The selection rank reused for truncation: nearer the core, better-attested, then by name."""
    return lambda w: (hops.get(w, 1 << 30), -weight.get(w, 0.0), w)


def _write_through(
    cache: VerdictCache, keys: Mapping[str, str]
) -> Callable[[str, Verdict], None]:
    """A gate callback that records each verdict durably the moment it lands.

    The round's ``keys`` are passed as an argument rather than captured from the enclosing loop, so
    the binding is a fact about this call rather than a convention about when the callback runs."""

    def put(word: str, verdict: Verdict) -> None:
        cache.put(keys[word], verdict, word)

    return put


def _kb_plan(
    closed: OutEdgeMap,
    allowed: Collection[str],
    curated_names: Collection[str],
    curated_affordances: Mapping[str, tuple[str, ...]],
    *,
    min_out_edges: int,
    isa_hops: int,
) -> tuple[tuple[str, ...], tuple[Record, ...], dict[str, str]]:
    """One fixpoint round's trial KB and dependency keys for the currently-``allowed`` words.

    Extracted verbatim from the fixpoint loop so the distributed build
    (:mod:`tools.conceptnet_build.shard`) derives byte-identical ``records`` and ``keys`` from the
    *same* code: a shard's verdict is mergeable with this build's only because their dependency keys
    match by construction, not by luck. ``pruned``, ``affordances`` and ``merged`` are consumed here
    to produce ``records``/``keys`` and are not read again by the caller."""
    kept, pruned = restrict(closed, allowed, curated_names, min_out_edges=min_out_edges)
    affordances = derive(kept, pruned, curated_affordances, isa_hops=isa_hops)
    records = to_records(kept, pruned, affordances)
    merged = merged_view(records)
    keys = {word: dependency_key(word, merged) for word in kept}
    return kept, records, keys


def build_records(
    edges: Mapping[tuple[str, str, str], float],
    *,
    cap: int,
    max_hops: int,
    max_out_edges: int,
    min_out_edges: int,
    isa_hops: int,
    seeds: int,
    jobs: int,
    target: int,
    z3_rlimit: int = 0,
    cache: VerdictCache | None = None,
) -> tuple[tuple[Record, ...], Counter[str], int, int]:
    """Run the prune/gate fixpoint and return ``(records, gate_reasons, pool_size, rounds)``."""
    view = curated_view()
    curated_names = set(view)
    curated_affordances = {name: affordances for name, (_relations, affordances) in view.items()}

    pool = select_pool(dict(edges), curated_names, cap=cap, max_hops=max_hops)
    _log(f"  selected pool: {len(pool):,} candidate words (cap={cap}, max_hops={max_hops})")
    closed = closed_out_edges(dict(edges), pool, curated_names, max_out_edges=max_out_edges)

    # The truncation rank is the *same* total order selection used, so shrinking to the band keeps
    # the best-attested words nearest the curated core rather than an arbitrary alphabetical prefix.
    rank_key = _rank_key(
        hop_map(curated_names, neighbour_map(dict(edges)), max_hops), strengths(dict(edges))
    )

    memo: dict[str, Verdict] = {}
    reasons: Counter[str] = Counter()
    allowed = set(pool)
    rounds = 0
    while True:
        rounds += 1
        kept, records, keys = _kb_plan(
            closed,
            allowed,
            curated_names,
            curated_affordances,
            min_out_edges=min_out_edges,
            isa_hops=isa_hops,
        )
        # Gate once per distinct *key*, not once per word: a verdict is a function of the depth-2
        # sub-KB alone (``invent`` never reads the root name — two words with the same
        # neighbourhood produce a byte-identical puzzle and provenance), so a second word with an
        # already-gated key would re-prove exactly the same thing. Sorted order picks the
        # representative, keeping the choice independent of dict iteration.
        to_gate: list[str] = []
        seen: set[str] = set()
        for word in sorted(kept):
            key = keys[word]
            if key in memo or key in seen:
                continue
            if cache is not None:
                stored = cache.get(key)
                if stored is not None:
                    memo[key] = stored
                    continue
            seen.add(key)
            to_gate.append(word)
        _log(
            f"  round {rounds}: {len(kept):,} kept, gating {len(to_gate):,} "
            f"(known {len(kept) - len(to_gate):,})"
        )
        # Scale the progress interval to the round's size (~20 updates) instead of the fixed
        # default: a pilot-sized round is smaller than that default, so it would otherwise run
        # to completion in total silence and be indistinguishable from a hang.
        every = max(1, len(to_gate) // 20)
        # Write each verdict through to the durable log as it lands, so an interrupted multi-hour
        # build resumes from the last completed proof rather than from nothing.
        verdicts = gate_words(
            records,
            to_gate,
            seeds=seeds,
            jobs=jobs,
            z3_rlimit=z3_rlimit,
            progress_every=every,
            on_verdict=None if cache is None else _write_through(cache, keys),
        )
        for word, verdict in verdicts.items():
            memo[keys[word]] = verdict
        failed = [word for word in kept if not memo[keys[word]][0]]
        if failed:
            for word in failed:
                reasons[memo[keys[word]][1]] += 1
            allowed = {word for word in kept if memo[keys[word]][0]}
            _log(f"    dropped {len(failed):,} by gate; {len(allowed):,} remain")
            continue
        if target and len(kept) > target:
            allowed = set(sorted(kept, key=rank_key)[:target])
            _log(f"    truncating {len(kept):,} -> {len(allowed):,} (target={target})")
            continue
        return records, reasons, len(pool), rounds


def round1_plan(
    edges: Mapping[tuple[str, str, str], float],
    *,
    cap: int,
    max_hops: int,
    max_out_edges: int,
    min_out_edges: int,
    isa_hops: int,
) -> tuple[tuple[Record, ...], list[str], dict[str, str]]:
    """The first fixpoint round's ``(records, to_gate, keys)`` — the whole vocabulary before any
    gate has dropped a word.

    This is exactly what :func:`build_records` proves in round 1 (its dominant cost), exposed so the
    sharded build (:mod:`tools.conceptnet_build.shard`) gates the *same* words against the *same*
    trial KB. ``to_gate`` is one representative word per distinct dependency key in sorted order, so
    ``to_gate[i::n]`` partitions the round-1 proof obligations across ``n`` shards deterministically
    and completely (every key lands in exactly one shard). The prologue mirrors ``build_records``:
    identical ``pool``/``closed`` construction, then the shared :func:`_kb_plan` and the same
    dedup-by-key loop — so the keys a shard computes are byte-identical to the build's."""
    view = curated_view()
    curated_names = set(view)
    curated_affordances = {name: affordances for name, (_relations, affordances) in view.items()}
    pool = select_pool(dict(edges), curated_names, cap=cap, max_hops=max_hops)
    closed = closed_out_edges(dict(edges), pool, curated_names, max_out_edges=max_out_edges)
    kept, records, keys = _kb_plan(
        closed,
        set(pool),
        curated_names,
        curated_affordances,
        min_out_edges=min_out_edges,
        isa_hops=isa_hops,
    )
    to_gate: list[str] = []
    seen: set[str] = set()
    for word in sorted(kept):
        if keys[word] in seen:
            continue
        seen.add(keys[word])
        to_gate.append(word)
    return records, to_gate, keys


def _report(
    records: Sequence[Record], reasons: Counter[str], pool_size: int, rounds: int
) -> None:
    """A deterministic build summary: sizes, fixpoint rounds, and the gate-drop histogram."""
    gate_dropped = sum(reasons.values())
    structural = pool_size - len(records) - gate_dropped
    _log("")
    _log(f"  pool selected .......... {pool_size:,}")
    _log(f"  pruned (under-connected / truncated) ... {structural:,}")
    _log(f"  dropped by certify gate  {gate_dropped:,}")
    for reason, count in sorted(reasons.items()):
        _log(f"      {reason:<28} {count:,}")
    _log(f"  kept (final vocabulary)  {len(records):,}")
    _log(f"  fixpoint rounds ........ {rounds}")
    _log("")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.conceptnet_build",
        description="Build the offline, certify-gated ConceptNet vocabulary artifact.",
    )
    p.add_argument("--dump", help="path to conceptnet-assertions-5.7.0.csv.gz")
    p.add_argument("--edge-cache", default=_DEFAULT_CACHE, help="filtered-edge cache (gz TSV)")
    p.add_argument("--weight-min", type=float, default=1.0, help="minimum assertion weight")
    p.add_argument("--cap", type=int, default=3500, help="max candidate words selected")
    p.add_argument("--max-hops", type=int, default=2, help="BFS radius from the curated core")
    p.add_argument("--max-out-edges", type=int, default=6, help="fan-out cap per word")
    p.add_argument("--min-out-edges", type=int, default=1, help="min surviving out-edges per word")
    p.add_argument("--isa-hops", type=int, default=3, help="IsA inheritance depth for affordances")
    p.add_argument("--seeds", type=int, default=9, help="certify-gate seeds 0..seeds-1")
    p.add_argument("--target", type=int, default=0, help="truncate survivors to this (0=off)")
    p.add_argument("--size-min", type=int, default=1000, help="fail if fewer words survive")
    p.add_argument("--size-max", type=int, default=3500, help="recorded band ceiling")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="gate worker processes")
    p.add_argument(
        "--z3-rlimit",
        type=int,
        default=8_000_000,
        help="deterministic Z3 resource limit per check (0=unbounded); bounds pathological solves",
    )
    p.add_argument(
        "--verdict-cache",
        default=_DEFAULT_VERDICTS,
        help="durable certify-gate verdict log, so an interrupted build can resume",
    )
    p.add_argument(
        "--no-verdict-cache",
        action="store_true",
        help="prove every word in this process (ignore and do not write the verdict log)",
    )
    p.add_argument(
        "--lock-file",
        default=_DEFAULT_LOCK,
        help="single-writer PID lock so two builds cannot corrupt the shared verdict log",
    )
    p.add_argument(
        "--no-lock",
        action="store_true",
        help="skip the single-writer lock (for smoke runs that share nothing)",
    )
    p.add_argument("--limit-lines", type=int, default=0, help="truncate the dump scan (smoke only)")
    p.add_argument("--out", default=_DEFAULT_OUT, help="artifact module to write")
    p.add_argument("--notice", default=_DEFAULT_NOTICE, help="repository NOTICE to check/write")
    p.add_argument("--write-notice", action="store_true", help="(over)write the NOTICE")
    p.add_argument("--dry-run", action="store_true", help="build and report but write nothing")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    started = time.monotonic()

    if args.write_notice:
        emit.write_notice(args.notice)
        _log(f"  wrote NOTICE -> {args.notice}")
    missing = emit.check_notice(args.notice)
    if missing:
        _log(f"NOTICE {args.notice} is missing required tokens: {missing}")
        _log("  re-run with --write-notice to generate it")
        return 2

    if args.no_lock:
        return _run(args, started)
    with RunLock(args.lock_file):
        return _run(args, started)


def _run(args: argparse.Namespace, started: float) -> int:
    """The build proper, held under the single-writer lock so no second build can race the log."""
    edges, dump_sha = _load_edges(args)
    _log(f"  {len(edges):,} filtered edges; dump sha {dump_sha[:12] or '(none)'}...")

    cache = (
        None
        if args.no_verdict_cache
        else VerdictCache(
            args.verdict_cache,
            seeds=args.seeds,
            gate_version=f"{GATE_VERSION}-rl{args.z3_rlimit}",
        )
    )
    if cache is None:
        _log("  verdict cache disabled: every word will be proven in this process")
        records, reasons, pool_size, rounds = build_records(
            edges,
            cap=args.cap,
            max_hops=args.max_hops,
            max_out_edges=args.max_out_edges,
            min_out_edges=args.min_out_edges,
            isa_hops=args.isa_hops,
            seeds=args.seeds,
            jobs=args.jobs,
            target=args.target,
            z3_rlimit=args.z3_rlimit,
        )
    else:
        with cache:
            records, reasons, pool_size, rounds = build_records(
                edges,
                cap=args.cap,
                max_hops=args.max_hops,
                max_out_edges=args.max_out_edges,
                min_out_edges=args.min_out_edges,
                isa_hops=args.isa_hops,
                seeds=args.seeds,
                jobs=args.jobs,
                target=args.target,
                z3_rlimit=args.z3_rlimit,
                cache=cache,
            )
        _log(f"  verdict cache: {cache.hits:,} reused, {cache.writes:,} newly proven")
    _report(records, reasons, pool_size, rounds)

    if not (args.size_min <= len(records) <= args.size_max):
        _log(
            f"FAIL: {len(records):,} certifiable words is outside the declared band "
            f"[{args.size_min:,}, {args.size_max:,}]: adjust --cap/--max-hops or the band"
        )
        return 1

    build_params: dict[str, object] = {
        "cap": args.cap,
        "conceptnet_version": "5.7.0",
        "dump": os.path.basename(args.dump) if args.dump else "",
        "isa_hops": args.isa_hops,
        "max_hops": args.max_hops,
        "max_out_edges": args.max_out_edges,
        "min_out_edges": args.min_out_edges,
        "seeds": args.seeds,
        "size_max": args.size_max,
        "size_min": args.size_min,
        "target": args.target,
        "weight_min": args.weight_min,
        "z3_rlimit": args.z3_rlimit,
    }
    artifact_hash = emit.compute_artifact_hash(records)
    if args.dry_run:
        _log(f"  dry run: {len(records):,} words, {artifact_hash}; nothing written")
        return 0

    emit.write_artifact(
        args.out, records, source_dump_sha256=dump_sha, build_params=build_params
    )
    elapsed = time.monotonic() - started
    _log(f"  wrote {len(records):,} records -> {args.out}")
    _log(f"  {artifact_hash}")
    _log(f"  done in {elapsed:.1f}s")
    return 0


__all__ = ["build_records", "main", "round1_plan"]
