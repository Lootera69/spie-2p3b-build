"""Uniqueness tests: the check must PASS (unique) on a single-path puzzle and FAIL
(report a second, genuinely distinct solution) on the diamond puzzle built for exactly
that purpose.
"""

from __future__ import annotations

from spie.examples_src import move, two_solutions
from spie.interpreter import run
from spie.solver import check_uniqueness, solve


def test_unique_puzzle_is_unique():
    puzzle = move()
    solution = solve(puzzle)
    verdict = check_uniqueness(puzzle, solution)
    assert verdict.unique is True
    assert verdict.witness is None


def test_two_solution_puzzle_is_not_unique():
    puzzle = two_solutions()
    solution = solve(puzzle)
    verdict = check_uniqueness(puzzle, solution)
    assert verdict.unique is False
    # The witness is a real, distinct solution of the same minimal length.
    assert verdict.witness is not None
    assert verdict.witness != solution.trace
    assert len(verdict.witness) == len(solution.trace) == 2
    # Both the original and the witness actually reach the goal in the interpreter.
    assert run(puzzle, solution.trace).reached_goal
    assert run(puzzle, verdict.witness).reached_goal
