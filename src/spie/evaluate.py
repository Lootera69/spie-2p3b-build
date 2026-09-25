"""The Python evaluator: one half of the single-source-of-semantics design.

``eval_expr`` computes the value of an expression against a concrete state (a mapping
of variable key -> python value). ``apply_effects`` computes the next state produced by
a ground action, framing every variable the action does not write.

The Z3 compiler in ``z3_compile`` mirrors this node-for-node. Any semantic decision
made here (integer arithmetic, truthiness, adjacency) must be made identically there;
``tests/test_solver_agreement.py`` is the guard that they never drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import expr as E


@dataclass(frozen=True)
class Context:
    """Static, tick-independent world facts needed to evaluate ``Node`` and ``Edge``."""

    node_index: dict[str, int]
    edges: frozenset[tuple[int, int]]

    @classmethod
    def from_puzzle(cls, puzzle) -> Context:  # noqa: ANN001 (avoid import cycle with ir)
        idx = {name: i for i, name in enumerate(puzzle.nodes)}
        edges = frozenset((idx[a], idx[b]) for a, b in puzzle.edges)
        return cls(node_index=idx, edges=edges)


State = dict[str, int]  # booleans are stored as 0/1 for a uniform integer state space


def _as_int(value: bool | int) -> int:
    """Normalise a python bool/int to the engine's integer state representation."""
    return int(value)


def eval_expr(node: E.Expr, state: State, ctx: Context) -> int:
    """Evaluate ``node`` to an integer (booleans are 0/1). Raises on unbound params."""
    match node:
        case E.Const(value):
            return _as_int(value)
        case E.Var(key):
            if key not in state:
                raise KeyError(f"unbound state variable: {key!r}")
            return state[key]
        case E.Node(name):
            if name not in ctx.node_index:
                raise KeyError(f"unknown location: {name!r}")
            return ctx.node_index[name]
        case E.Edge(src, dst):
            s = eval_expr(src, state, ctx)
            d = eval_expr(dst, state, ctx)
            return 1 if (s, d) in ctx.edges else 0
        case E.Not(operand):
            return 1 if eval_expr(operand, state, ctx) == 0 else 0
        case E.And(operands):
            return 1 if all(eval_expr(o, state, ctx) != 0 for o in operands) else 0
        case E.Or(operands):
            return 1 if any(eval_expr(o, state, ctx) != 0 for o in operands) else 0
        case E.Add(left, right):
            return eval_expr(left, state, ctx) + eval_expr(right, state, ctx)
        case E.Sub(left, right):
            return eval_expr(left, state, ctx) - eval_expr(right, state, ctx)
        case E.Eq(left, right):
            return 1 if eval_expr(left, state, ctx) == eval_expr(right, state, ctx) else 0
        case E.Lt(left, right):
            return 1 if eval_expr(left, state, ctx) < eval_expr(right, state, ctx) else 0
        case E.Le(left, right):
            return 1 if eval_expr(left, state, ctx) <= eval_expr(right, state, ctx) else 0
        case E.Ite(cond, then, otherwise):
            return (
                eval_expr(then, state, ctx)
                if eval_expr(cond, state, ctx) != 0
                else eval_expr(otherwise, state, ctx)
            )
        case E.PVal(name):
            raise ValueError(f"ungrounded action parameter {name!r} reached the evaluator")
        case _:
            raise TypeError(f"unhandled expression node: {type(node).__name__}")


def eval_bool(node: E.Expr, state: State, ctx: Context) -> bool:
    return eval_expr(node, state, ctx) != 0


def apply_effects(effects, state: State, ctx: Context) -> State:  # noqa: ANN001
    """Return the next state: assignments computed against the *current* state, every
    unwritten variable framed (carried forward unchanged).

    All right-hand sides are evaluated against ``state`` before any write, so an action
    whose effects reference each other sees a consistent pre-transition snapshot.
    """
    updates: State = {}
    for eff in effects:
        updates[eff.key] = eval_expr(eff.value, state, ctx)
    nxt = dict(state)
    nxt.update(updates)
    return nxt
