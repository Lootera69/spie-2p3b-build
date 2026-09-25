"""Deterministic selection of the candidate vocabulary from the filtered edge set.

Selection answers one question: *which* of the ~100k filtered ConceptNet terms should be offered
to the certify gate. The answer is a bounded neighbourhood of the hand-curated core, ranked by a
**total** order so the pool is a pure function of the edge set and the parameters:

* **Breadth-first from the curated seeds over the _undirected_ filtered graph.** Undirected,
  because ConceptNet's useful neighbours of ``door`` include everything that points *at* it
  (``x IsA barrier``) as well as what it points to. Selection reachability is undirected;
  the *emitted* edges stay strictly directed and never originate at a curated concept.
* **Curated names are excluded from the pool outright.** ``spie.concepts._merge_kb`` would ignore
  a colliding record anyway, but excluding it here means the artifact can never contain an
  out-edge *from* a curated concept — which is precisely the thing that would perturb a pinned
  word's ``expand`` (the traversal is outgoing-only).
* **Rank ``(min_hop asc, -total_weight desc, name asc)``, take the top ``cap``.** Nearer the
  curated core first, then better-attested, then alphabetical as the final tie-break, so no two
  candidates can ever tie.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Collection, Iterable

from .stream import Edges

# word -> ((relation, target), ...) and word -> {neighbour, ...}
OutEdgeMap = dict[str, tuple[tuple[str, str], ...]]


def out_edge_map(edges: Edges) -> OutEdgeMap:
    """Group the edge set by source into sorted, de-duplicated ``(relation, target)`` tuples."""
    grouped: dict[str, set[tuple[str, str]]] = {}
    for start, relation, end in edges:
        grouped.setdefault(start, set()).add((relation, end))
    return {word: tuple(sorted(pairs)) for word, pairs in sorted(grouped.items())}


def neighbour_map(edges: Edges) -> dict[str, set[str]]:
    """The undirected adjacency used for reachability (see the module docstring)."""
    neighbours: dict[str, set[str]] = {}
    for start, _relation, end in edges:
        neighbours.setdefault(start, set()).add(end)
        neighbours.setdefault(end, set()).add(start)
    return neighbours


def strengths(edges: Edges) -> dict[str, float]:
    """Total incident weight per term — the attestation proxy the ranking uses.

    Summed over a **sorted** edge list so the float accumulation order, and therefore the value,
    is a function of the edge set alone and not of dictionary insertion order."""
    totals: dict[str, float] = {}
    for (start, _relation, end), weight in sorted(edges.items()):
        totals[start] = totals.get(start, 0.0) + weight
        totals[end] = totals.get(end, 0.0) + weight
    return totals


def hop_map(
    seeds: Iterable[str], neighbours: dict[str, set[str]], max_hops: int
) -> dict[str, int]:
    """Minimum undirected hop count from any seed, out to ``max_hops`` (seeds are hop 0)."""
    hops: dict[str, int] = {}
    frontier: deque[tuple[str, int]] = deque()
    for seed in sorted(set(seeds)):
        hops[seed] = 0
        frontier.append((seed, 0))
    while frontier:
        name, distance = frontier.popleft()
        if distance >= max_hops:
            continue
        for neighbour in sorted(neighbours.get(name, ())):
            if neighbour not in hops:
                hops[neighbour] = distance + 1
                frontier.append((neighbour, distance + 1))
    return hops


def select_pool(
    edges: Edges, curated: Collection[str], *, cap: int, max_hops: int
) -> tuple[str, ...]:
    """The ranked candidate pool: non-curated terms within ``max_hops`` of the curated core.

    Returned **sorted by name** (the pool is a set; the ranking only decides membership), so
    downstream stages never depend on rank order."""
    curated_set = set(curated)
    hops = hop_map(curated_set, neighbour_map(edges), max_hops)
    weight = strengths(edges)
    candidates = [w for w, hop in hops.items() if hop >= 1 and w not in curated_set]
    candidates.sort(key=lambda w: (hops[w], -weight.get(w, 0.0), w))
    return tuple(sorted(candidates[:cap]))


__all__ = [
    "OutEdgeMap",
    "out_edge_map",
    "neighbour_map",
    "strengths",
    "hop_map",
    "select_pool",
]
