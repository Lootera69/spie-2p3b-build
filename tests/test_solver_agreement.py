"""The anti-drift guard. Two independent checks that the Python evaluator and the Z3
compiler define one semantics:

1. Per-node agreement: a battery of expressions covering every AST node is evaluated both
   ways over several states; the results must match. This covers nodes (Ite, Lt, Or, ...)
   that the corpus may not exercise.
2. Corpus conformance: every example is solved by Z3 and its trace replayed through the
   interpreter; the run must reach the goal and reproduce the solver's exact state-path.
"""

from __future__ import annotations

import z3

from spie import expr as E
from spie.conformance import check_conformance
from spie.evaluate import Context, eval_expr
from spie.examples_src import BUILDERS
from spie.expr import all_of, any_of
from spie.solver import solve
from spie.z3_compile import compile_expr

_CTX = Context(node_index={"A": 0, "B": 1, "C": 2}, edges=frozenset({(0, 1), (1, 2)}))

_EXPRS = [
    E.Const(5),
    E.Var("x"),
    E.Add(E.Var("x"), E.Var("y")),
    E.Sub(E.Var("x"), E.Const(2)),
    E.Eq(E.Var("x"), E.Const(3)),
    E.Lt(E.Var("x"), E.Var("y")),
    E.Le(E.Var("y"), E.Var("x")),
    E.Not(E.Eq(E.Var("x"), E.Var("y"))),
    all_of(E.Lt(E.Var("x"), E.Const(10)), E.Le(E.Const(0), E.Var("x"))),
    any_of(E.Eq(E.Var("x"), E.Const(0)), E.Eq(E.Var("y"), E.Const(0))),
    E.Node("B"),
    E.Edge(E.Var("p"), E.Const(1)),
    E.Edge(E.Node("A"), E.Node("B")),
    E.Ite(E.Lt(E.Var("x"), E.Var("y")), E.Const(100), E.Const(200)),
]

_STATES = [
    {"x": 3, "y": 7, "p": 0},
    {"x": 7, "y": 7, "p": 1},
    {"x": 0, "y": 0, "p": 2},
]


def _z3_value(expr: E.Expr, state: dict[str, int]) -> int:
    """Compile ``expr`` with every variable pinned to a constant, then simplify to a
    numeral — the Z3 backend's answer for this concrete state."""
    var_at = {k: z3.IntVal(v) for k, v in state.items()}
    return z3.simplify(compile_expr(expr, var_at, _CTX)).as_long()


def test_evaluator_and_compiler_agree_per_node():
    for expr in _EXPRS:
        for state in _STATES:
            assert eval_expr(expr, state, _CTX) == _z3_value(expr, state), (expr, state)


def test_solver_traces_conform_across_corpus():
    for builder in BUILDERS:
        puzzle = builder()
        solution = solve(puzzle)
        assert solution.solvable, f"{puzzle.id} should be solvable"
        conf = check_conformance(puzzle, solution)
        assert conf.ok, f"{puzzle.id} conformance failed: {conf.detail}"
        assert conf.reached_goal, f"{puzzle.id} did not reach goal on replay"
