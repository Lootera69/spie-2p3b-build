"""Streaming ingest of the pinned ConceptNet dump, plus a re-usable edge cache.

The published assertions dump is ~1.2 GB gzipped (~9 GB raw, ~34M lines), so it is read
**line by line** out of the compressed stream and never materialized. What survives
:func:`~tools.conceptnet_build.filters.parse_line` is a few hundred thousand edges, which fit
comfortably in memory.

Repeated assertions (the same ``(start, relation, end)`` contributed by several ConceptNet source
datasets) are aggregated by **max** weight. Max is chosen over a sum because it is
order-independent *exactly* — a float sum's result depends on addition order, which would make the
aggregate a function of the dump's line order rather than of its content.

The edge cache exists so that regenerating at a different ``cap`` / ``max-hops`` (the pilot then
the full build) does not re-read the dump. It stores the dump's sha256 and the weight floor it was
built with and refuses to serve a mismatched request, so a cache can never silently stand in for
different build parameters.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import sys
from collections.abc import Iterator

from .filters import parse_line

# (start, relation, end) -> aggregated weight.
Edges = dict[tuple[str, str, str], float]

_CACHE_MAGIC = "# spie-conceptnet-edge-cache/1"
_SHA_CHUNK = 1 << 20


def dump_sha256(path: str) -> str:
    """The sha256 of the dump file as shipped — the artifact's input provenance."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_SHA_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def iter_filtered(
    path: str, *, progress_every: int = 2_000_000, limit_lines: int = 0
) -> Iterator[tuple[str, str, str, float]]:
    """Yield every ``(start, relation, end, weight)`` the filters admit, in dump order.

    ``limit_lines`` truncates the scan (for smoke tests only — a truncated scan yields a different,
    honestly-different artifact). Progress goes to stderr so a multi-minute scan is observable."""
    kept = 0
    with gzip.open(path, "rb") as fh:
        for index, raw in enumerate(fh, start=1):
            if limit_lines and index > limit_lines:
                break
            if progress_every and index % progress_every == 0:
                print(f"  ... {index:,} lines scanned, {kept:,} edges kept", file=sys.stderr)
            edge = parse_line(raw)
            if edge is not None:
                kept += 1
                yield edge
    print(f"  scanned to completion: {kept:,} edges kept", file=sys.stderr)


def collect_edges(
    path: str, *, weight_min: float, progress_every: int = 2_000_000, limit_lines: int = 0
) -> Edges:
    """Stream the dump and return the weight-aggregated edge set at or above ``weight_min``."""
    edges: Edges = {}
    for start, relation, end, weight in iter_filtered(
        path, progress_every=progress_every, limit_lines=limit_lines
    ):
        if weight < weight_min:
            continue
        key = (start, relation, end)
        previous = edges.get(key)
        if previous is None or weight > previous:
            edges[key] = weight
    return edges


def write_edge_cache(path: str, edges: Edges, *, dump_sha: str, weight_min: float) -> None:
    """Write the filtered edge set to a gzipped TSV, sorted, with its provenance header."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{_CACHE_MAGIC}\t{dump_sha}\t{weight_min!r}\n")
        for (start, relation, end), weight in sorted(edges.items()):
            fh.write(f"{start}\t{relation}\t{end}\t{weight!r}\n")


def read_edge_cache(path: str, *, dump_sha: str | None, weight_min: float) -> Edges | None:
    """Read a cache written by :func:`write_edge_cache`, or ``None`` if it cannot be trusted.

    A cache is refused when it is absent, malformed, built from a different dump, or built at a
    different weight floor — the cache is a speed-up, never a substitute for the pinned input."""
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        if len(header) != 3 or header[0] != _CACHE_MAGIC:
            print(f"  cache {path}: unrecognized header, ignoring", file=sys.stderr)
            return None
        if dump_sha is not None and header[1] != dump_sha:
            print(f"  cache {path}: built from a different dump, ignoring", file=sys.stderr)
            return None
        if float(header[2]) != weight_min:
            print(f"  cache {path}: built at weight_min={header[2]}, ignoring", file=sys.stderr)
            return None
        edges: Edges = {}
        for line in fh:
            start, relation, end, weight = line.rstrip("\n").split("\t")
            edges[(start, relation, end)] = float(weight)
    print(
        f"  cache {path}: {len(edges):,} edges reused (dump {header[1][:12]}...)", file=sys.stderr
    )
    return edges


def cached_dump_sha(path: str) -> str | None:
    """The dump sha recorded in an edge cache, so a rebuild can reuse it without re-hashing the
    1.2 GB input."""
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
    return header[1] if len(header) == 3 and header[0] == _CACHE_MAGIC else None


__all__ = [
    "Edges",
    "dump_sha256",
    "iter_filtered",
    "collect_edges",
    "write_edge_cache",
    "read_edge_cache",
    "cached_dump_sha",
]
