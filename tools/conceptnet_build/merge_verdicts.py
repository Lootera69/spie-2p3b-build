"""Merge sharded verdict caches into one, and VALIDATE cloud verdicts against local ground truth.

Two subcommands, both operating on the plain :class:`~tools.conceptnet_build.verdicts.VerdictCache`
on-disk format (a header line, then ``digest\\tpassed\\treason\\tword`` rows):

* ``merge FILES... --out OUT`` — concatenate shard caches into one: a single header, every data
  row, deduplicated by key digest. Each round-1 key lands in exactly one shard, so digests do not
  collide across shards; the result is a drop-in ``verdicts.tsv`` the local build consumes as pure
  cache hits. Rows are written in sorted-digest order, so the merge is itself byte-deterministic.
* ``validate --against LOCAL FILES...`` — the soundness gate. For every key present in BOTH a
  cloud/shard cache and the locally-proven ``LOCAL`` cache, assert the ``(passed, reason)`` are
  identical. A single disagreement means the runner's Z3/clingo did not reproduce this machine's
  proof, so the whole cloud batch is untrustworthy: it exits non-zero and names the divergent keys.
  A stored verdict is trusted by key without re-proof (see ``verdicts.py``), so this cross-machine
  diff is precisely what earns that trust — it is run before any cloud verdict is merged into the
  shipped build's cache, never after.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .verdicts import _MAGIC


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _read(path: str) -> tuple[str, str, dict[str, tuple[str, str, str]]]:
    """Parse a verdict cache into ``(gate_version, seeds, {digest: (passed, reason, word)})``."""
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        if len(header) != 3 or header[0] != _MAGIC:
            raise SystemExit(f"{path}: not a verdict cache (unrecognized header)")
        gate_version, seeds = header[1], header[2]
        rows: dict[str, tuple[str, str, str]] = {}
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:  # a row torn by a kill mid-write; the rest is still good
                continue
            digest, passed, reason, word = parts
            rows[digest] = (passed, reason, word)
    return gate_version, seeds, rows


def merge(files: Sequence[str], out: str) -> int:
    gate_version: str | None = None
    seeds: str | None = None
    merged: dict[str, tuple[str, str, str]] = {}
    for path in files:
        gv, sd, rows = _read(path)
        if gate_version is None:
            gate_version, seeds = gv, sd
        elif (gv, sd) != (gate_version, seeds):
            raise SystemExit(
                f"{path}: gate {gv!r}/seeds {sd!r} != {gate_version!r}/{seeds!r}; "
                "refusing to merge caches produced by different gates"
            )
        merged.update(rows)
        _log(f"  {path}: {len(rows):,} rows")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{_MAGIC}\t{gate_version}\t{seeds}\n")
        for digest in sorted(merged):
            passed, reason, word = merged[digest]
            fh.write(f"{digest}\t{passed}\t{reason}\t{word}\n")
    _log(
        f"  merged {len(files)} cache(s) -> {out}: {len(merged):,} distinct verdicts "
        f"(gate {gate_version}, seeds {seeds})"
    )
    return 0


def validate(local: str, others: Sequence[str]) -> int:
    lgv, lsd, lrows = _read(local)
    _log(f"  local ground truth {local}: {len(lrows):,} verdicts (gate {lgv}, seeds {lsd})")
    shared = 0
    mismatches: list[str] = []
    for path in others:
        gv, sd, rows = _read(path)
        if (gv, sd) != (lgv, lsd):
            raise SystemExit(
                f"{path}: gate {gv!r}/seeds {sd!r} != local {lgv!r}/{lsd!r}; not comparable"
            )
        for digest, (passed, reason, word) in rows.items():
            if digest not in lrows:
                continue
            shared += 1
            lpassed, lreason, _lword = lrows[digest]
            if (passed, reason) != (lpassed, lreason):
                mismatches.append(
                    f"    {word or digest[:12]}: cloud=({passed},{reason!r}) "
                    f"local=({lpassed},{lreason!r})"
                )
    if not shared:
        _log(
            "  VALIDATE INCONCLUSIVE: no keys shared between cloud and local yet; "
            "cannot vouch for the cloud verdicts; let the local build prove more, then re-run"
        )
        return 1
    if mismatches:
        _log(
            f"  VALIDATE FAILED: {len(mismatches):,} of {shared:,} shared keys disagree; the "
            "cloud toolchain does NOT reproduce this machine. Discard every cloud verdict."
        )
        for line in mismatches[:50]:
            _log(line)
        if len(mismatches) > 50:
            _log(f"    ... and {len(mismatches) - 50:,} more")
        return 1
    _log(
        f"  VALIDATE OK: all {shared:,} shared keys agree; cloud verdicts reproduce the local "
        "ground truth byte-for-byte; the merged cache is safe to trust"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.conceptnet_build.merge_verdicts",
        description="Merge shard verdict caches, or validate cloud verdicts against a local cache.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge", help="concatenate shard caches into one, deduplicated by key")
    m.add_argument("files", nargs="+", help="shard verdict caches to merge")
    m.add_argument("--out", required=True, help="merged verdict cache to write")
    v = sub.add_parser(
        "validate",
        help="diff cloud/shard caches against a local cache; nonzero on any disagreement",
    )
    v.add_argument("--against", required=True, dest="local", help="locally-proven ground truth")
    v.add_argument("files", nargs="+", help="cloud/shard caches to check against local")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "merge":
        return merge(args.files, args.out)
    return validate(args.local, args.files)


if __name__ == "__main__":
    raise SystemExit(main())
