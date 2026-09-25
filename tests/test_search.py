"""Explicit-state search (Phase 2, D1): the second solver must agree with the interpreter
and — across the whole corpus — with the Z3 backend on solvability, minimal length, and
uniqueness. That agreement is the concrete half of decision gate G2.
"""

from __future__ import annotations

from spie import search
from spie.conformance import check_conformance
from spie.examples_src import BUILDERS, move, two_solutions
from spie.ground import path_cost
from spie.interpreter import run
from spie.solver import check_uniqueness as z3_unique
from spie.solver import solve as z3_solve


def test_search_solution_conforms_across_corpus():
    for builder in BUILDERS:
        puzzle = builder()
        sol = search.solve(puzzle)
        assert sol.solvable, f"{puzzle.id}: search found no solution"
        # The search trace replays cleanly through the ground-truth interpreter and its
        # canonical state-path matches — the same trust check Z3 traces must pass.
        conf = check_conformance(puzzle, sol)
        assert conf.ok, f"{puzzle.id}: search trace not conformant — {conf.detail}"
        assert run(puzzle, sol.trace).reached_goal


def test_search_and_z3_agree_on_length_and_uniqueness():
    for builder in BUILDERS:
        puzzle = builder()
        s_search = search.solve(puzzle)
        s_z3 = z3_solve(puzzle)
        assert s_search.solvable == s_z3.solvable, puzzle.id
        assert s_search.horizon == s_z3.horizon, f"{puzzle.id}: length disagreement"

        u_search = search.check_uniqueness(puzzle, s_search)
        u_z3 = z3_unique(puzzle, s_z3)
        assert u_search.unique == u_z3.unique, f"{puzzle.id}: uniqueness disagreement"


def test_min_cost_equals_min_length_under_unit_costs():
    # The whole corpus uses the default unit action cost, so the cheapest solution costs
    # exactly its length, and no cheaper-but-longer path can exist.
    for builder in BUILDERS:
        puzzle = builder()
        by_length = search.solve(puzzle)
        by_cost = search.solve_min_cost(puzzle)
        assert by_cost.solvable
        assert by_cost.cost == by_length.horizon, puzzle.id
        assert by_length.cost == path_cost(puzzle, by_length.trace)


def test_uniqueness_enumeration_positive_and_negative():
    # move() has one shortest path; two_solutions() has two by construction.
    unique = search.check_uniqueness(move(), search.solve(move()))
    assert unique.unique is True and unique.witness is None

    puzzle = two_solutions()
    verdict = search.check_uniqueness(puzzle, search.solve(puzzle))
    assert verdict.unique is False
    assert verdict.witness is not None
    # The witness is a genuinely distinct, valid minimal solution.
    assert run(puzzle, verdict.witness).reached_goal
    assert len(verdict.witness) == search.solve(puzzle).horizon


def test_reach_graph_structure():
    puzzle = move()
    graph = search.explore(puzzle)
    assert graph.initial_live
    assert graph.goals, "solvable puzzle must have reachable goal states"
    # The corridor A->B->C->D has exactly four reachable positions and no traps.
    assert len(graph.states) == 4
    assert graph.traps() == set()
    assert graph.min_goal_dist() == 3
