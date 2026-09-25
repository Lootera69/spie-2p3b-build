"""The verification suite (Phase 2, D3): every gate audited with a positive and a negative.

The whole corpus must pass every gate (the design-quality bar). Then each gate is fired
deliberately by a minimal fixture — a puzzle that violates exactly that gate's contract — so
we prove the gate *detects* the fault, not merely that clean puzzles pass. The determinism
gate gets a dedicated regression fixture (08_two_solutions), the non-unique puzzle whose Z3
model used to flip between two equally-minimal traces before certificates were pinned to the
canonical (lexicographically-least) solution.
"""

from __future__ import annotations

import dataclasses

from epistemic_fixtures import which_switch, which_switch_three
from spie import search
from spie.certificate import certify
from spie.examples_src import BUILDERS, irreversible, move, two_solutions
from spie.expr import Const, Edge, Eq, Node, PVal, Var, all_of
from spie.ir import Action, Assign, Kind, Objective, Observability, Param, Puzzle, Variable
from spie.serialize import certificate_to_json, dumps
from spie.verify import GateStatus, verify


def _gate(report, name):
    """The single gate with this name (there is exactly one of each per report)."""
    (gate,) = [g for g in report.gates if g.name == name]
    return gate


# --- positive: the whole corpus clears every gate -----------------------------------


def test_corpus_passes_every_gate():
    for builder in BUILDERS:
        report = verify(builder())
        failed = [(g.name, g.detail) for g in report.gates if g.status is GateStatus.FAIL]
        assert report.ok, f"{report.puzzle_id}: {failed}"


def test_concept_relevance_is_deferred_not_skipped():
    # The one gate that is honestly INFO rather than PASS/FAIL until the semantics phase.
    assert _gate(verify(move()), "concept-relevance").status is GateStatus.INFO


# --- negative: uniqueness -----------------------------------------------------------


def test_uniqueness_gate_fails_when_declaration_violated():
    # 08 is genuinely non-unique; flip its declaration to demand uniqueness and the gate fires.
    p = two_solutions()
    p = dataclasses.replace(p, objective=dataclasses.replace(p.objective, requires_unique=True))
    gate = _gate(verify(p), "uniqueness")
    assert gate.status is GateStatus.FAIL
    assert any(f.rule == "uniqueness-violated" for f in gate.findings)


# --- negative: dead-state fairness --------------------------------------------------


def test_dead_state_gate_fails_on_silent_trap_under_signaled():
    # 05 has a live trap: at Exit empty-handed the only move (seal) is a loss, so it is a
    # silent dead-end. Allowed by default; under "signaled" the gate must catch it.
    p = irreversible()
    p = dataclasses.replace(p, objective=dataclasses.replace(p.objective, trap_policy="signaled"))
    gate = _gate(verify(p), "dead-state")
    assert gate.status is GateStatus.FAIL
    assert any(f.rule == "silent-trap" for f in gate.findings)


def test_dead_state_gate_allows_traps_under_allowed_policy():
    # Same puzzle, default policy: the trap is an intended mechanic, so the gate passes.
    assert _gate(verify(irreversible()), "dead-state").status is GateStatus.PASS


# --- negative: shortcut -------------------------------------------------------------


def _cost_shortcut_puzzle() -> Puzzle:
    """A cheap two-hop path (cost 2) undercuts an expensive one-step warp (cost 5), so the
    minimal-*length* solution is not cost-optimal — exactly what the shortcut gate forbids."""
    nodes = ("S", "M", "G")
    hop = Action(
        name="hop",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("pos", PVal("dst")),),
        cost=1,
    )
    warp = Action(
        name="warp",
        precondition=Eq(Var("pos"), Node("S")),
        effects=(Assign("pos", Node("G")),),
        cost=5,
    )
    return Puzzle(
        id="fx_cost_shortcut",
        title="Warp vs Hop",
        nodes=nodes,
        edges=(("S", "M"), ("M", "G")),
        variables=(Variable("pos", Kind.LOC),),
        initial={"pos": "S"},
        actions=(hop, warp),
        objective=Objective(goal=Eq(Var("pos"), Node("G")), max_horizon=6, requires_unique=False),
        seed=101,
    )


def test_shortcut_gate_fails_when_a_cheaper_path_exists():
    gate = _gate(verify(_cost_shortcut_puzzle()), "shortcut")
    assert gate.status is GateStatus.FAIL
    assert any(f.rule == "cost-shortcut" for f in gate.findings)


# --- negative: minimality -----------------------------------------------------------


def _redundant_puzzle() -> Puzzle:
    """01_move with a never-firing action bolted on: its precondition is unsatisfiable, so it
    contributes no edges and its removal leaves the behavioural signature untouched."""
    base = move()
    dead = Action(
        name="noop", precondition=Eq(Const(0), Const(1)), effects=(Assign("pos", Node("A")),)
    )
    return dataclasses.replace(base, id="fx_redundant", actions=base.actions + (dead,))


def test_minimality_gate_flags_a_redundant_element():
    gate = _gate(verify(_redundant_puzzle()), "minimality")
    assert gate.status is GateStatus.FAIL
    assert any(f.rule == "redundant-element" for f in gate.findings)


# --- determinism: the canonical-solution regression ---------------------------------


def test_determinism_gate_passes_on_nonunique_puzzle():
    # 08 has two equally-minimal traces; the certificate records the canonical (lex-least)
    # one, a function of the puzzle alone, so bytes are stable even here.
    assert _gate(verify(two_solutions()), "determinism").status is GateStatus.PASS


def test_certificate_records_the_canonical_solution():
    p = two_solutions()
    canon = search.canonical_solution(p)
    # Lexicographically least: the L branch precedes the R branch.
    assert canon.trace == ["move[src=S,dst=L]", "move[src=L,dst=G]"]
    cert = certify(p)
    assert [s.action for s in cert.solution] == canon.trace
    # And byte-identical across independent certifications.
    runs = {dumps(certificate_to_json(certify(p))) for _ in range(4)}
    assert len(runs) == 1


# --- Phase 3: the epistemic gates ---------------------------------------------------


def test_epistemic_fixtures_pass_every_gate():
    # The branching-plan fixtures must clear every gate in epistemic mode, just as the
    # fully-observable corpus does in concrete mode.
    for builder in (which_switch, which_switch_three):
        report = verify(builder())
        failed = [(g.name, g.detail) for g in report.gates if g.status is GateStatus.FAIL]
        assert report.ok, f"{report.puzzle_id}: {failed}"


def test_epistemic_report_uses_the_conformance_gate():
    # In epistemic mode the concrete-only gates give way to their epistemic analogues; the
    # fairness/uniformity theorem is audited by the conformance gate.
    report = verify(which_switch())
    names = {g.name for g in report.gates}
    assert "conformance" in names
    assert "shortcut" not in names  # a concrete-only gate, absent under hidden state
    assert _gate(report, "conformance").status is GateStatus.PASS


# --- negative: observability --------------------------------------------------------


def test_observability_gate_fails_on_out_of_range_belief():
    # A belief support value (5) outside target's BOOL domain is an inconsistent info model.
    # The out-of-range world is filtered from B0, so the solver still runs — only this gate
    # fires, proving it detects the malformed declaration rather than crashing.
    p = which_switch()
    p = dataclasses.replace(p, initial_belief={"target": (0, 1, 5)})
    gate = _gate(verify(p), "observability")
    assert gate.status is GateStatus.FAIL
    assert any(f.rule == "belief-out-of-range" for f in gate.findings)


# --- negative: information-necessity ------------------------------------------------


def _redundant_sense_puzzle() -> Puzzle:
    """which_switch with a second, duplicate sensing action: now either probe alone suffices,
    so neither sense is individually load-bearing — removing one leaves the puzzle strongly
    solvable through the other."""
    base = which_switch()
    probe2 = dataclasses.replace(
        next(a for a in base.actions if a.name == "probe"), name="probe2"
    )
    return dataclasses.replace(
        base,
        id="fx_redundant_sense",
        actions=base.actions + (probe2,),
        objective=dataclasses.replace(base.objective, requires_unique=False),
    )


def test_information_necessity_gate_flags_a_redundant_sense():
    gate = _gate(verify(_redundant_sense_puzzle()), "information-necessity")
    assert gate.status is GateStatus.FAIL
    assert any(f.rule == "redundant-sense" for f in gate.findings)


def test_information_necessity_gate_passes_when_the_sense_is_load_bearing():
    # which_switch cannot be solved without probing, so its single sense is load-bearing.
    assert _gate(verify(which_switch()), "information-necessity").status is GateStatus.PASS


# --- negative: epistemic-reduction --------------------------------------------------


def _vacuous_hidden_puzzle() -> Puzzle:
    """Hidden state is declared, but a single target-independent action wins in every world, so
    the strong plan never branches on an observation — the information model is vacuous."""
    variables = (
        Variable("target", Kind.BOOL, obs=Observability.HIDDEN),
        Variable("done", Kind.BOOL),
    )
    win = Action(
        name="win",
        precondition=Eq(Var("done"), Const(0)),
        effects=(Assign("done", Const(1)),),
    )
    return Puzzle(
        id="fx_vacuous_hidden",
        title="Vacuous Hidden",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"target": 0, "done": 0},
        actions=(win,),
        objective=Objective(goal=Eq(Var("done"), Const(1)), max_horizon=5, requires_unique=False),
        seed=310,
        initial_belief={"target": (0, 1)},
    )


def test_epistemic_reduction_gate_fails_on_a_vacuous_information_model():
    gate = _gate(verify(_vacuous_hidden_puzzle()), "epistemic-reduction")
    assert gate.status is GateStatus.FAIL
    assert any(f.rule == "vacuous-information-model" for f in gate.findings)


def test_epistemic_reduction_gate_passes_when_the_plan_genuinely_branches():
    assert _gate(verify(which_switch()), "epistemic-reduction").status is GateStatus.PASS


def test_epistemic_reduction_holds_for_the_fully_observable_corpus():
    # Every fully-observable puzzle's contingent plan must collapse to its linear trace.
    for builder in BUILDERS:
        assert _gate(verify(builder()), "epistemic-reduction").status is GateStatus.PASS
