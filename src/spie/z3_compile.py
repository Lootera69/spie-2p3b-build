"""The Z3 backend: the second half of the single-source-of-semantics design.

``compile_expr`` mirrors ``evaluate.eval_expr`` node-for-node, but emits a Z3 Int term
instead of computing a Python int. Like the evaluator, *every* expression compiles to an
Int (booleans as 0/1), so the two backends agree by construction; the only duplication is
the trivial per-node mapping, and ``tests/test_solver_agreement.py`` guards against drift.

``build_unrolling`` performs bounded model checking: it unrolls the transition relation to
a fixed horizon H, creating a fresh Z3 Int constant ``v@t`` for every variable ``v`` and
tick ``t in 0..H``. ``solver.py`` drives this: it searches H upward for the minimal feasible
horizon, then reuses the same unrolling shape for the uniqueness check.

Nothing outside this module (and ``solver.py``) imports z3.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3

from . import expr as E
from .evaluate import Context
from .ground import GroundAction, ground_all
from .interpreter import domain_of, initial_state
from .ir import Puzzle


def _b2i(cond: z3.BoolRef) -> z3.ArithRef:
    """Lift a Z3 Bool to the 0/1 Int the evaluator uses, so booleans and integers share
    one sort exactly as they do in ``eval_expr``."""
    return z3.If(cond, z3.IntVal(1), z3.IntVal(0))


def compile_expr(node: E.Expr, var_at: dict[str, z3.ArithRef], ctx: Context) -> z3.ArithRef:
    """Compile ``node`` to a Z3 Int term over the tick whose variables are ``var_at``.
    Structurally identical to :func:`spie.evaluate.eval_expr`."""
    match node:
        case E.Const(value):
            return z3.IntVal(int(value))
        case E.Var(key):
            return var_at[key]
        case E.Node(name):
            if name not in ctx.node_index:
                raise KeyError(f"unknown location: {name!r}")
            return z3.IntVal(ctx.node_index[name])
        case E.Edge(src, dst):
            s = compile_expr(src, var_at, ctx)
            d = compile_expr(dst, var_at, ctx)
            if not ctx.edges:
                return z3.IntVal(0)
            return _b2i(z3.Or([z3.And(s == a, d == b) for a, b in ctx.edges]))
        case E.Not(operand):
            return _b2i(compile_expr(operand, var_at, ctx) == 0)
        case E.And(operands):
            return _b2i(z3.And([compile_expr(o, var_at, ctx) != 0 for o in operands]))
        case E.Or(operands):
            return _b2i(z3.Or([compile_expr(o, var_at, ctx) != 0 for o in operands]))
        case E.Add(left, right):
            return compile_expr(left, var_at, ctx) + compile_expr(right, var_at, ctx)
        case E.Sub(left, right):
            return compile_expr(left, var_at, ctx) - compile_expr(right, var_at, ctx)
        case E.Eq(left, right):
            return _b2i(compile_expr(left, var_at, ctx) == compile_expr(right, var_at, ctx))
        case E.Lt(left, right):
            return _b2i(compile_expr(left, var_at, ctx) < compile_expr(right, var_at, ctx))
        case E.Le(left, right):
            return _b2i(compile_expr(left, var_at, ctx) <= compile_expr(right, var_at, ctx))
        case E.Ite(cond, then, otherwise):
            return z3.If(
                compile_expr(cond, var_at, ctx) != 0,
                compile_expr(then, var_at, ctx),
                compile_expr(otherwise, var_at, ctx),
            )
        case E.PVal(name):
            raise ValueError(f"ungrounded action parameter {name!r} reached the compiler")
        case _:
            raise TypeError(f"unhandled expression node: {type(node).__name__}")


def compile_bool(node: E.Expr, var_at: dict[str, z3.ArithRef], ctx: Context) -> z3.BoolRef:
    """Boolean view of ``node`` (non-zero is true), mirroring ``evaluate.eval_bool``."""
    return compile_expr(node, var_at, ctx) != 0


@dataclass
class Unrolling:
    """A puzzle's transition relation unrolled to ``horizon`` ticks, with all BMC
    constraints already asserted on ``solver`` *except* the goal (the caller adds that, so
    the same object serves both the reachability solve and the uniqueness re-solve)."""

    puzzle: Puzzle
    horizon: int
    ctx: Context
    ground: list[GroundAction]
    v: dict[tuple[str, int], z3.ArithRef]
    fire: dict[tuple[int, int], z3.BoolRef]
    solver: z3.Solver

    def var_at(self, t: int) -> dict[str, z3.ArithRef]:
        return {var.key: self.v[(var.key, t)] for var in self.puzzle.variables}

    def goal_term(self, t: int) -> z3.BoolRef:
        return compile_bool(self.puzzle.objective.goal, self.var_at(t), self.ctx)

    def read_trace(self, model: z3.ModelRef) -> list[str]:
        """The ordered ground-action names chosen at each tick 0..H-1."""
        trace: list[str] = []
        for t in range(self.horizon):
            for i, ga in enumerate(self.ground):
                if z3.is_true(model.eval(self.fire[(i, t)], model_completion=True)):
                    trace.append(ga.name)
                    break
        return trace

    def read_state_path(self, model: z3.ModelRef) -> tuple[tuple[int, ...], ...]:
        """The canonical state-path s0..sH: one integer tuple per tick (variables in
        declared order). This is the equivalence object the uniqueness check blocks."""
        keys = [var.key for var in self.puzzle.variables]
        return tuple(
            tuple(model.eval(self.v[(k, t)], model_completion=True).as_long() for k in keys)
            for t in range(self.horizon + 1)
        )

    def block_state_path(self, path: tuple[tuple[int, ...], ...]) -> None:
        """Assert the run does not reproduce ``path`` exactly (negate the conjunction of
        every variable equalling its recorded value at every tick)."""
        keys = [var.key for var in self.puzzle.variables]
        eqs = [
            self.v[(k, t)] == path[t][j]
            for t in range(self.horizon + 1)
            for j, k in enumerate(keys)
        ]
        self.solver.add(z3.Not(z3.And(eqs)))


def build_unrolling(puzzle: Puzzle, horizon: int) -> Unrolling:
    """Assert every BMC constraint for ``puzzle`` at ``horizon`` except the goal: variable
    domains, the initial state, per-tick invariants/loss, and the transition relation with
    an exactly-one-action-per-tick selector. The caller asserts the goal and solves."""
    ctx = Context.from_puzzle(puzzle)
    ground = ground_all(puzzle)
    solver = z3.Solver()

    # One Int constant per (variable, tick), with its declared domain bounds on every tick.
    v: dict[tuple[str, int], z3.ArithRef] = {}
    for var in puzzle.variables:
        lo, hi = domain_of(puzzle, var.key)
        for t in range(horizon + 1):
            c = z3.Int(f"{var.key}@{t}")
            v[(var.key, t)] = c
            solver.add(c >= lo, c <= hi)

    un = Unrolling(puzzle, horizon, ctx, ground, v, {}, solver)

    # Initial state pinned at tick 0.
    init = initial_state(puzzle)
    for var in puzzle.variables:
        solver.add(v[(var.key, 0)] == init[var.key])

    # Invariants hold, and the loss predicate is avoided, at every tick.
    for t in range(horizon + 1):
        va = un.var_at(t)
        for inv in puzzle.objective.invariants:
            solver.add(compile_bool(inv, va, ctx))
        if puzzle.objective.loss is not None:
            solver.add(z3.Not(compile_bool(puzzle.objective.loss, va, ctx)))

    # Transition relation for each step t -> t+1.
    for t in range(horizon):
        cur = un.var_at(t)
        selectors: list[z3.BoolRef] = []
        for i, ga in enumerate(ground):
            sel = z3.Bool(f"fire_{i}@{t}")
            un.fire[(i, t)] = sel
            selectors.append(sel)
            written = {e.key for e in ga.effects}
            cons = [compile_bool(ga.precondition, cur, ctx)]
            cons += [v[(e.key, t + 1)] == compile_expr(e.value, cur, ctx) for e in ga.effects]
            cons += [
                v[(var.key, t + 1)] == v[(var.key, t)]
                for var in puzzle.variables
                if var.key not in written
            ]
            solver.add(z3.Implies(sel, z3.And(cons)))
        # Exactly one ground action fires at each tick (no no-ops: the horizon search keeps
        # solutions minimal, so a wait step is never needed to reach the goal).
        solver.add(z3.PbEq([(s, 1) for s in selectors], 1))

    return un


__all__ = ["compile_expr", "compile_bool", "Unrolling", "build_unrolling"]
