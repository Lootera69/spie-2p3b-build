"""Drive the Z3 backend: find a minimal-length solution, then decide uniqueness.

The search is deliberately simple and reproducible: try horizon H = 0, 1, 2, ... up to the
puzzle's ``max_horizon``; the first H at which the unrolling is ``sat`` yields the
minimal-length solution. Uniqueness is then decided at that same H by blocking the found
solution's canonical state-path and re-solving — ``unsat`` means no genuinely different
solution of minimal length exists.

This is the only module besides ``z3_compile`` that touches z3.
"""

from __future__ import annotations

import z3

from .ground import path_cost
from .ir import Puzzle
from .results import EQUIVALENCE, Solution, Uniqueness
from .z3_compile import build_unrolling

SOLVER_NAME = "z3-bmc"


def solver_version() -> str:
    return z3.get_version_string()


def solve(puzzle: Puzzle) -> Solution:
    """Search H upward for the minimal horizon that reaches the goal."""
    for horizon in range(puzzle.objective.max_horizon + 1):
        un = build_unrolling(puzzle, horizon)
        un.solver.add(un.goal_term(horizon))
        if un.solver.check() == z3.sat:
            model = un.solver.model()
            trace = un.read_trace(model)
            return Solution(
                solvable=True,
                horizon=horizon,
                trace=trace,
                state_path=un.read_state_path(model),
                cost=path_cost(puzzle, trace),
            )
    return Solution(solvable=False, horizon=puzzle.objective.max_horizon)


def check_uniqueness(puzzle: Puzzle, solution: Solution) -> Uniqueness:
    """Decide whether ``solution`` is the only minimal-length solution up to state-path
    equivalence. Blocks the found path and re-solves at the same horizon."""
    if not solution.solvable:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)
    un = build_unrolling(puzzle, solution.horizon)
    un.solver.add(un.goal_term(solution.horizon))
    un.block_state_path(solution.state_path)
    if un.solver.check() == z3.sat:
        return Uniqueness(
            unique=False, equivalence=EQUIVALENCE, witness=un.read_trace(un.solver.model())
        )
    return Uniqueness(unique=True, equivalence=EQUIVALENCE)


__all__ = [
    "SOLVER_NAME",
    "solver_version",
    "Solution",
    "Uniqueness",
    "EQUIVALENCE",
    "solve",
    "check_uniqueness",
]
