"""Phase 3.6 — reset semantics: the ``Reset`` effect marker and ``persistent`` variables.

Reset is expanded at grounding into concrete ``Assign``s, so the interpreter and Z3 never see
a new primitive; these tests pin that expansion, prove persistent state survives a reset while
transient state is snapped back, and confirm a reset puzzle certifies (cross-solver agreement +
conformance) and clears every verification gate. The negative control shows the ``persistent``
flag is load-bearing, not cosmetic.
"""

from __future__ import annotations

from reset_fixtures import reset_lock, reset_lock_no_persistence
from spie import search
from spie.certificate import certify
from spie.expr import Assign, Const, Reset
from spie.ground import ground_all
from spie.interpreter import run
from spie.serialize import dumps, puzzle_from_json, puzzle_to_json
from spie.verify import GateStatus, verify

TRACE = ["advance", "advance", "mark", "reset"]


# --- grounding: the marker expands to exactly the non-persistent initial assignments --------


def test_reset_expands_to_non_persistent_initial_assignments():
    ground = {g.name: g for g in ground_all(reset_lock())}
    reset = ground["reset"]
    # Only the transient variable `a` is restored (to its initial 0); persistent `flag` is not
    # touched, so it is framed and carries forward.
    assert reset.effects == (Assign("a", Const(0)),)


def test_reset_marker_is_not_leaked_to_ground_effects():
    # Whatever the template holds, a ground action's effects are always plain Assigns.
    for g in ground_all(reset_lock()):
        assert all(isinstance(e, Assign) for e in g.effects)


# --- semantics: persistent survives, transient snaps back ------------------------------------


def test_persistent_state_survives_reset_transient_is_restored():
    outcome = run(reset_lock(), TRACE)
    assert outcome.reached_goal
    # After the final reset: transient counter back to 0, learned flag preserved.
    assert outcome.final_state["a"] == 0
    assert outcome.final_state["flag"] == 1
    # And specifically across the reset step (index 3 -> state index 4): flag stayed 1.
    before_reset, after_reset = outcome.states[3], outcome.states[4]
    assert before_reset["flag"] == 1 and after_reset["flag"] == 1
    assert before_reset["a"] == 2 and after_reset["a"] == 0


def test_without_persistence_the_reset_clears_the_flag_and_goal_is_unreachable():
    # The negative control: flag non-persistent => reset wipes it => strongly unsolvable.
    assert not search.canonical_solution(reset_lock_no_persistence()).solvable


# --- certificate: solvable, unique, conformant, cross-solver agreement -----------------------


def test_reset_puzzle_certifies_with_agreement():
    cert = certify(reset_lock())
    assert cert.solvable and cert.unique and cert.conformance_ok
    assert [s.action for s in cert.solution] == TRACE
    # Three independent solvers (Z3 BMC + explicit search + ASP) agree on the linear case.
    assert len(cert.solvers) == 3
    assert all(e.solvable and e.unique for e in cert.solvers)
    horizons = {e.horizon for e in cert.solvers}
    assert horizons == {4}


def test_reset_puzzle_passes_every_gate():
    report = verify(reset_lock())
    failed = [(g.name, g.detail) for g in report.gates if g.status is GateStatus.FAIL]
    assert report.ok, failed


# --- serialization: the marker round-trips, reset-free actions stay byte-identical -----------


def test_reset_round_trips_byte_identical():
    p = reset_lock()
    once = dumps(puzzle_to_json(p))
    twice = dumps(puzzle_to_json(puzzle_from_json(puzzle_to_json(p))))
    assert once == twice
    # The reset action serializes its marker as {"reset": true}.
    doc = puzzle_to_json(p)
    (reset_action,) = [a for a in doc["actions"] if a["name"] == "reset"]
    assert reset_action["effects"] == [{"reset": True}]


def test_reset_marker_reconstructs_from_json():
    p = reset_lock()
    back = puzzle_from_json(puzzle_to_json(p))
    (reset_action,) = [a for a in back.actions if a.name == "reset"]
    assert reset_action.effects == (Reset(),)
