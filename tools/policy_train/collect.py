"""Harvest a ``(parent-context, operator, child-survived)`` corpus from SPIE's own search.

The :class:`CollectorPolicy` satisfies the exact protocol :func:`spie.mapelites.evolve` expects of a
steering policy — ``choose_niche`` / ``choose_operator(names, context)`` / ``reward(niche, op,
survived, context)`` — so the engine drives it through its normal policy code path with no special
casing. Unlike the learned policies it proposes **uniformly at random** from its own
``random.Random(rng_seed)``: an unbiased explorer gives every operator balanced, well-covered labels
across the contexts the search visits, and the fixed seed keeps the corpus byte-reproducible. Its
``reward`` hook does the only extra work — appending the training triple the engine hands it, where
the survival label is the verdict the unchanged ``validate -> verify -> certify`` gate already
reached (``placed``/``replaced`` -> 1.0, everything else -> 0.0).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from spie import mapelites
from spie.examples_src import BUILDERS

# The training triple: (parent-elite context vector, operator __name__, child survival in {0.0, 1.0}).
Triple = tuple[tuple[float, ...], str, float]

_BY_NAME = {b.__name__: b for b in BUILDERS}


@dataclass
class CollectorPolicy:
    """A uniform-random proposer that records every training triple the search produces.

    Selection draws from ``random.Random(rng_seed)`` over the *sorted* candidate set, so a given
    ``rng_seed`` yields a byte-identical trajectory. The policy never consults survival to choose
    (it only *records* it), so the harvested labels are an unbiased sample over the operators."""

    rng_seed: int = 0
    rng: random.Random = field(default_factory=random.Random)
    triples: list[Triple] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.rng_seed)

    def choose_niche(self, niches):
        """Pick an occupied niche uniformly at random (over the sorted keys, for determinism)."""
        return self.rng.choice(sorted(niches))

    def choose_operator(self, operator_names, context=None):
        """Pick an operator ``__name__`` uniformly at random (over the sorted names)."""
        return self.rng.choice(sorted(operator_names))

    def reward(self, niche, operator_name: str, survived: float, context=None) -> None:
        """Record the ``(context, operator, survived)`` triple the engine just resolved. ``context``
        is the parent elite's feature vector; it is always present on the policy path (a pure
        function of the parent), but a ``None`` is skipped defensively rather than mis-recorded."""
        if context is not None:
            self.triples.append((tuple(context), operator_name, float(survived)))


def build_corpus(grid: list[tuple[tuple[str, ...], int, int]]) -> list[Triple]:
    """Aggregate the training triples produced by running the MAP-Elites search over ``grid``.

    Each grid entry is ``(builder_names, integer_seed, iterations)``: the starting population is the
    named hand-authored example puzzles, the search runs for ``iterations`` steps under a fresh
    :class:`CollectorPolicy` seeded with ``integer_seed`` (and the engine's own RNG seeded the same),
    and every triple it records is appended. Purely a function of ``grid`` — no global state, no
    network — so the whole corpus is byte-reproducible."""
    corpus: list[Triple] = []
    for names, integer_seed, iterations in grid:
        seeds = [_BY_NAME[n]() for n in names]
        collector = CollectorPolicy(rng_seed=integer_seed)
        mapelites.evolve(seeds, iterations, integer_seed, policy=collector)
        corpus.extend(collector.triples)
    return corpus


__all__ = ["Triple", "CollectorPolicy", "build_corpus"]
