"""Typed expression and effect AST — the single definition of puzzle semantics.

This module defines *only the data* of expressions. It contains no evaluation logic.
Two backends walk this same tree:

* ``evaluate.eval_expr``   — the deterministic Python interpreter (ground-truth runtime)
* ``z3_compile.compile_expr`` — the Z3 term compiler (the proof backend)

Because both backends traverse one structural definition, the semantics of a puzzle
are defined exactly once. If a new node type is added here, both backends must handle
it, and ``tests/test_solver_agreement.py`` proves they never diverge on the corpus.

Design notes
------------
* Expressions are frozen dataclasses so they are hashable, comparable, and safe to
  reuse across timesteps in the Z3 encoding.
* The value domain is deliberately small: booleans and bounded integers. Location
  variables are represented as bounded integers (an index into ``World.nodes``), so
  ``Loc`` needs no dedicated expression node.
* ``Assign`` is an *effect*, not an expression: it names a state variable and the
  expression whose value it takes at the next tick. Any variable not named by an
  action's effects is *framed* (held constant) — see the interpreter and Z3 encoder.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Expression nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Expr:
    """Base class for all expression nodes. Never instantiated directly."""


@dataclass(frozen=True)
class Const(Expr):
    """A literal boolean or integer constant."""

    value: bool | int


@dataclass(frozen=True)
class Var(Expr):
    """A read of a state variable by key. Its value is the variable's value at the
    current tick."""

    key: str


@dataclass(frozen=True)
class Node(Expr):
    """A literal reference to a location by name. Resolves to that location's integer
    index in ``World.nodes``. Lets puzzles name places instead of hardcoding indices."""

    name: str


@dataclass(frozen=True)
class Edge(Expr):
    """Static adjacency test: True iff a directed edge ``src -> dst`` exists in the
    world. ``src``/``dst`` evaluate to location indices. Used as a movement guard."""

    src: Expr
    dst: Expr


@dataclass(frozen=True)
class PVal(Expr):
    """An action-parameter placeholder, valid only *inside an action template*. Action
    grounding replaces every ``PVal(name)`` with a concrete ``Const`` or ``Node`` before
    the interpreter or Z3 compiler ever sees it. Reaching a backend is a bug."""

    name: str


@dataclass(frozen=True)
class Not(Expr):
    operand: Expr


@dataclass(frozen=True)
class And(Expr):
    operands: tuple[Expr, ...]


@dataclass(frozen=True)
class Or(Expr):
    operands: tuple[Expr, ...]


@dataclass(frozen=True)
class Add(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Sub(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Eq(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Lt(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Le(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Ite(Expr):
    """If-then-else. ``cond`` is boolean; ``then``/``otherwise`` share a type."""

    cond: Expr
    then: Expr
    otherwise: Expr


# ---------------------------------------------------------------------------
# Effect node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assign:
    """An effect: state variable ``key`` becomes ``value`` at the next tick."""

    key: str
    value: Expr


@dataclass(frozen=True)
class Reset:
    """A first-class *reset* effect marker (Phase 3.6): snap every **non-persistent** variable
    back to its declared initial value, leaving ``persistent`` variables untouched.

    ``Reset`` is a template-level primitive that never reaches a backend. Grounding
    (:func:`spie.ground.ground_all`) expands each marker in place into the concrete
    ``Assign(key, Const(initial_value))`` effects for the puzzle's non-persistent variables, so
    the interpreter and the Z3 compiler only ever see plain :class:`Assign`s — reset therefore
    inherits the single source of semantics exactly, with zero drift risk, while remaining a
    real, inspectable, serializable DSL element. Because a ground action's effects apply with
    last-write-wins over a single pre-transition snapshot, a ``Reset`` composes with explicit
    assignments in the same action by position (an assignment after the marker overrides the
    reset value for that variable; one before it is overridden)."""



# ---------------------------------------------------------------------------
# Ergonomic constructors (keep hand-encoded puzzles readable)
# ---------------------------------------------------------------------------


def lit(value: bool | int) -> Const:
    return Const(value)


def var(key: str) -> Var:
    return Var(key)


def all_of(*operands: Expr) -> Expr:
    """Conjunction with identity handling: no operands -> True, one -> itself."""
    if not operands:
        return Const(True)
    if len(operands) == 1:
        return operands[0]
    return And(tuple(operands))


def any_of(*operands: Expr) -> Expr:
    if not operands:
        return Const(False)
    if len(operands) == 1:
        return operands[0]
    return Or(tuple(operands))
