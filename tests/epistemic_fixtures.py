"""Shared epistemic puzzle fixtures for the Phase-3 solver tests.

These are hand puzzles that *cannot* be solved by any single linear trace: the player must
sense a hidden fact and branch on what they observe. Both the concrete solver
(:mod:`spie.epistemic`, Method A) and the symbolic one (:mod:`spie.z3_epistemic`, Method B)
are exercised against them, and must agree. Kept out of any ``test_*`` module (and named
without the ``test_`` prefix) so pytest imports but does not collect it.
"""

from __future__ import annotations

from spie.expr import Const, Eq, Var, all_of
from spie.ir import Action, Assign, Kind, Objective, Observability, Puzzle, Variable


def which_switch() -> Puzzle:
    """A hidden binary ``target`` decides which switch wins.

    ``target`` is HIDDEN with support {0, 1}; ``probe`` senses it without changing the world;
    ``flip0`` / ``flip1`` each win but are legal only in the matching world. No linear plan
    works — ``flip0`` is illegal in the ``target=1`` world and vice versa — so the only
    solution is to probe, then branch on the observed value. Optimal worst-case depth 2,
    and the plan is unique.
    """
    variables = (
        Variable("target", Kind.BOOL, obs=Observability.HIDDEN),
        Variable("done", Kind.BOOL),
    )
    probe = Action(
        name="probe",
        precondition=Eq(Var("done"), Const(0)),
        effects=(),  # pure sensing: reveals target, changes no state
        senses=("target",),
    )
    flip0 = Action(
        name="flip0",
        precondition=all_of(Eq(Var("target"), Const(0)), Eq(Var("done"), Const(0))),
        effects=(Assign("done", Const(1)),),
    )
    flip1 = Action(
        name="flip1",
        precondition=all_of(Eq(Var("target"), Const(1)), Eq(Var("done"), Const(0))),
        effects=(Assign("done", Const(1)),),
    )
    return Puzzle(
        id="ep_which_switch",
        title="Which Switch",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"target": 0, "done": 0},
        actions=(probe, flip0, flip1),
        objective=Objective(goal=Eq(Var("done"), Const(1)), max_horizon=5),
        seed=301,
        initial_belief={"target": (0, 1)},
        notes="Sense the hidden target, then flip the matching switch; needs a branching plan.",
    )


def which_switch_three() -> Puzzle:
    """The three-world generalization: a hidden ``target`` ∈ {0, 1, 2} selects the winning
    switch. Stresses the multi-world encoding beyond a single pair — three trajectories, three
    pairwise uniformity constraints — while staying a unique depth-2 branching plan (probe,
    then the one matching flip). A wrong guess is illegal in two of the three worlds.
    """
    variables = (
        Variable("target", Kind.INT, lo=0, hi=2, obs=Observability.HIDDEN),
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
        for k in (0, 1, 2)
    )
    return Puzzle(
        id="ep_which_switch_three",
        title="Which Switch (of three)",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"target": 0, "done": 0},
        actions=(probe, *flips),
        objective=Objective(goal=Eq(Var("done"), Const(1)), max_horizon=5),
        seed=302,
        initial_belief={"target": (0, 1, 2)},
        notes="Sense the hidden 3-valued target, then flip the matching switch.",
    )
