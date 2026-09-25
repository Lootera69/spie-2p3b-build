"""Shared fixtures for the Phase-3.6 reset primitive (imported, not collected — the name has
no ``test_`` prefix, matching :mod:`epistemic_fixtures`).

``reset_lock`` is the minimal puzzle that exercises *both* halves of reset semantics at once:
a non-persistent counter that must be snapped back to its start, and a persistent flag that
must survive the snap. Solving it is impossible unless a ``Reset`` restores the counter **and**
leaves the learned flag intact — so the fixture is a positive control for the primitive and,
with ``flag`` made non-persistent, a negative control (see ``reset_lock_no_persistence``).
"""

from __future__ import annotations

import dataclasses

from spie.expr import Add, Const, Eq, Lt, Reset, Var, all_of
from spie.ir import Action, Assign, Kind, Objective, Puzzle, Variable


def reset_lock() -> Puzzle:
    """Advance a counter ``a`` (0..2) to 2, ``mark`` sets the persistent ``flag``, then ``reset``
    restores ``a`` to 0 while ``flag`` (persistent) survives. Goal: ``flag == 1 and a == 0``.

    The unique minimal solution is ``advance, advance, mark, reset`` (length 4): ``mark`` needs
    ``a == 2`` so both advances precede it, and only ``reset`` can return ``a`` to 0, so it must
    come last. Removing any action makes the puzzle unsolvable — reset included, which is what
    makes it load-bearing rather than decorative."""
    a = Variable("a", Kind.INT, lo=0, hi=2)  # transient — snapped back by reset
    flag = Variable("flag", Kind.BOOL, persistent=True)  # learned — survives reset
    advance = Action(
        name="advance",
        precondition=Lt(Var("a"), Const(2)),
        effects=(Assign("a", Add(Var("a"), Const(1))),),
    )
    mark = Action(
        name="mark",
        precondition=Eq(Var("a"), Const(2)),
        effects=(Assign("flag", Const(1)),),
    )
    reset = Action(name="reset", precondition=Const(True), effects=(Reset(),))
    return Puzzle(
        id="fx_reset_lock",
        title="Reset Lock",
        nodes=("Room",),
        edges=(),
        variables=(a, flag),
        initial={"a": 0, "flag": 0},
        actions=(advance, mark, reset),
        objective=Objective(
            goal=all_of(Eq(Var("flag"), Const(1)), Eq(Var("a"), Const(0))),
            max_horizon=6,
            requires_unique=True,
        ),
        seed=360,
    )


def reset_lock_no_persistence() -> Puzzle:
    """``reset_lock`` with ``flag`` made non-persistent: ``reset`` now also clears the flag, so
    the goal (``flag == 1 and a == 0``) is unreachable — the negative control proving that the
    ``persistent`` flag is what carries the learned fact across the reset."""
    base = reset_lock()
    variables = tuple(
        dataclasses.replace(v, persistent=False) if v.key == "flag" else v
        for v in base.variables
    )
    return dataclasses.replace(base, id="fx_reset_lock_no_persistence", variables=variables)
