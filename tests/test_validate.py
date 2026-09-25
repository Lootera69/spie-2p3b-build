"""Static validator tests: a clean puzzle scores 100 with no findings, and each kind of
authoring mistake surfaces as its own stable rule with the expected score penalty.
"""

from __future__ import annotations

from dataclasses import replace

from spie.examples_src import move, pressure
from spie.expr import Assign, Const, Eq, Var
from spie.ir import Action, Kind, Objective, Puzzle, Variable
from spie.report import build_report
from spie.validate import validate


def _rules(puzzle: Puzzle) -> set[str]:
    return {f.rule for f in validate(puzzle)}


def test_clean_puzzle_has_no_findings():
    puzzle = move()
    findings = validate(puzzle)
    assert findings == []
    assert build_report(puzzle.id, findings).score == 100


def test_missing_initial_value():
    puzzle = replace(move(), initial={})
    assert "missing-initial" in _rules(puzzle)


def test_unknown_edge_endpoint():
    puzzle = replace(move(), edges=(*move().edges, ("A", "Z")))
    assert "unknown-edge-endpoint" in _rules(puzzle)


def test_initial_out_of_range():
    puzzle = replace(pressure(), initial={"pressure": 9, "sealed": 0})
    assert "initial-out-of-range" in _rules(puzzle)


def test_nonpositive_horizon():
    base = move()
    puzzle = replace(base, objective=replace(base.objective, max_horizon=0))
    assert "nonpositive-horizon" in _rules(puzzle)


def test_unknown_effect_target():
    puzzle = Puzzle(
        id="bad",
        title="bad",
        nodes=("A",),
        edges=(),
        variables=(Variable("x", Kind.BOOL),),
        initial={"x": 0},
        actions=(Action("boom", precondition=Const(True), effects=(Assign("ghost", Const(1)),)),),
        objective=Objective(goal=Eq(Var("x"), Const(1)), max_horizon=3),
    )
    assert "unknown-effect-target" in _rules(puzzle)


def test_score_drops_by_penalty_per_finding():
    puzzle = replace(move(), initial={})  # exactly one finding (missing pos)
    report = build_report(puzzle.id, validate(puzzle))
    assert report.score == 100 - 8 * len(report.findings)
    assert report.histogram == {"missing-initial": 1}
