"""Phase 4.7 — ``invent``: the thin orchestration over the whole Phase-4 pipeline.

This is the entry point the CLI's ``invent`` / ``evolve`` commands call. It does no new work of
its own — it *sequences* the stages the earlier sub-phases built, so the whole roadmap-p4
INPUT→MEANING→INVENTION path is reachable from a single word:

    Sense → Expand → Afford → Blend → Operationalize → **Ablate**

* :func:`invent` runs that pipeline for one word and returns a certifiable :class:`~spie.ir.Puzzle`.
* :func:`invent_traced` returns the puzzle *and* its element-level
  :data:`~spie.operationalize.Provenance`, so the caller can run the concept-relevance gate as a
  real PASS/FAIL check (``verify(puzzle, provenance)``).
* :func:`evolve` invents a puzzle per seed word and hands them to the hand-rolled MAP-Elites
  search (:func:`spie.mapelites.evolve`) — invention feeding quality-diversity search.

**Ablate is a checked prune, never an assumption.** After operationalizing, invent ablates each
source concept by exactly the standard the minimality gate uses (:func:`spie.verify.inert_concepts`
— a concept is inert iff removing its actions leaves :func:`spie.search.signature` unchanged) and
drops any *modifier* concept that is not load-bearing, recompiling until every remaining concept
earns its place. The base skeleton concept is never dropped (removing the skeleton trivially
changes solvability). Because the pipeline is bounded and ``dropped`` grows monotonically, the loop
always terminates — in the degenerate limit at a bare, still-certifiable chain.

**Totality over the curated vocabulary.** :data:`~spie.operationalize.SUPPORTED_MODIFIERS` excludes
the epistemic/temporal mechanics (``REVEAL`` / ``DELAY``), which need the belief-space cross-check
to certify. Rather than refuse a word that affords them, invent keeps only the *compilable* core of
the afforded mechanics, so every KB word yields a fully-observable, certifiable puzzle (a word that
affords nothing else collapses to a bare forced chain). Determinism is inherited: every stage is a
pure, canonical function of its input, so ``invent(word, seed)`` is byte-reproducible.
"""

from __future__ import annotations

from dataclasses import replace

from . import mapelites
from .afford import MechanicKind, afford, blend
from .concepts import expand, normalize, sense
from .ir import Puzzle
from .mapelites import Archive
from .operationalize import SUPPORTED_MODIFIERS, Provenance, operationalize_traced
from .verify import inert_concepts

# The mechanic kinds operationalize compiles into a certifiable fully-observable puzzle: the
# CONNECT base skeleton plus the supported modifiers. Afforded REVEAL/DELAY mechanics are dropped
# so invent stays total over the vocabulary, emitting the observable core of any word.
_COMPILABLE = frozenset({MechanicKind.CONNECT}) | SUPPORTED_MODIFIERS


def invent_traced(
    word: str, seed: int = 0, depth: int = 2, length: int = 3
) -> tuple[Puzzle, Provenance]:
    """Run the full pipeline for ``word`` and return the certifiable puzzle plus its provenance.

    Sense/Expand/Afford/Blend build a rule graph from the word's curated meaning; Operationalize
    compiles it to a :class:`~spie.ir.Puzzle`; the Ablate loop then drops any modifier concept the
    solver cannot observe the effect of, recompiling until every source concept is load-bearing."""
    node = sense(word)
    graph = expand(node, depth)
    mechanics = tuple(m for m in afford(graph) if m.kind in _COMPILABLE)
    dropped: set[str] = set()
    while True:
        usable = tuple(m for m in mechanics if m.source not in dropped)
        rule_graph = blend(usable, length=length)
        puzzle, prov = operationalize_traced(rule_graph, seed)
        base_concept = rule_graph.provenance[rule_graph.base]
        inert = tuple(c for c in inert_concepts(puzzle, prov) if c != base_concept)
        if not inert:
            return puzzle, prov
        dropped.update(inert)


def invent(word: str, seed: int = 0, depth: int = 2, length: int = 3) -> Puzzle:
    """Invent a certifiable :class:`~spie.ir.Puzzle` from a single word (see :func:`invent_traced`
    for the provenance-carrying variant used to drive the concept-relevance gate)."""
    return invent_traced(word, seed=seed, depth=depth, length=length)[0]


def evolve(
    seeds: list[str], iterations: int, seed: int = 0, policy: mapelites.Policy | None = None
) -> Archive:
    """Invent one puzzle per seed word, then run the deterministic MAP-Elites search over them.

    Each seed puzzle is renamed ``inv_<word>`` so distinct words never collide on a generated id;
    the archive is byte-reproducible for a given ``(seeds, iterations, seed)`` exactly as
    :func:`spie.mapelites.evolve` guarantees (the seeds here are just its starting population).
    ``policy`` is threaded straight through: ``None`` (the default) keeps the uniform historical
    search byte-identical, while a steering / contextual / frozen proposer only biases *which*
    operator and niche to try — the formal gate stays the sole authority on acceptance."""
    puzzles = [replace(invent(w, seed=seed), id=f"inv_{normalize(w)}") for w in seeds]
    return mapelites.evolve(puzzles, iterations, seed, policy=policy)


__all__ = ["invent", "invent_traced", "evolve"]
