"""Phase 3.8 — property-based cross-validation of the epistemic layer.

Where :mod:`test_property` searches for a puzzle on which the *fully-observable* backends
disagree, this module lifts that search to partial observability. Four properties, each the
strongest form of a Phase-3 invariant, are hunted for counterexamples by ``hypothesis``:

1. **Reduction** — on random fully-observable puzzles both epistemic methods collapse to the
   Phase-1/2 ground truth: Method A (belief-search) ≡ Method B (Z3 multi-world) ≡ ``search``
   on solvability, minimal depth, and uniqueness, and the contingent plan degenerates to the
   exact linear trace.
2. **Epistemic agreement (gate G2 lifted)** — on random hidden-state puzzles Method A ≡ Method
   B on (solvable, depth, unique), across belief sizes, not just the hand fixtures.
3. **Conformance over all worlds** — the certified policy reaches the goal legally on *every*
   world of ``B0`` and is uniform (no clairvoyance), replayed through the interpreter.
4. **Determinism** — certifying the same puzzle twice is byte-identical, across both the linear
   and contingent certificate paths.

Any counterexample is a real defect (never a warning), minimized automatically.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from spie import epistemic, search, z3_epistemic
from spie.certificate import certify
from spie.conformance import check_plan_conformance
from spie.expr import Const, Eq, Var, all_of
from spie.ir import Action, Assign, Kind, Objective, Observability, Puzzle, Variable
from spie.serialize import certificate_to_json, dumps
from test_property import small_puzzles


@st.composite
def hidden_switch_puzzles(draw):
    """A parametric "which of n switches" puzzle: a hidden ``target`` ∈ {0..n-1} that a pure
    ``probe`` senses, with one winning ``flip`` per world (legal only when it matches). No
    linear plan solves it, so the encodings must find the depth-2 probe-then-branch policy —
    Method B over n trajectories with n(n-1)/2 uniformity pairs, Method A over the belief
    fixpoint — stressing both past the singleton case across random belief sizes."""
    n = draw(st.integers(min_value=2, max_value=5))
    variables = (
        Variable("target", Kind.INT, lo=0, hi=n - 1, obs=Observability.HIDDEN),
        Variable("done", Kind.BOOL),
    )
    probe = Action(
        name="probe",
        precondition=Eq(Var("done"), Const(0)),
        effects=(),
        senses=("target",),
    )
    flips = tuple(
        Action(
            name=f"flip{k}",
            precondition=all_of(Eq(Var("target"), Const(k)), Eq(Var("done"), Const(0))),
            effects=(Assign("done", Const(1)),),
        )
        for k in range(n)
    )
    return Puzzle(
        id="prop_hidden",
        title="prop_hidden",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"target": 0, "done": 0},
        actions=(probe, *flips),
        objective=Objective(goal=Eq(Var("done"), Const(1)), max_horizon=5),
        seed=0,
        initial_belief={"target": tuple(range(n))},
    )


@settings(max_examples=60, deadline=None)
@given(puzzle=small_puzzles())
def test_reduction_epistemic_equals_search_and_bmc(puzzle):
    """Fully-observable ⇒ ``B0`` is a singleton and both epistemic methods must reduce to the
    Phase-1/2 ground truth — the reduction anchor, hunted over random puzzles."""
    ss = search.solve(puzzle)
    a = epistemic.solve_strong(puzzle)
    b = z3_epistemic.solve_strong(puzzle)
    assert a.solvable == ss.solvable == b.solvable, f"solvability disagreement on {puzzle}"
    assert b.world_count == 1, "fully-observable B0 must be a singleton"
    if not ss.solvable:
        return
    assert a.depth == ss.horizon, f"A depth {a.depth} vs search {ss.horizon} on {puzzle}"
    assert b.depth == ss.horizon, f"B depth {b.depth} vs search {ss.horizon} on {puzzle}"
    # The contingent plan degenerates to the exact linear trace search returns.
    plan = epistemic.canonical_plan(puzzle)
    assert plan is not None and plan.is_linear()
    assert list(plan.linear_trace()) == list(search.canonical_solution(puzzle).trace)
    a_u = epistemic.check_uniqueness(puzzle).unique
    b_u = z3_epistemic.check_uniqueness(puzzle).unique
    s_u = search.check_uniqueness(puzzle, ss).unique
    assert a_u == b_u == s_u, f"uniqueness disagreement on {puzzle}"


@settings(max_examples=25, deadline=None)
@given(puzzle=hidden_switch_puzzles())
def test_epistemic_methods_agree_under_uncertainty(puzzle):
    """Partial-observable ⇒ Method A ≡ Method B on (solvable, depth, unique) — gate G2 lifted,
    checked on random belief sizes rather than only the hand fixtures."""
    a = epistemic.solve_strong(puzzle)
    b = z3_epistemic.solve_strong(puzzle)
    assert a.solvable and b.solvable
    assert a.depth == b.depth == 2, f"depth {a.depth}/{b.depth} on {puzzle}"
    assert b.world_count == len(puzzle.initial_belief["target"])
    a_u = epistemic.check_uniqueness(puzzle).unique
    b_u = z3_epistemic.check_uniqueness(puzzle).unique
    assert a_u == b_u, f"uniqueness disagreement on {puzzle}"
    assert a_u is True


@settings(max_examples=25, deadline=None)
@given(puzzle=hidden_switch_puzzles())
def test_contingent_plan_conforms_on_every_world(puzzle):
    """The certified policy reaches the goal legally on *every* world of ``B0`` and is uniform
    (no clairvoyance) — replayed through the interpreter, checked not assumed."""
    plan = epistemic.canonical_plan(puzzle)
    assert plan is not None
    pc = check_plan_conformance(puzzle, plan)
    assert pc.ok and pc.reached_goal_all and pc.uniform, pc.detail
    assert len(pc.world_replays) == len(puzzle.initial_belief["target"])
    assert all(r.ok and r.reached_goal for r in pc.world_replays)


@settings(max_examples=40, deadline=None)
@given(puzzle=st.one_of(small_puzzles(), hidden_switch_puzzles()))
def test_certificate_is_byte_reproducible(puzzle):
    """Determinism: certifying the same puzzle twice yields byte-identical canonical JSON,
    across both the linear and contingent certificate paths."""
    first = dumps(certificate_to_json(certify(puzzle)))
    second = dumps(certificate_to_json(certify(puzzle)))
    assert first == second, f"non-reproducible certificate on {puzzle}"
