"""Phase 4.1 tests — the concept KB (Sense + Expand).

Covers Sense (known / unknown / normalization), Expand (bounded, deterministic, closed) and KB
integrity (no dangling edges), per the Phase-4 plan's 4.1 exit criteria."""

from __future__ import annotations

import pytest

from spie import concepts
from spie.concepts import KB, Affordance, ConceptNode, Relation, expand, sense


def test_kb_integrity_no_dangling_edges() -> None:
    # Re-running the import-time invariant explicitly: every relation target is a known concept.
    concepts._check_integrity()
    for concept in KB.values():
        for relation, targets in concept.relations.items():
            assert isinstance(relation, Relation)
            for target in targets:
                assert target in KB, f"dangling edge {concept.name} -> {target}"


def test_kb_affordances_are_valid() -> None:
    for concept in KB.values():
        for aff in concept.affordances:
            assert isinstance(aff, Affordance)


def test_sense_known_word() -> None:
    node = sense("door")
    assert isinstance(node, ConceptNode)
    assert node.name == "door"
    assert Affordance.CONNECT in node.affordances
    assert Affordance.NEGATE in node.affordances


def test_sense_normalizes_word() -> None:
    assert sense("  Door ").name == "door"
    assert sense("FUEL").name == "fuel"


def test_sense_unknown_word_raises() -> None:
    with pytest.raises(KeyError):
        sense("banana")


def test_expand_depth_zero_is_root_only() -> None:
    g = expand(sense("door"), depth=0)
    assert g.root == "door"
    assert g.concepts == ("door",)
    assert g.edges == ()


def test_expand_reaches_category_and_property() -> None:
    g = expand(sense("fuel"), depth=1)
    # fuel IsA resource, UsedFor travel, CapableOf deplete
    assert "resource" in g.concepts
    assert "travel" in g.concepts
    assert "deplete" in g.concepts
    assert ("fuel", Relation.IS_A, "resource") in g.edges


def test_expand_is_bounded_by_depth() -> None:
    shallow = set(expand(sense("fuel"), depth=1).concepts)
    deep = set(expand(sense("fuel"), depth=2).concepts)
    # resource HAS_PROPERTY finite is only reachable at depth 2.
    assert "finite" not in shallow
    assert "finite" in deep
    assert shallow <= deep


def test_expand_is_deterministic() -> None:
    a = expand(sense("signal"), depth=3)
    b = expand("signal", depth=3)  # accepts a bare name too
    assert a == b
    # concepts and edges are sorted
    assert list(a.concepts) == sorted(a.concepts)
    assert list(a.edges) == sorted(a.edges, key=lambda e: (e[0], e[1].value, e[2]))


def test_expand_negative_depth_raises() -> None:
    with pytest.raises(ValueError):
        expand(sense("door"), depth=-1)


def test_expand_unknown_root_raises() -> None:
    with pytest.raises(KeyError):
        expand("banana")


def test_graph_affordances_map() -> None:
    g = expand(sense("signal"), depth=1)
    affs = g.affordances()
    assert affs["signal"] == KB["signal"].affordances
    assert set(affs) == set(g.concepts)
