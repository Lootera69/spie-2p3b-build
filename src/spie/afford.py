"""Phase 4.2 — Afford + Blend: turn a semantic graph into a mechanic-level rule graph.

This is the middle of the roadmap's INPUT→MEANING pipeline. :func:`afford` reads the puzzle
:class:`~spie.concepts.Affordance`\\ s off the concepts in a :class:`~spie.concepts.SemanticGraph`
and instantiates a :class:`Mechanic` for each; :func:`blend` couples those mechanics into a single
:class:`RuleGraph` — a backend-agnostic description of the intended puzzle, one level above the
DSL. Stage 4.3 (``operationalize``) compiles a :class:`RuleGraph` into an executable
:class:`~spie.ir.Puzzle`.

Like :mod:`spie.concepts` this module holds *only data and deterministic transforms* — it builds
no :class:`~spie.ir.Puzzle` and imports nothing from the semantic core. Every output is a
deterministic, sorted function of its input, so the pipeline stays byte-reproducible, and every
mechanic records the concept it came from (``provenance``) so stage 4.6 can ablate concepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .concepts import Affordance, SemanticGraph


class MechanicKind(str, Enum):
    """A puzzle mechanic template. One :attr:`CHAIN`/:attr:`CONNECT` acts as the skeleton; the
    rest decorate it. Each maps 1:1 from an :class:`~spie.concepts.Affordance` except
    :attr:`CHAIN`, the implicit base skeleton every rule graph carries."""

    CHAIN = "chain"          # forced linear transformation skeleton (the default base)
    CONNECT = "connect"      # movement along a path (an alternative base)
    CONSUME = "consume"      # a resource depleted as the chain advances
    REVEAL = "reveal"        # a hidden fact sensed, then acted on
    DELAY = "delay"          # a lagged readout of a hidden fact
    PRESERVE = "preserve"    # persistent state surviving a reset
    NEGATE = "negate"        # a guard/gate that blocks a step until satisfied
    PROPAGATE = "propagate"  # a coupled-variable transfer


# Affordance -> the mechanic it affords. A total map over the affordance vocabulary.
_AFFORDANCE_MECHANIC: dict[Affordance, MechanicKind] = {
    Affordance.CONNECT: MechanicKind.CONNECT,
    Affordance.CONSUME: MechanicKind.CONSUME,
    Affordance.REVEAL: MechanicKind.REVEAL,
    Affordance.DELAY: MechanicKind.DELAY,
    Affordance.PRESERVE: MechanicKind.PRESERVE,
    Affordance.NEGATE: MechanicKind.NEGATE,
    Affordance.PROPAGATE: MechanicKind.PROPAGATE,
}

# Which mechanic kinds may serve as the base skeleton, in preference order.
_BASE_PREFERENCE: tuple[MechanicKind, ...] = (MechanicKind.CONNECT, MechanicKind.CHAIN)


@dataclass(frozen=True)
class Mechanic:
    """One instantiated mechanic template with its provenance.

    ``source`` is the concept name that afforded this mechanic — the thread stage 4.6 follows to
    prove each concept is load-bearing."""

    kind: MechanicKind
    source: str


@dataclass(frozen=True)
class RuleGraph:
    """A coupled set of mechanics — the mechanic-level IR between meaning and the DSL.

    * ``base`` — the skeleton mechanic (:attr:`MechanicKind.CHAIN` or :attr:`MechanicKind.CONNECT`).
    * ``modifiers`` — the remaining mechanic kinds, sorted and deduplicated, layered on the base.
    * ``provenance`` — every mechanic kind present (base included) → the concept it came from.
    * ``length`` — the number of forced steps in the skeleton (chain length / path hops).

    A rule graph is *well-formed* when its base is a valid skeleton kind, its modifiers are
    distinct and exclude the base, and ``provenance`` covers exactly the mechanics present — the
    invariant :func:`RuleGraph.check` asserts and the tests exercise."""

    base: MechanicKind
    modifiers: tuple[MechanicKind, ...]
    provenance: dict[MechanicKind, str]
    length: int

    @property
    def mechanics(self) -> tuple[MechanicKind, ...]:
        """Every mechanic kind present, base first then modifiers (sorted)."""
        return (self.base, *self.modifiers)

    def check(self) -> None:
        """Assert well-formedness; raise :class:`ValueError` otherwise."""
        if self.base not in _BASE_PREFERENCE:
            raise ValueError(f"rule-graph base {self.base} is not a skeleton kind")
        if len(set(self.modifiers)) != len(self.modifiers):
            raise ValueError("rule-graph modifiers contain a duplicate")
        if self.base in self.modifiers:
            raise ValueError("rule-graph base also appears as a modifier")
        present = set(self.mechanics)
        if set(self.provenance) != present:
            raise ValueError("rule-graph provenance does not cover exactly the mechanics present")
        if self.length < 1:
            raise ValueError(f"rule-graph length must be >= 1, got {self.length}")


def afford(graph: SemanticGraph) -> tuple[Mechanic, ...]:
    """Afford: instantiate a :class:`Mechanic` for every affordance carried by a concept in the
    graph. Deterministic: mechanics are returned sorted by ``(kind, source)`` and deduplicated on
    that pair, so a concept that affords the same operation twice yields one mechanic."""
    found: set[Mechanic] = set()
    affordances = graph.affordances()
    for concept in sorted(affordances):
        for aff in affordances[concept]:
            found.add(Mechanic(kind=_AFFORDANCE_MECHANIC[aff], source=concept))
    return tuple(sorted(found, key=lambda m: (m.kind.value, m.source)))


def blend(mechanics: tuple[Mechanic, ...], length: int = 3) -> RuleGraph:
    """Blend: couple a set of mechanics into a single well-formed :class:`RuleGraph`.

    The base skeleton is the most-preferred base kind present (movement over a bare chain),
    defaulting to :attr:`MechanicKind.CHAIN` when none of the mechanics is a base kind. Remaining
    kinds become sorted, deduplicated modifiers. When several concepts afford the same mechanic,
    the lexicographically-least source concept is recorded as its provenance (a deterministic
    tie-break). ``length`` sets the skeleton's forced-step count."""
    # Provenance: least source concept per kind, deterministic.
    by_kind: dict[MechanicKind, str] = {}
    for m in sorted(mechanics, key=lambda m: (m.kind.value, m.source)):
        if m.kind not in by_kind:
            by_kind[m.kind] = m.source

    present = set(by_kind)
    base = next((b for b in _BASE_PREFERENCE if b in present), MechanicKind.CHAIN)
    if MechanicKind.CHAIN not in by_kind:
        # The skeleton is always present; if no concept afforded a base, the chain is implicit.
        by_kind.setdefault(base, "chain")
    modifiers = tuple(sorted((k for k in by_kind if k != base), key=lambda k: k.value))

    graph = RuleGraph(base=base, modifiers=modifiers, provenance=by_kind, length=length)
    graph.check()
    return graph


__all__ = [
    "MechanicKind",
    "Mechanic",
    "RuleGraph",
    "afford",
    "blend",
]
