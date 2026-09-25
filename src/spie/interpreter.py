"""The deterministic interpreter: the puzzle's ground-truth runtime.

Given a puzzle and a trace (a list of ground-action names), it steps the state machine
tick by tick, enforcing preconditions, invariants, and the loss predicate, and reports
whether the goal was reached. This is the authority the roadmap demands: the solver's
proof is only trusted after its solution replays cleanly *here* (see ``conformance``).

Nothing in this module knows about Z3.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import expr as E
from .evaluate import Context, State, apply_effects, eval_bool
from .ground import GroundAction, ground_all
from .ir import Kind, Puzzle


class ExecutionError(Exception):
    """Raised when a trace is illegal (unknown action, precondition/invariant violation,
    loss reached). Carries the tick at which it happened for diagnostics."""

    def __init__(self, message: str, tick: int):
        super().__init__(f"tick {tick}: {message}")
        self.tick = tick


@dataclass
class Outcome:
    """Result of running a trace to completion (or to its failure point)."""

    reached_goal: bool
    final_state: State
    states: list[State]  # states[0] == initial, one entry per tick incl. final


def initial_state(puzzle: Puzzle) -> State:
    """Build the integer initial state, applying LOC default bounds and normalising
    booleans to 0/1. Validates that every declared variable has an initial value."""
    idx = puzzle.node_index()
    state: State = {}
    for v in puzzle.variables:
        if v.key not in puzzle.initial:
            raise ValueError(f"variable {v.key!r} has no initial value")
        raw = puzzle.initial[v.key]
        if v.kind is Kind.BOOL:
            state[v.key] = 1 if raw else 0
        elif v.kind is Kind.LOC:
            # LOC initial values may be given as a location name or an index.
            state[v.key] = idx[raw] if isinstance(raw, str) else int(raw)
        else:  # INT
            state[v.key] = int(raw)
    return state


def _check_invariants(puzzle: Puzzle, state: State, ctx: Context, tick: int) -> None:
    for inv in puzzle.objective.invariants:
        if not eval_bool(inv, state, ctx):
            raise ExecutionError("invariant violated", tick)
    if puzzle.objective.loss is not None and eval_bool(puzzle.objective.loss, state, ctx):
        raise ExecutionError("loss predicate reached", tick)


def run(puzzle: Puzzle, trace: list[str]) -> Outcome:
    """Execute ``trace`` (ground-action names) from the initial state.

    Raises :class:`ExecutionError` on any illegal step. Returns an :class:`Outcome`
    whose ``reached_goal`` reflects the goal predicate evaluated at the final state.
    """
    ctx = Context.from_puzzle(puzzle)
    by_name: dict[str, GroundAction] = {g.name: g for g in ground_all(puzzle)}

    state = initial_state(puzzle)
    _check_invariants(puzzle, state, ctx, 0)
    states = [state]

    for tick, action_name in enumerate(trace):
        ga = by_name.get(action_name)
        if ga is None:
            raise ExecutionError(f"unknown action {action_name!r}", tick)
        if not eval_bool(ga.precondition, state, ctx):
            raise ExecutionError(f"precondition failed for {action_name!r}", tick)
        state = apply_effects(ga.effects, state, ctx)
        _check_invariants(puzzle, state, ctx, tick + 1)
        states.append(state)

    reached = eval_bool(puzzle.objective.goal, state, ctx)
    return Outcome(reached_goal=reached, final_state=state, states=states)


def goal_holds(puzzle: Puzzle, state: State) -> bool:
    """Convenience: is the goal satisfied in ``state``?"""
    ctx = Context.from_puzzle(puzzle)
    return eval_bool(puzzle.objective.goal, state, ctx)


def domain_of(puzzle: Puzzle, v_key: str) -> tuple[int, int]:
    """Resolve the (lo, hi) integer domain of a variable, applying LOC/BOOL defaults.
    Shared by the interpreter's validation and the Z3 encoder's range assertions so the
    two agree on every variable's range."""
    var = puzzle.variables_by_key()[v_key]
    if var.kind is Kind.BOOL:
        return (0, 1)
    if var.kind is Kind.LOC:
        lo = 0 if var.lo is None else var.lo
        hi = (len(puzzle.nodes) - 1) if var.hi is None else var.hi
        return (lo, hi)
    if var.lo is None or var.hi is None:
        raise ValueError(f"INT variable {v_key!r} must declare lo and hi bounds")
    return (var.lo, var.hi)


# Re-exported for callers that build expressions inline.
__all__ = ["run", "Outcome", "ExecutionError", "initial_state", "goal_holds", "domain_of", "E"]
