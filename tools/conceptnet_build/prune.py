"""Closure of the candidate subgraph, and assembly of the canonical artifact records.

Two invariants are established here, both of them load-bearing at *import* time in the shipped
engine:

* **Closure.** Every relation target of an emitted record must itself be a key of the merged
  knowledge base — a curated concept or another emitted record. A dangling target raises in
  :func:`spie.concepts._check_integrity`, which would take every KB-importing test down with it.
  Closure is therefore enforced by removal, and re-enforced after every gate round, because
  dropping one word can dangle another word's edge.
* **Bounded fan-out.** ``expand`` is a depth-2 breadth-first walk, so a ConceptNet hub with
  hundreds of out-edges would blow the semantic graph up quadratically and swamp both the gate
  and run-time invention. Each word's out-edges are capped to the ``max_out_edges``
  best-attested, mirroring the curated core's own density (1-3 edges per concept). The cap is
  applied **after** closure, so a word is not penalised for edges that point out of the pool.

A word left with fewer than ``min_out_edges`` surviving edges is dropped entirely: with no
out-edges it contributes nothing but the fallback affordance, and every such word would invent
the identical bare chain puzzle.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from .select import OutEdgeMap
from .stream import Edges

# The artifact record shape: (name, ((relation, (target, ...)), ...), (affordance, ...)).
Record = tuple[str, tuple[tuple[str, tuple[str, ...]], ...], tuple[str, ...]]


def closed_out_edges(
    edges: Edges, pool: Collection[str], curated: Collection[str], *, max_out_edges: int
) -> OutEdgeMap:
    """Every pool word's out-edges, restricted to in-vocabulary targets and capped by attestation.

    Ranked ``(-weight, relation, target)`` — best-attested first, with a total tie-break — then
    re-sorted into canonical ``(relation, target)`` order for emission."""
    pool_set, curated_set = set(pool), set(curated)
    allowed = pool_set | curated_set
    ranked: dict[str, list[tuple[float, str, str]]] = {}
    for (start, relation, end), weight in edges.items():
        if start in pool_set and end in allowed and end != start:
            ranked.setdefault(start, []).append((-weight, relation, end))
    out: OutEdgeMap = {}
    for word in sorted(pool_set):
        best = sorted(ranked.get(word, ()))[:max_out_edges]
        out[word] = tuple(sorted((relation, end) for _w, relation, end in best))
    return out


def restrict(
    out_map: OutEdgeMap, allowed: Collection[str], curated: Collection[str], *, min_out_edges: int
) -> tuple[tuple[str, ...], OutEdgeMap]:
    """Removal-only fixpoint: keep only ``allowed`` words, only edges into the surviving
    vocabulary, and only words that still carry ``min_out_edges`` of them.

    Monotone (nothing is ever added back), so the loop terminates; it runs to a fixpoint because
    dropping an under-connected word can dangle an edge that kept another word alive."""
    curated_set = set(curated)
    kept = set(allowed) & set(out_map)
    while True:
        survivors = kept | curated_set
        pruned = {w: tuple(e for e in out_map[w] if e[1] in survivors) for w in sorted(kept)}
        dropped = {w for w, edges in pruned.items() if len(edges) < min_out_edges}
        if not dropped:
            return tuple(sorted(kept)), pruned
        kept -= dropped


def to_records(
    words: Collection[str],
    out_map: OutEdgeMap,
    affordances: Mapping[str, tuple[str, ...]],
) -> tuple[Record, ...]:
    """Assemble the canonical artifact records: sorted by name, relations grouped and sorted by
    relation value, targets and affordances sorted and de-duplicated."""
    records: list[Record] = []
    for word in sorted(words):
        grouped: dict[str, set[str]] = {}
        for relation, target in out_map.get(word, ()):
            grouped.setdefault(relation, set()).add(target)
        relations = tuple(
            (relation, tuple(sorted(targets))) for relation, targets in sorted(grouped.items())
        )
        records.append((word, relations, tuple(sorted(set(affordances[word])))))
    return tuple(records)


__all__ = ["Record", "closed_out_edges", "restrict", "to_records"]
