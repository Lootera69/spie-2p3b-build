"""Action grounding — expand parameterised action templates into concrete actions.

An :class:`~spie.ir.Action` may carry finite :class:`~spie.ir.Param`s. Grounding takes
the cross product of all parameter values and, for each combination, substitutes every
``PVal(name)`` in the precondition and effects with a concrete literal:

* a NODE param value (a location name) becomes ``Node(name)``;
* an INT param value becomes ``Const(int)``.

The result is a flat list of :class:`GroundAction`, each with a unique display name like
``move[src=A,dst=B]``. Both backends operate exclusively on ground actions, so ``PVal``
never reaches the evaluator or the Z3 compiler.

Grounding is purely structural (no world state), which keeps it identical for the
interpreter and the solver — a prerequisite for their agreement.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from . import expr as E
from .ir import Action, Assign, Puzzle, Reset


@dataclass(frozen=True)
class GroundAction:
    """A fully-instantiated action: no free parameters remain.

    ``senses`` carries the template's :attr:`~spie.ir.Action.senses` through grounding (empty
    for every slice-1/2 action). It is a structural property of the action, like ``cost``, and
    is what the epistemic belief-space solver reads to know which variables firing this action
    reveals. It never reaches the interpreter or the Z3 compiler, so fully-observable behavior
    is untouched.

    ``effects`` is always a tuple of plain :class:`~spie.ir.Assign`: any
    :class:`~spie.ir.Reset` marker on the template has already been expanded during grounding,
    so both backends see only concrete assignments."""

    name: str
    precondition: E.Expr
    effects: tuple[Assign, ...]
    cost: int
    senses: tuple[str, ...] = ()


def _subst(node: E.Expr, binding: dict[str, int | str]) -> E.Expr:
    """Replace every ``PVal`` in ``node`` per ``binding``. Structural recursion mirrors
    the expression AST exactly."""
    match node:
        case E.PVal(name):
            if name not in binding:
                raise KeyError(f"no binding for parameter {name!r}")
            value = binding[name]
            return E.Node(value) if isinstance(value, str) else E.Const(value)
        case E.Const() | E.Var() | E.Node():
            return node
        case E.Not(operand):
            return E.Not(_subst(operand, binding))
        case E.And(operands):
            return E.And(tuple(_subst(o, binding) for o in operands))
        case E.Or(operands):
            return E.Or(tuple(_subst(o, binding) for o in operands))
        case E.Add(left, right):
            return E.Add(_subst(left, binding), _subst(right, binding))
        case E.Sub(left, right):
            return E.Sub(_subst(left, binding), _subst(right, binding))
        case E.Eq(left, right):
            return E.Eq(_subst(left, binding), _subst(right, binding))
        case E.Lt(left, right):
            return E.Lt(_subst(left, binding), _subst(right, binding))
        case E.Le(left, right):
            return E.Le(_subst(left, binding), _subst(right, binding))
        case E.Edge(src, dst):
            return E.Edge(_subst(src, binding), _subst(dst, binding))
        case E.Ite(cond, then, otherwise):
            return E.Ite(
                _subst(cond, binding), _subst(then, binding), _subst(otherwise, binding)
            )
        case _:
            raise TypeError(f"unhandled node in substitution: {type(node).__name__}")


def _subst_key(key: str, binding: dict[str, int | str]) -> str:
    """Substitute ``{param}`` placeholders inside an effect's target variable key,
    so ``carrying_{obj}`` with ``obj=key`` becomes ``carrying_key``."""
    out = key
    for name, value in binding.items():
        out = out.replace("{" + name + "}", str(value))
    return out


def _expand_effects(
    effects: tuple, binding: dict[str, int | str], reset_assigns: tuple[Assign, ...]
) -> tuple[Assign, ...]:
    """Ground one action's effect list: substitute parameters into every :class:`Assign` and
    splice each :class:`Reset` marker, in place, into the pre-computed non-persistent reset
    assignments. The marker expands positionally, so last-write-wins over the resulting flat
    tuple matches the template author's ordering intent."""
    out: list[Assign] = []
    for eff in effects:
        if isinstance(eff, Reset):
            out.extend(reset_assigns)
        else:
            out.append(Assign(_subst_key(eff.key, binding), _subst(eff.value, binding)))
    return tuple(out)


def ground_action(
    action: Action, reset_assigns: tuple[Assign, ...] = ()
) -> list[GroundAction]:
    """Expand one template into all its ground instances (one if it has no params).

    ``reset_assigns`` are the concrete assignments a :class:`~spie.ir.Reset` marker expands to
    (one per non-persistent variable, restoring its initial value); :func:`ground_all` computes
    them from the puzzle. An action with no ``Reset`` marker ignores them entirely."""
    if not action.params:
        return [
            GroundAction(
                action.name,
                action.precondition,
                _expand_effects(action.effects, {}, reset_assigns),
                action.cost,
                tuple(action.senses),
            )
        ]
    names = [p.name for p in action.params]
    value_lists = [p.values for p in action.params]
    out: list[GroundAction] = []
    for combo in itertools.product(*value_lists):
        binding = dict(zip(names, combo, strict=True))
        label = ",".join(f"{n}={binding[n]}" for n in names)
        pre = _subst(action.precondition, binding)
        effects = _expand_effects(action.effects, binding, reset_assigns)
        senses = tuple(_subst_key(s, binding) for s in action.senses)
        out.append(GroundAction(f"{action.name}[{label}]", pre, effects, action.cost, senses))
    return out


def _reset_assigns(puzzle: Puzzle) -> tuple[Assign, ...]:
    """The assignments a :class:`~spie.ir.Reset` marker expands to for this puzzle: every
    **non-persistent** variable restored to its declared initial value.

    Initial values are taken from the interpreter's normalised integer initial state (BOOL →
    0/1, LOC name → node index), so a reset assigns exactly the value the puzzle starts from —
    reusing the single source of that normalisation rather than re-deriving it here."""
    from .interpreter import initial_state  # local import avoids a ground<->interpreter cycle

    init = initial_state(puzzle)
    return tuple(
        Assign(v.key, E.Const(init[v.key])) for v in puzzle.variables if not v.persistent
    )


def ground_all(puzzle: Puzzle) -> list[GroundAction]:
    """All ground actions for a puzzle, in a deterministic order (template order, then
    cross-product order). Determinism matters: the solver's action indices must be
    stable across runs for reproducible certificates.

    The non-persistent reset assignments are computed only when some action actually carries a
    :class:`~spie.ir.Reset` marker, so a puzzle without reset semantics grounds exactly as
    before (no dependency on the initial state, no behavioural change)."""
    has_reset = any(isinstance(e, Reset) for a in puzzle.actions for e in a.effects)
    reset_assigns = _reset_assigns(puzzle) if has_reset else ()
    out: list[GroundAction] = []
    for action in puzzle.actions:
        out.extend(ground_action(action, reset_assigns))
    return out


def path_cost(puzzle: Puzzle, trace: list[str] | tuple[str, ...]) -> int:
    """Total cost of a trace: the sum of the (ground) action costs along it.

    Costs are a purely structural property of the ground actions, so this is shared by both
    solver backends and by the shortcut gate — none of them may disagree on what a path
    costs. An empty trace costs 0."""
    by_name = {g.name: g.cost for g in ground_all(puzzle)}
    return sum(by_name[name] for name in trace)
