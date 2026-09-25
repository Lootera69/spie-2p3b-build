"""Semantics-preserving compilation of history-dependent observability (Phase 3.9).

The IR declares four observability modes (:class:`spie.ir.Observability`), but the epistemic
solvers, the interpreter, and conformance all key observation off ``VISIBLE`` ∪ an action's
``senses`` — a *memoryless* model. ``DELAYED`` and ``REMEMBERED`` are history-dependent and
cannot be expressed that way directly: a ``DELAYED`` variable is a *standing* observation seen
every tick that merely lags by ``delay`` ticks; a ``REMEMBERED`` variable's sensed value must
*latch* into a fact the player keeps even after the variable moves on.

Rather than re-implement lag/latch across the three observation sites (``epistemic._expand``,
``z3_epistemic._assert_uniformity``, ``conformance._plan_trace_for_world``) — a triple-drift
risk — this module compiles them away, exactly as :mod:`spie.ground` expands the ``Reset``
marker. :func:`desugar` rewrites a puzzle into an equivalent one that uses only ``VISIBLE`` and
``HIDDEN`` variables plus injected per-action framing effects, so **every existing solver, the
interpreter, and conformance run unchanged** and **Method A ≡ Method B holds by construction**
(both solve the identical compiled puzzle).

DELAYED compilation (a shift register)
--------------------------------------
For a ``DELAYED`` variable ``x`` with ``delay = d ≥ 1`` the player observes ``x``'s value from
``d`` ticks ago. We add ``d`` auxiliary variables ``x$lag1 … x$lagd`` (same kind/domain as
``x``):

* ``x$lagd`` — the value ``d`` ticks ago — is **VISIBLE**: the lagged readout.
* ``x$lag1 … x$lag{d-1}`` are **HIDDEN** shift-register buffers carrying *less*-delayed values,
  which must not leak; each is pinned to a singleton belief ``{init_x}`` so ``|B0|`` is
  unchanged.
* the true ``x`` becomes **HIDDEN** (its current value is not directly observable); its authored
  belief support is preserved, or defaults to the singleton ``{init_x}``.

Every authored action gets the shift appended to its effects: ``x$lag1' = x`` and
``x$lagi' = x$lag{i-1}`` for ``i ≥ 2``. Because effects are applied *synchronously* — every
right-hand side is evaluated against the pre-state before any write, identically in the
interpreter (:func:`spie.evaluate.apply_effects`) and in Method B's framing — these implement a
true one-tick shift, so ``x$lagd`` lags ``x`` by exactly ``d`` ticks. All aux variables
initialise to the known constant ``initial_state(puzzle)[x]``, so early ticks show the start
value until the pipeline fills — a clean, documented convention. The shift targets are disjoint
from any authored write, so appending them is order-independent.

REMEMBERED compilation (a latch)
--------------------------------
For a ``REMEMBERED`` variable ``x`` the value is observable only at the tick a sensing action
reads it (it is transient), and the player must carry the fact forward. We add one auxiliary
variable ``x$mem`` — the **VISIBLE**, **persistent** latch — and:

* the true ``x`` becomes **HIDDEN** (its authored belief support is preserved, or defaults to the
  singleton ``{init_x}``); it is the evolving ground truth the latch snapshots.
* every authored read of ``x`` (in preconditions, effects' right-hand sides, the goal,
  invariants, and loss) is redirected to ``x$mem`` — *the player only ever reads what they
  remember*, never transient ``x``. Effect **targets** are left alone: an action that writes true
  ``x`` still writes ``x``.
* an action that ``senses`` ``x`` gets the latch-write ``x$mem' = x`` appended (reading true
  ``x``, the one place it is read), and ``x`` is dropped from that action's ``senses`` — the
  standing VISIBLE latch, not a one-shot sense, is now the observation channel. Every other
  action frames ``x$mem`` automatically, and because the latch is ``persistent`` it also survives
  a ``Reset``: the remembered fact outlives both ``x`` changing and a reset, which is the point.

The latch's domain widens ``x``'s by one: ``x$mem ∈ [lo_x, hi_x + 1]`` initialised to the
out-of-range **sentinel** ``hi_x + 1`` ("not yet observed"). No authored predicate can match the
sentinel, so a decision that depends on the remembered value is unreachable until a sense fires —
making the sense *load-bearing* by construction (blinding it strands the latch at the sentinel and
the puzzle becomes unsolvable), without a separate ``$seen`` flag. ``REMEMBERED`` variables are
expected to be ``INT``/``BOOL`` domained (the latch is an ``INT`` so it can hold the sentinel).

Reduction anchor
----------------
:func:`desugar` is the **identity** on any puzzle with no ``DELAYED`` / ``REMEMBERED`` variable
(and idempotent: its own output has neither, so a second call hits the fast-path), so every
fully-observable and every plain-hidden puzzle certifies byte-identically. That is both the
backward-compatibility guarantee and the standing regression oracle (the reduction + determinism
property tests). The two passes act on disjoint variables and disjoint aux names (``$lag`` vs
``$mem``), so they compose commutatively for a puzzle that declares both modes.
"""

from __future__ import annotations

from dataclasses import replace

from . import expr as E
from .interpreter import domain_of, initial_state
from .ir import Kind, Observability, Puzzle, Variable


def _has_history_obs(puzzle: Puzzle) -> bool:
    """True iff the puzzle declares any ``DELAYED`` / ``REMEMBERED`` variable — the guard for
    the identity fast-path that keeps the reduction anchor intact."""
    return any(
        v.obs in (Observability.DELAYED, Observability.REMEMBERED) for v in puzzle.variables
    )


def desugar(puzzle: Puzzle) -> Puzzle:
    """Compile history-dependent observability away, returning an equivalent puzzle that uses
    only ``VISIBLE`` / ``HIDDEN`` variables. Identity (and idempotent) on any puzzle without a
    ``DELAYED`` / ``REMEMBERED`` variable, so the existing corpus is untouched."""
    if not _has_history_obs(puzzle):
        return puzzle
    # REMEMBERED then DELAYED; each is the identity when its mode is absent, and they touch
    # disjoint variables, so the composition commutes and desugar is idempotent (its output has
    # neither mode, so a repeat call returns via the fast-path above).
    return _desugar_delayed(_desugar_remembered(puzzle))


# --- REMEMBERED: redirect authored reads to the latch, snapshot true x on a sense -----------


def _rename_in_expr(node: E.Expr, rename: dict[str, str]) -> E.Expr:
    """Return ``node`` with every ``Var(k)`` whose key is in ``rename`` replaced by
    ``Var(rename[k])`` — used to point authored reads of a REMEMBERED variable at its latch."""
    match node:
        case E.Var(key):
            return E.Var(rename.get(key, key))
        case E.Not(operand):
            return E.Not(_rename_in_expr(operand, rename))
        case E.And(operands):
            return E.And(tuple(_rename_in_expr(o, rename) for o in operands))
        case E.Or(operands):
            return E.Or(tuple(_rename_in_expr(o, rename) for o in operands))
        case E.Add(a, b):
            return E.Add(_rename_in_expr(a, rename), _rename_in_expr(b, rename))
        case E.Sub(a, b):
            return E.Sub(_rename_in_expr(a, rename), _rename_in_expr(b, rename))
        case E.Eq(a, b):
            return E.Eq(_rename_in_expr(a, rename), _rename_in_expr(b, rename))
        case E.Lt(a, b):
            return E.Lt(_rename_in_expr(a, rename), _rename_in_expr(b, rename))
        case E.Le(a, b):
            return E.Le(_rename_in_expr(a, rename), _rename_in_expr(b, rename))
        case E.Edge(s, d):
            return E.Edge(_rename_in_expr(s, rename), _rename_in_expr(d, rename))
        case E.Ite(c, t, e):
            return E.Ite(
                _rename_in_expr(c, rename),
                _rename_in_expr(t, rename),
                _rename_in_expr(e, rename),
            )
        case _:  # Const / Node / PVal reference no variable
            return node


def _rename_in_effect(eff: object, rename: dict[str, str]) -> object:
    """Rewrite an effect's right-hand side (never its target). ``Reset`` carries no expression."""
    if isinstance(eff, E.Assign):
        return E.Assign(eff.key, _rename_in_expr(eff.value, rename))
    return eff


def _desugar_remembered(puzzle: Puzzle) -> Puzzle:
    """Rewrite every ``REMEMBERED`` variable into a VISIBLE persistent latch plus a sense-time
    snapshot, redirecting all authored reads to the latch (see the module docstring)."""
    remembered = [v for v in puzzle.variables if v.obs is Observability.REMEMBERED]
    if not remembered:
        return puzzle
    init = initial_state(puzzle)
    rem_keys = {v.key for v in remembered}
    rename = {k: f"{k}$mem" for k in rem_keys}  # authored reads see the remembered value

    new_initial = dict(puzzle.initial)
    new_belief = dict(puzzle.initial_belief)

    # 1. The true REMEMBERED variables become HIDDEN; each gains a VISIBLE persistent latch whose
    #    domain widens by one to hold the out-of-range "not yet observed" sentinel.
    transformed: list[Variable] = []
    latch_vars: list[Variable] = []
    for v in puzzle.variables:
        if v.key in rem_keys:
            transformed.append(replace(v, obs=Observability.HIDDEN, delay=0))
            new_belief.setdefault(v.key, (init[v.key],))
            lo, hi = domain_of(puzzle, v.key)
            sentinel = hi + 1
            mem_key = f"{v.key}$mem"
            latch_vars.append(
                Variable(
                    mem_key,
                    Kind.INT,
                    lo=lo,
                    hi=sentinel,
                    obs=Observability.VISIBLE,
                    persistent=True,
                )
            )
            new_initial[mem_key] = sentinel
        else:
            transformed.append(v)

    # 2. Redirect every authored read of a remembered variable to its latch.
    obj = puzzle.objective
    new_obj = replace(
        obj,
        goal=_rename_in_expr(obj.goal, rename),
        invariants=tuple(_rename_in_expr(i, rename) for i in obj.invariants),
        loss=None if obj.loss is None else _rename_in_expr(obj.loss, rename),
    )

    # 3. Rewrite each action's reads, snapshot true x on a sense, and drop x from senses.
    new_actions = []
    for a in puzzle.actions:
        pre = _rename_in_expr(a.precondition, rename)
        effects = tuple(_rename_in_effect(e, rename) for e in a.effects)
        latched = tuple(E.Assign(f"{k}$mem", E.Var(k)) for k in a.senses if k in rem_keys)
        senses = tuple(k for k in a.senses if k not in rem_keys)
        new_actions.append(
            replace(a, precondition=pre, effects=effects + latched, senses=senses)
        )

    return replace(
        puzzle,
        variables=tuple(transformed) + tuple(latch_vars),
        initial=new_initial,
        actions=tuple(new_actions),
        objective=new_obj,
        initial_belief=new_belief,
    )


def _desugar_delayed(puzzle: Puzzle) -> Puzzle:
    """Rewrite every ``DELAYED`` variable into a shift register of ``VISIBLE``/``HIDDEN`` aux
    variables plus per-action shift effects (see the module docstring)."""
    delayed = [v for v in puzzle.variables if v.obs is Observability.DELAYED]
    if not delayed:
        return puzzle
    init = initial_state(puzzle)  # normalised initial ints (post remembered-compilation)
    delayed_keys = {v.key for v in delayed}

    new_initial = dict(puzzle.initial)
    new_belief = dict(puzzle.initial_belief)

    # 1. The true DELAYED variables become HIDDEN (their current value is unobservable).
    transformed = []
    for v in puzzle.variables:
        if v.key in delayed_keys:
            transformed.append(replace(v, obs=Observability.HIDDEN, delay=0))
            new_belief.setdefault(v.key, (init[v.key],))
        else:
            transformed.append(v)

    # 2. Build each variable's shift register and the effects that clock it.
    aux_vars: list[Variable] = []
    shift_assigns: list[E.Assign] = []
    for v in delayed:
        init_val = init[v.key]
        for i in range(1, v.delay + 1):
            aux_key = f"{v.key}$lag{i}"
            is_readout = i == v.delay
            aux_vars.append(
                replace(
                    v,
                    key=aux_key,
                    obs=Observability.VISIBLE if is_readout else Observability.HIDDEN,
                    delay=0,
                    persistent=False,
                )
            )
            new_initial[aux_key] = init_val
            if not is_readout:
                # Intermediate buffers carry less-delayed values and must not leak; pinning
                # each to its known start value keeps |B0| unchanged (singleton support).
                new_belief[aux_key] = (init_val,)
            source = E.Var(v.key) if i == 1 else E.Var(f"{v.key}$lag{i - 1}")
            shift_assigns.append(E.Assign(aux_key, source))

    # 3. Clock the shift register on every authored action (append, like the Reset splice).
    shift_tuple = tuple(shift_assigns)
    new_actions = tuple(
        replace(a, effects=tuple(a.effects) + shift_tuple) for a in puzzle.actions
    )

    return replace(
        puzzle,
        variables=tuple(transformed) + tuple(aux_vars),
        initial=new_initial,
        actions=new_actions,
        initial_belief=new_belief,
    )


__all__ = ["desugar"]

