"""Phase 4.2 tests — Afford + Blend (semantic graph -> mechanic-level rule graph).

Covers Afford (every affordance instantiates its mechanic; deterministic + total over the KB),
Blend (base-skeleton selection, sorted deduplicated modifiers, deterministic provenance) and
RuleGraph well-formedness, per the Phase-4 plan's 4.2 exit criteria."""

from __future__ import annotations

import pytest

from spie.afford import (
    _AFFORDANCE_MECHANIC,
    Mechanic,
    MechanicKind,
    RuleGraph,
    afford,
    blend,
)
from spie.concepts import KB, Affordance, expand, sense


def test_affordance_mechanic_map_is_total() -> None:
    # Every affordance in the vocabulary maps to a mechanic kind.
    assert set(_AFFORDANCE_MECHANIC) == set(Affordance)
    for kind in _AFFORDANCE_MECHANIC.values():
        assert isinstance(kind, MechanicKind)


def test_afford_instantiates_each_affordance() -> None:
    g = expand(sense("fuel"), depth=1)
    mechanics = afford(g)
    kinds = {m.kind for m in mechanics}
    # fuel affords CONSUME; its neighbours (resource/travel/deplete) afford CONSUME/CONNECT.
    assert MechanicKind.CONSUME in kinds
    assert MechanicKind.CONNECT in kinds
    # Every mechanic records the concept it came from, and that concept is in the graph.
    for m in mechanics:
        assert m.source in g.concepts


def test_afford_is_deterministic_and_sorted() -> None:
    g = expand(sense("signal"), depth=3)
    a = afford(g)
    b = afford(g)
    assert a == b
    assert list(a) == sorted(a, key=lambda m: (m.kind.value, m.source))


def test_afford_dedups_kind_source_pairs() -> None:
    # A concept affording the same operation yields exactly one mechanic for that (kind, source).
    g = expand(sense("door"), depth=0)  # door alone: affords CONNECT, NEGATE
    mechanics = afford(g)
    pairs = [(m.kind, m.source) for m in mechanics]
    assert len(pairs) == len(set(pairs))
    assert {m.kind for m in mechanics} == {MechanicKind.CONNECT, MechanicKind.NEGATE}
    assert all(m.source == "door" for m in mechanics)


def test_afford_total_over_kb() -> None:
    # afford never raises and every mechanic kind is valid, for every KB concept as a root.
    for name in KB:
        for m in afford(expand(sense(name), depth=2)):
            assert isinstance(m.kind, MechanicKind)
            assert m.source in KB


def test_blend_prefers_connect_base() -> None:
    g = expand(sense("bridge"), depth=1)  # path/travel -> CONNECT present
    rg = blend(afford(g))
    assert rg.base == MechanicKind.CONNECT
    assert MechanicKind.CONNECT not in rg.modifiers
    rg.check()


def test_blend_defaults_to_chain_skeleton() -> None:
    # A resource-only mechanic set has no base kind, so the implicit chain skeleton is used.
    mechanics = (Mechanic(MechanicKind.CONSUME, "fuel"),)
    rg = blend(mechanics)
    assert rg.base == MechanicKind.CHAIN
    assert MechanicKind.CONSUME in rg.modifiers
    assert rg.provenance[MechanicKind.CHAIN] == "chain"
    assert rg.provenance[MechanicKind.CONSUME] == "fuel"
    rg.check()


def test_blend_modifiers_sorted_and_deduped() -> None:
    g = expand(sense("signal"), depth=3)
    rg = blend(afford(g))
    assert list(rg.modifiers) == sorted(rg.modifiers, key=lambda k: k.value)
    assert len(set(rg.modifiers)) == len(rg.modifiers)
    rg.check()


def test_blend_provenance_covers_exactly_mechanics() -> None:
    g = expand(sense("water"), depth=1)
    rg = blend(afford(g))
    assert set(rg.provenance) == set(rg.mechanics)
    rg.check()


def test_blend_provenance_tiebreak_is_least_concept() -> None:
    # Two concepts afford CONSUME; the lexicographically-least source wins.
    mechanics = (
        Mechanic(MechanicKind.CONSUME, "water"),
        Mechanic(MechanicKind.CONSUME, "fuel"),
    )
    rg = blend(mechanics)
    assert rg.provenance[MechanicKind.CONSUME] == "fuel"


def test_blend_is_deterministic() -> None:
    g = expand(sense("battery"), depth=2)
    assert blend(afford(g)) == blend(afford(g))


def test_blend_total_over_kb() -> None:
    # blend never raises and always returns a well-formed rule graph, for every KB concept.
    for name in KB:
        rg = blend(afford(expand(sense(name), depth=2)))
        rg.check()


def test_rulegraph_check_rejects_bad_base() -> None:
    with pytest.raises(ValueError):
        RuleGraph(
            base=MechanicKind.CONSUME,
            modifiers=(),
            provenance={MechanicKind.CONSUME: "fuel"},
            length=3,
        ).check()


def test_rulegraph_check_rejects_base_in_modifiers() -> None:
    with pytest.raises(ValueError):
        RuleGraph(
            base=MechanicKind.CHAIN,
            modifiers=(MechanicKind.CHAIN,),
            provenance={MechanicKind.CHAIN: "chain"},
            length=3,
        ).check()


def test_rulegraph_check_rejects_bad_provenance() -> None:
    with pytest.raises(ValueError):
        RuleGraph(
            base=MechanicKind.CHAIN,
            modifiers=(MechanicKind.CONSUME,),
            provenance={MechanicKind.CHAIN: "chain"},  # missing CONSUME
            length=3,
        ).check()


def test_rulegraph_check_rejects_bad_length() -> None:
    with pytest.raises(ValueError):
        RuleGraph(
            base=MechanicKind.CHAIN,
            modifiers=(),
            provenance={MechanicKind.CHAIN: "chain"},
            length=0,
        ).check()
