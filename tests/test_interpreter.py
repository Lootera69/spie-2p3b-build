"""Interpreter unit tests: the deterministic runtime is the ground truth, so its handling
of preconditions, invariants, loss, framing, and initial-state normalisation must be exact.
"""

from __future__ import annotations

import pytest

from spie.examples_src import irreversible, move, synchronize
from spie.interpreter import ExecutionError, initial_state, run


def test_initial_state_normalises_bools_and_locations():
    puzzle = irreversible()  # pos: LOC, has_gem/sealed: BOOL
    state = initial_state(puzzle)
    assert state["pos"] == 0  # "Vault" is node index 0
    assert state["has_gem"] == 0
    assert state["sealed"] == 0


def test_good_trace_reaches_goal():
    puzzle = move()
    trace = ["move[src=A,dst=B]", "move[src=B,dst=C]", "move[src=C,dst=D]"]
    outcome = run(puzzle, trace)
    assert outcome.reached_goal is True
    assert outcome.final_state["pos"] == 3  # "D"
    assert len(outcome.states) == len(trace) + 1  # initial + one per tick


def test_unknown_action_raises_with_tick():
    puzzle = move()
    with pytest.raises(ExecutionError) as exc:
        run(puzzle, ["move[src=A,dst=B]", "teleport"])
    assert exc.value.tick == 1


def test_precondition_failure_raises():
    puzzle = move()
    # A->C is not an edge, so the move guard fails immediately at tick 0.
    with pytest.raises(ExecutionError) as exc:
        run(puzzle, ["move[src=A,dst=C]"])
    assert exc.value.tick == 0


def test_invariant_violation_raises():
    puzzle = synchronize()  # invariant: doors never both open
    with pytest.raises(ExecutionError):
        run(puzzle, ["openA", "openB"])  # both doors open -> invariant broken


def test_loss_predicate_raises():
    puzzle = irreversible()  # loss: sealed while empty-handed
    with pytest.raises(ExecutionError):
        run(puzzle, ["move[src=Vault,dst=Exit]", "seal"])  # sealed with no gem


def test_framing_preserves_unwritten_variables():
    puzzle = irreversible()
    # grab writes has_gem only; pos and sealed must be framed unchanged.
    outcome = run(puzzle, ["grab"])
    assert outcome.final_state["has_gem"] == 1
    assert outcome.final_state["pos"] == 0  # still at Vault
    assert outcome.final_state["sealed"] == 0
