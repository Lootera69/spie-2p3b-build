"""Phase 3.9a — the DELAYED observation-history compilation (``augment.desugar``).

``desugar`` rewrites DELAYED variables into a hidden shift register whose final stage is a
VISIBLE lagged readout, so every solver, the interpreter, and conformance run unchanged and
Method A ≡ Method B holds *by construction* (both solve the same compiled puzzle). These tests
pin the three obligations of that design:

* **Reduction anchor / identity** — ``desugar`` is the identity (same object) on any puzzle
  with no DELAYED/REMEMBERED variable, so the 18 pre-existing certificates stay byte-identical.
* **Correct compilation** — a hand DELAYED fixture desugars to exactly the expected
  VISIBLE/HIDDEN shape, and is idempotent.
* **Solving** — on the compiled puzzle Method A and Method B agree (solvable, depth, unique),
  the certified plan conforms uniformly on every world, and the lagged readout is *load-bearing*
  (blinding it makes the puzzle unsolvable).
"""

from __future__ import annotations

from dataclasses import replace

from spie import augment, epistemic, z3_epistemic
from spie import expr as E
from spie.certificate import certify
from spie.conformance import check_plan_conformance
from spie.examples_src import BUILDERS, delayed_signal, remembered_recall
from spie.ir import Kind, Observability
from spie.serialize import certificate_to_json, dumps


def _by_key(puzzle):
    return {v.key: v for v in puzzle.variables}


def _read_keys(node: E.Expr) -> set[str]:
    """Every variable key read anywhere in an expression tree (targets aren't expressions)."""
    match node:
        case E.Var(key):
            return {key}
        case E.Not(operand):
            return _read_keys(operand)
        case E.And(operands) | E.Or(operands):
            return set().union(*(_read_keys(o) for o in operands)) if operands else set()
        case E.Add(a, b) | E.Sub(a, b) | E.Eq(a, b) | E.Lt(a, b) | E.Le(a, b) | E.Edge(a, b):
            return _read_keys(a) | _read_keys(b)
        case E.Ite(c, t, e):
            return _read_keys(c) | _read_keys(t) | _read_keys(e)
        case _:
            return set()


def test_desugar_is_identity_on_non_delayed_corpus():
    """No DELAYED/REMEMBERED variable ⇒ desugar returns the puzzle unchanged (the same object),
    the reduction anchor that keeps the fully-observable and plain-hidden corpus byte-identical."""
    for builder in BUILDERS:
        puzzle = builder()
        history = (Observability.DELAYED, Observability.REMEMBERED)
        if any(v.obs in history for v in puzzle.variables):
            continue
        assert augment.desugar(puzzle) is puzzle, f"{puzzle.id} was rewritten by desugar"


def test_delayed_desugars_to_expected_shift_register():
    """The delay-2 fixture compiles to: true var HIDDEN, one HIDDEN buffer, and a VISIBLE
    readout, with belief and initial values as designed."""
    puzzle = delayed_signal()
    desugared = augment.desugar(puzzle)
    vk = _by_key(desugared)
    assert set(vk) == {"signal", "done", "signal$lag1", "signal$lag2"}
    assert vk["signal"].obs is Observability.HIDDEN and vk["signal"].delay == 0
    assert vk["signal$lag1"].obs is Observability.HIDDEN
    assert vk["signal$lag2"].obs is Observability.VISIBLE
    # The true signal keeps its authored uncertain belief; the intermediate buffer is pinned.
    assert desugared.initial_belief["signal"] == (0, 1)
    assert desugared.initial_belief["signal$lag1"] == (0,)
    assert "signal$lag2" not in desugared.initial_belief  # visible ⇒ no belief support
    assert desugared.initial["signal$lag1"] == 0 and desugared.initial["signal$lag2"] == 0
    # Every action gains the two shift assignments, appended after its own effects.
    for action in desugared.actions:
        tail = tuple(e.key for e in action.effects[-2:])
        assert tail == ("signal$lag1", "signal$lag2"), action.name


def test_desugar_is_idempotent():
    """desugar's output has no DELAYED/REMEMBERED variable, so re-running it is the identity."""
    once = augment.desugar(delayed_signal())
    assert augment.desugar(once) is once


def test_delayed_methods_agree_and_conform():
    """Method A ≡ Method B on the compiled puzzle (checked, never assumed), and the certified
    contingent plan reaches the goal uniformly on every world of B0."""
    puzzle = delayed_signal()
    a = epistemic.solve_strong(puzzle)
    b = z3_epistemic.solve_strong(puzzle)
    assert a.solvable and b.solvable
    assert a.depth == b.depth == 3, f"depth {a.depth}/{b.depth}"
    assert b.world_count == 2
    a_u = epistemic.check_uniqueness(puzzle).unique
    b_u = z3_epistemic.check_uniqueness(puzzle).unique
    assert a_u == b_u is True

    plan = epistemic.canonical_plan(puzzle)
    assert plan is not None and plan.branch_factor() >= 2  # genuinely branches on the readout
    pc = check_plan_conformance(puzzle, plan)
    assert pc.ok and pc.reached_goal_all and pc.uniform, pc.detail
    assert len(pc.world_replays) == 2
    assert all(r.ok and r.reached_goal for r in pc.world_replays)


def test_lagged_readout_is_load_bearing():
    """Necessity: the lagged readout is the puzzle's only information channel. Blind it (make
    ``signal`` a plain HIDDEN with no sensing and no lag) and the puzzle becomes unsolvable —
    the two worlds are forever indistinguishable, so uniformity forbids a correct commit."""
    puzzle = delayed_signal()
    assert epistemic.solve_strong(puzzle).solvable
    blinded_vars = tuple(
        replace(v, obs=Observability.HIDDEN, delay=0) if v.key == "signal" else v
        for v in puzzle.variables
    )
    blinded = replace(puzzle, variables=blinded_vars)
    assert not epistemic.solve_strong(blinded).solvable
    assert not z3_epistemic.solve_strong(blinded).solvable


def test_delayed_certificate_is_byte_reproducible():
    """The contingent certificate over the compiled puzzle is byte-identical across runs."""
    first = dumps(certificate_to_json(certify(delayed_signal())))
    second = dumps(certificate_to_json(certify(delayed_signal())))
    assert first == second


# --- Phase 3.9b — REMEMBERED (the latch) ----------------------------------------------------


def test_remembered_desugars_to_expected_latch():
    """The REMEMBERED fixture compiles to: true var HIDDEN (belief preserved), plus a VISIBLE
    persistent INT latch whose domain widens by one for the out-of-range sentinel; the sensing
    action snapshots true x into the latch and drops x from its senses; every authored read is
    redirected to the latch (never transient x)."""
    puzzle = remembered_recall()
    desugared = augment.desugar(puzzle)
    vk = _by_key(desugared)
    assert set(vk) == {"code", "phase", "entered", "code$mem"}
    # True code is now the unobservable ground truth; its authored belief support is preserved.
    assert vk["code"].obs is Observability.HIDDEN
    assert desugared.initial_belief["code"] == (0, 1)
    # The latch: VISIBLE, persistent, INT, domain [0, hi+1] initialised to the sentinel hi+1.
    mem = vk["code$mem"]
    assert mem.obs is Observability.VISIBLE and mem.persistent is True
    assert mem.kind is Kind.INT and (mem.lo, mem.hi) == (0, 2)
    assert desugared.initial["code$mem"] == 2  # the "not yet observed" sentinel
    assert "code$mem" not in desugared.initial_belief  # visible ⇒ no belief support
    # The sensing action snapshots TRUE code into the latch and no longer senses code.
    ak = {a.name: a for a in desugared.actions}
    read = ak["read"]
    assert "code" not in read.senses
    assert read.effects[-1] == E.Assign("code$mem", E.Var("code"))
    # Authored reads of code are redirected to the latch; the enter guards test code$mem.
    for name in ("enter0", "enter1"):
        keys = _read_keys(ak[name].precondition)
        assert "code$mem" in keys and "code" not in keys
    # The wipe still writes TRUE code (effect targets are never renamed).
    wipe_targets = {e.key for e in ak["wipe"].effects if isinstance(e, E.Assign)}
    assert "code" in wipe_targets


def test_remembered_is_idempotent():
    """desugar's output has no REMEMBERED variable, so re-running it is the identity."""
    once = augment.desugar(remembered_recall())
    assert augment.desugar(once) is once


def test_remembered_methods_agree_and_conform():
    """Method A ≡ Method B on the compiled latch puzzle (checked, never assumed), and the
    certified contingent plan reaches the goal uniformly on both worlds of B0."""
    puzzle = remembered_recall()
    a = epistemic.solve_strong(puzzle)
    b = z3_epistemic.solve_strong(puzzle)
    assert a.solvable and b.solvable
    assert a.depth == b.depth == 3, f"depth {a.depth}/{b.depth}"
    assert b.world_count == 2
    a_u = epistemic.check_uniqueness(puzzle).unique
    b_u = z3_epistemic.check_uniqueness(puzzle).unique
    assert a_u == b_u is True

    plan = epistemic.canonical_plan(puzzle)
    assert plan is not None and plan.branch_factor() >= 2  # branches on the remembered readout
    pc = check_plan_conformance(puzzle, plan)
    assert pc.ok and pc.reached_goal_all and pc.uniform, pc.detail
    assert len(pc.world_replays) == 2
    assert all(r.ok and r.reached_goal for r in pc.world_replays)


def test_latch_is_load_bearing():
    """Necessity: the latch is the only surviving record of the vanished code. Blind the sense
    (so nothing is ever snapshotted) and the latch stays stranded at the sentinel — the player
    can never learn which code to enter, so the puzzle becomes unsolvable in both methods.

    This is stronger than plain HIDDEN+sensing: the true code is *wiped* before the commit, so
    plan-branching cannot 'remember for free' — only the persistent latch keeps the worlds
    distinguishable after reconvergence."""
    puzzle = remembered_recall()
    assert epistemic.solve_strong(puzzle).solvable
    blinded_actions = tuple(
        replace(act, senses=tuple(k for k in act.senses if k != "code"))
        for act in puzzle.actions
    )
    blinded = replace(puzzle, actions=blinded_actions)
    assert not epistemic.solve_strong(blinded).solvable
    assert not z3_epistemic.solve_strong(blinded).solvable


def test_remembered_certificate_is_byte_reproducible():
    """The contingent certificate over the compiled latch puzzle is byte-identical across runs."""
    first = dumps(certificate_to_json(certify(remembered_recall())))
    second = dumps(certificate_to_json(certify(remembered_recall())))
    assert first == second
