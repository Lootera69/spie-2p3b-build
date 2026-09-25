"""Phase 3.2 — the belief-space solver (:mod:`spie.epistemic`), Method A.

Two things are proven here:

1. **Reduction oracle.** On every fully-observable corpus puzzle the belief-space solver must
   collapse to :mod:`spie.search`: the initial belief is a singleton, the contingent plan is
   linear, and its action trace / worst-case depth / uniqueness verdict match
   ``search.canonical_solution`` exactly. This is the backward-compatibility guarantee.

2. **Genuine contingency.** A hidden-then-sense fixture ("which switch") that *cannot* be
   solved by any single linear trace: the player must sense the hidden target and branch on
   what they observe. The solver must return a branching plan of the right shape, and each
   branch must replay to the goal in its own world.
"""

from __future__ import annotations

from dataclasses import replace

from epistemic_fixtures import which_switch as _which_switch
from spie import epistemic, search
from spie.examples_src import BUILDERS
from spie.interpreter import run
from spie.validate import validate

# --- reduction: fully-observable corpus collapses to spie.search ---------------------


def test_initial_belief_is_singleton_when_fully_observable():
    for builder in BUILDERS:
        puzzle = builder()
        if puzzle.initial_belief:  # epistemic puzzles are hidden by design — out of oracle scope
            continue
        assert len(epistemic.build_initial_belief(puzzle)) == 1, puzzle.id


def test_reduction_plan_is_linear_and_matches_search_trace():
    for builder in BUILDERS:
        puzzle = builder()
        if puzzle.initial_belief:
            continue
        canonical = search.canonical_solution(puzzle)
        plan = epistemic.canonical_plan(puzzle)
        assert plan is not None, f"{puzzle.id}: belief solver found no plan"
        assert plan.is_linear(), f"{puzzle.id}: fully-observable plan should be linear"
        assert plan.linear_trace() == canonical.trace, f"{puzzle.id}: trace mismatch"


def test_reduction_depth_matches_search_horizon():
    for builder in BUILDERS:
        puzzle = builder()
        if puzzle.initial_belief:
            continue
        strong = epistemic.solve_strong(puzzle)
        canonical = search.canonical_solution(puzzle)
        assert strong.solvable, f"{puzzle.id}: belief solver reports unsolvable"
        assert strong.depth == canonical.horizon, f"{puzzle.id}: depth {strong.depth}"
        assert strong.plan is not None and strong.plan.depth() == canonical.horizon


def test_reduction_uniqueness_matches_search():
    for builder in BUILDERS:
        puzzle = builder()
        if puzzle.initial_belief:
            continue
        canonical = search.canonical_solution(puzzle)
        epistemic_verdict = epistemic.check_uniqueness(puzzle)
        search_verdict = search.check_uniqueness(puzzle, canonical)
        assert epistemic_verdict.unique == search_verdict.unique, puzzle.id
        assert epistemic_verdict.equivalence == search_verdict.equivalence


# --- genuine contingency: the which-switch fixture -----------------------------------


def test_which_switch_is_wellformed():
    assert validate(_which_switch()) == []


def test_which_switch_initial_belief_has_two_worlds():
    puzzle = _which_switch()
    belief = epistemic.build_initial_belief(puzzle)
    assert len(belief) == 2  # {target=0, target=1}


def test_which_switch_requires_a_branching_plan():
    puzzle = _which_switch()
    strong = epistemic.solve_strong(puzzle)
    assert strong.solvable
    assert strong.depth == 2  # probe, then one flip
    plan = strong.plan
    assert plan is not None
    assert not plan.is_linear(), "a hidden-target puzzle cannot be solved by one linear trace"
    assert plan.linear_trace() is None
    assert plan.action == "probe"
    assert plan.depth() == 2
    # Sensing splits the belief into exactly the two target worlds, each a one-action win.
    assert len(plan.branches) == 2
    leaf_actions = {child.action for _, child in plan.branches}
    assert leaf_actions == {"flip0", "flip1"}
    for _, child in plan.branches:
        assert len(child.branches) == 1
        assert child.branches[0][1].is_leaf


def test_which_switch_plan_is_unique():
    assert epistemic.check_uniqueness(_which_switch()).unique is True


def test_which_switch_each_branch_replays_to_the_goal():
    """The plan is correct per world: in each possible world, following the branch that
    matches the observed target reaches the goal legally through the interpreter."""
    puzzle = _which_switch()
    for target_value, winning_action in ((0, "flip0"), (1, "flip1")):
        world = replace(puzzle, initial={**puzzle.initial, "target": target_value})
        outcome = run(world, ["probe", winning_action])
        assert outcome.reached_goal, f"target={target_value} did not reach goal"


def test_which_switch_guessing_without_sensing_can_fail():
    """The wrong branch loses in the mismatched world — which is *why* sensing is required."""
    puzzle = _which_switch()
    # In the target=1 world, committing to flip0 (the target=0 action) is illegal.
    world = replace(puzzle, initial={**puzzle.initial, "target": 1})
    try:
        run(world, ["flip0"])
    except Exception:  # noqa: BLE001 — any execution failure proves the point
        pass
    else:
        raise AssertionError("flip0 should be illegal in the target=1 world")
