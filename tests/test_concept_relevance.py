"""Phase 4.6 tests — Ablate / concept-relevance.

The Ablate stage closes the roadmap-p4 pipeline loop: a *generated* puzzle carries provenance
(which concept produced which action), and a concept counts as **used** only if removing the
actions it contributed changes the puzzle's behavioral :func:`~spie.search.signature`. These
tests prove (a) ``operationalize_traced`` emits a provenance that exactly partitions the puzzle's
actions (so it can never drift from the emitted names), (b) every concept of a generated puzzle
is load-bearing and the concept-relevance gate PASSes, (c) an inert concept (a decoy action) is
caught as ``inert-concept`` and FAILs the gate, and (d) a provenance-free hand puzzle keeps the
deferred INFO verdict verbatim — the 20-corpus verify reports stay byte-identical.
"""

from __future__ import annotations

import random
from dataclasses import replace

from spie.afford import MechanicKind, RuleGraph
from spie.certificate import certify
from spie.examples_src import BUILDERS
from spie.operationalize import operationalize_traced
from spie.operators import add_decoy_action
from spie.search import signature
from spie.validate import validate
from spie.verify import GateStatus, concept_relevance, verify

BY_NAME = {b.__name__: b for b in BUILDERS}


def _rg(base: MechanicKind, modifiers: tuple[MechanicKind, ...], length: int = 3) -> RuleGraph:
    """A well-formed rule graph with a distinct synthetic concept behind every mechanic, so each
    concept's provenance is a separable action set."""
    prov = {base: base.value}
    prov.update({m: m.value for m in modifiers})
    rg = RuleGraph(base=base, modifiers=modifiers, provenance=prov, length=length)
    rg.check()
    return rg


def _gate(report) -> object:
    return next(g for g in report.gates if g.name == "concept-relevance")


# --- Provenance is a faithful, drift-proof partition of the emitted actions -----------------


def test_traced_provenance_partitions_every_action() -> None:
    puzzle, prov = operationalize_traced(_rg(MechanicKind.CHAIN, (MechanicKind.CONSUME,)))
    credited = [name for names in prov.values() for name in names]
    assert sorted(credited) == sorted(a.name for a in puzzle.actions)  # covers all
    assert len(credited) == len(set(credited))  # disjoint: no action credited twice


def test_traced_provenance_is_canonical_and_deterministic() -> None:
    a = operationalize_traced(_rg(MechanicKind.CONNECT, (MechanicKind.NEGATE,)), seed=3)
    b = operationalize_traced(_rg(MechanicKind.CONNECT, (MechanicKind.NEGATE,)), seed=3)
    assert a[1] == b[1]
    for names in a[1].values():
        assert list(names) == sorted(set(names))  # sorted + de-duplicated


# --- A generated puzzle: every source concept is load-bearing -------------------------------


def test_generated_puzzle_has_no_inert_concept() -> None:
    puzzle, prov = operationalize_traced(
        _rg(MechanicKind.CHAIN, (MechanicKind.CONSUME, MechanicKind.NEGATE))
    )
    assert concept_relevance(puzzle, prov) == ()


def test_concept_relevance_gate_passes_for_a_generated_puzzle() -> None:
    puzzle, prov = operationalize_traced(_rg(MechanicKind.CONNECT, (MechanicKind.PROPAGATE,)))
    assert validate(puzzle) == []
    assert certify(puzzle).solvable
    report = verify(puzzle, prov)
    gate = _gate(report)
    assert gate.status is GateStatus.PASS
    assert report.ok
    assert f"all {len(prov)}" in gate.detail


# --- An inert concept is caught ------------------------------------------------------------


def test_inert_concept_is_flagged() -> None:
    puzzle, prov = operationalize_traced(_rg(MechanicKind.CHAIN, (MechanicKind.CONSUME,)))
    base = puzzle
    withdecoy = add_decoy_action(base, random.Random(0))
    assert withdecoy is not None
    # The decoy is inert: it only writes a variable to itself, so removing it cannot change the
    # signature. Credit a fake concept to it; every real concept still maps to load-bearing work.
    padded = dict(prov)
    padded["decoy_concept"] = ("decoy",)
    findings = concept_relevance(withdecoy, padded)
    assert [f.rule for f in findings] == ["inert-concept"]
    assert "decoy_concept" in findings[0].message
    # The decoy really is behavior-preserving (guards the test's premise).
    kept = tuple(a for a in withdecoy.actions if a.name != "decoy")
    assert signature(replace(withdecoy, actions=kept)) == signature(withdecoy)


def test_concept_relevance_gate_fails_on_inert_concept() -> None:
    puzzle, prov = operationalize_traced(_rg(MechanicKind.CHAIN, (MechanicKind.NEGATE,)))
    withdecoy = add_decoy_action(puzzle, random.Random(0))
    assert withdecoy is not None
    padded = {**prov, "decoy_concept": ("decoy",)}
    report = verify(withdecoy, padded)
    gate = _gate(report)
    assert gate.status is GateStatus.FAIL
    assert not report.ok
    assert any(f.rule == "inert-concept" for f in gate.findings)


# --- A provenance-free hand puzzle stays deferred (INFO), byte-for-byte ----------------------


def test_hand_puzzle_concept_relevance_stays_info() -> None:
    report = verify(BY_NAME["move"]())
    gate = _gate(report)
    assert gate.status is GateStatus.INFO
    assert gate.detail == "deferred to the semantics phase — no concepts exist to ablate yet"
    assert gate.findings == ()
