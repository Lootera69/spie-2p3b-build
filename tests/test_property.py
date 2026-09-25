"""Property-based cross-validation (Phase 2, D7): on randomly generated small puzzles the
three independent semantics — the Z3 proof backend, the explicit-state search, and the
interpreter (via conformance replay) — must never disagree.

This is the strongest form of gate G2: instead of trusting agreement on the hand-picked
corpus, ``hypothesis`` searches for a puzzle on which symbolic and concrete solving diverge.
Any counterexample would be a genuine semantic bug in one backend, minimized automatically.

Generator soundness note: the explicit-state search decides solvability over the *whole*
reachable graph and ignores ``max_horizon``, while Z3 is a bounded model checker that respects
it. So the generator sets ``max_horizon`` to ``n * 2**ns`` — an upper bound on the number of
reachable states, hence on any shortest solution length — so a bounded/unbounded difference
can never manufacture a spurious disagreement. A mismatch then means a real defect.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from spie import search, solver
from spie.conformance import check_conformance
from spie.expr import Const, Edge, Eq, Node, PVal, Var, all_of
from spie.ir import Action, Assign, Kind, Objective, Param, Puzzle, Variable


@st.composite
def small_puzzles(draw):
    """A random reachability puzzle: move ``pos`` along a random digraph, plus 0-2 one-way
    boolean switches, with a goal over the destination node and a random subset of switches."""
    n = draw(st.integers(min_value=2, max_value=4))
    nodes = tuple(f"N{i}" for i in range(n))
    possible = [(a, b) for a in nodes for b in nodes if a != b]
    edges = tuple(
        draw(st.lists(st.sampled_from(possible), min_size=1, max_size=n + 1, unique=True))
    )

    ns = draw(st.integers(min_value=0, max_value=2))
    switches = tuple(f"s{i}" for i in range(ns))
    variables = (Variable("pos", Kind.LOC),) + tuple(
        Variable(s, Kind.BOOL) for s in switches
    )

    move = Action(
        name="move",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("pos", PVal("dst")),),
    )
    actions = [move]
    for s in switches:
        actions.append(
            Action(
                name=f"toggle_{s}",
                precondition=Eq(Var(s), Const(0)),
                effects=(Assign(s, Const(1)),),
            )
        )

    goal_terms = [Eq(Var("pos"), Node(nodes[-1]))]
    for s in switches:
        if draw(st.booleans()):
            goal_terms.append(Eq(Var(s), Const(1)))
    goal = all_of(*goal_terms)

    initial = {"pos": nodes[0]}
    for s in switches:
        initial[s] = 0

    horizon = n * (2 ** ns)  # >= reachable-state count >= any minimal solution length
    return Puzzle(
        id="prop",
        title="prop",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial=initial,
        actions=tuple(actions),
        objective=Objective(goal=goal, max_horizon=horizon, requires_unique=False),
        seed=0,
    )


@settings(max_examples=100, deadline=None)
@given(puzzle=small_puzzles())
def test_z3_and_search_agree(puzzle):
    zs = solver.solve(puzzle)
    ss = search.solve(puzzle)
    assert zs.solvable == ss.solvable, f"solvability disagreement on {puzzle}"
    if zs.solvable:
        assert zs.horizon == ss.horizon, f"horizon disagreement on {puzzle}"
        z3_unique = solver.check_uniqueness(puzzle, zs).unique
        se_unique = search.check_uniqueness(puzzle, ss).unique
        assert z3_unique == se_unique, f"uniqueness disagreement on {puzzle}"
        # The interpreter is the third semantics: both traces must replay cleanly.
        assert check_conformance(puzzle, zs).ok, f"Z3 trace non-conformant on {puzzle}"
        assert check_conformance(puzzle, ss).ok, f"search trace non-conformant on {puzzle}"
