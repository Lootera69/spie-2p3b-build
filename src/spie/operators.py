"""Phase 4.4 — Invention operators: the roadmap's four mutation families over a Puzzle genome.

Each operator is a pure, deterministic ``Puzzle -> Puzzle | None`` given ``(puzzle, rng)``: it
returns a *new* frozen :class:`~spie.ir.Puzzle` built with :func:`dataclasses.replace`, or ``None``
when it does not apply to the puzzle (so a search can simply skip it). Every operator ends by
running :func:`~spie.validate.validate` on its result and discarding a malformed mutation
(returning ``None``) — so an operator never yields a structurally-broken puzzle, and the MAP-Elites
search (4.5) only ever *certifies* well-formed candidates through the ordinary gates.

The four families mirror roadmap p4:

* **Structural** — couple two variables, transfer a property, reverse a causal edge, compose two
  actions into one.
* **Temporal** — lag an effect (VISIBLE→DELAYED), flip a variable's reset-persistence, synchronize
  two subsystems, introduce reset (time-loop) semantics.
* **Information** — hide a variable (VISIBLE→HIDDEN + belief), reveal it through a sensing action,
  make an observation costly, add a false affordance (decoy action).
* **Goal / constraint** — invert the goal, add a resource budget, require an invariant, remove a
  redundant clue.

Determinism: every choice is an ``rng`` pick over a *sorted* candidate list, so the same
``(puzzle, rng-state)`` always yields the same mutation — the byte-reproducibility discipline
lifted to the search layer.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import replace

from .expr import Assign, Const, Eq, Le, Not, Reset, Sub, Var, all_of
from .interpreter import domain_of
from .ir import Action, Kind, Observability, Puzzle, Variable
from .validate import validate

Operator = Callable[[Puzzle, random.Random], "Puzzle | None"]


def _clean(puzzle: Puzzle) -> Puzzle | None:
    """Return ``puzzle`` iff it is structurally well-formed, else ``None``. Every operator ends
    here so a malformed mutation is discarded rather than offered to the search."""
    return puzzle if not validate(puzzle) else None


def _written_keys(action: Action) -> frozenset[str]:
    """The state variables an action assigns (a Reset marker writes nothing concrete here)."""
    return frozenset(e.key for e in action.effects if isinstance(e, Assign))


def _has_reset(action: Action) -> bool:
    return any(isinstance(e, Reset) for e in action.effects)


def _replace_action(puzzle: Puzzle, index: int, new: Action) -> Puzzle:
    actions = list(puzzle.actions)
    actions[index] = new
    return replace(puzzle, actions=tuple(actions))


# --- Structural -----------------------------------------------------------------------------


def couple_variables(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Couple two variables: append ``y := x`` to an action that already writes ``x`` so ``y``
    tracks ``x`` (same Kind, to stay type-correct) — a new coupling between prior-independent
    state."""
    by_key = puzzle.variables_by_key()
    cands: list[tuple[int, str, str]] = []
    for i, a in enumerate(puzzle.actions):
        written = _written_keys(a)
        for x in sorted(written):
            for y in sorted(by_key):
                if y != x and y not in written and by_key[y].kind is by_key[x].kind:
                    cands.append((i, x, y))
    if not cands:
        return None
    i, x, y = rng.choice(cands)
    a = puzzle.actions[i]
    return _clean(_replace_action(puzzle, i, replace(a, effects=a.effects + (Assign(y, Var(x)),))))


def transfer_property(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Transfer a property: copy one variable's ``persistent`` trait onto another same-Kind
    variable that lacks it (propagating a HasProperty-style relation through the design)."""
    cands: list[tuple[str, str]] = []
    for d in puzzle.variables:
        if not d.persistent:
            continue
        for v in puzzle.variables:
            if v.kind is d.kind and not v.persistent and v.key != d.key:
                cands.append((d.key, v.key))
    cands.sort()
    if not cands:
        return None
    _, target = rng.choice(cands)
    variables = tuple(replace(v, persistent=True) if v.key == target else v
                      for v in puzzle.variables)
    return _clean(replace(puzzle, variables=variables))


def reverse_edge(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Reverse a causal/movement edge ``a->b`` into ``b->a`` (flip a directed relation).
    Applying it to the same edge twice restores the graph (invertible)."""
    present = set(puzzle.edges)
    cands = sorted((a, b) for (a, b) in puzzle.edges if a != b and (b, a) not in present)
    if not cands:
        return None
    a, b = rng.choice(cands)
    edges = tuple((b, a) if (s, d) == (a, b) else (s, d) for (s, d) in puzzle.edges)
    return _clean(replace(puzzle, edges=edges))


def compose_actions(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Compose two parameterless, disjoint-effect actions into one atomic macro action: its
    guard is the conjunction of both guards; it applies both effect sets at once."""
    idx = {a.name: a for a in puzzle.actions if not a.params and not _has_reset(a)}
    names = {a.name for a in puzzle.actions}
    cands: list[tuple[str, str]] = []
    for an, a in idx.items():
        for bn, b in idx.items():
            if an < bn and not (_written_keys(a) & _written_keys(b)) and f"{an}__{bn}" not in names:
                cands.append((an, bn))
    cands.sort()
    if not cands:
        return None
    an, bn = rng.choice(cands)
    a, b = idx[an], idx[bn]
    macro = Action(name=f"{an}__{bn}", precondition=all_of(a.precondition, b.precondition),
                   effects=a.effects + b.effects, cost=a.cost + b.cost)
    return _clean(replace(puzzle, actions=puzzle.actions + (macro,)))


# --- Temporal -------------------------------------------------------------------------------


def delay_effect(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Lag a variable's readout: VISIBLE -> DELAYED with delay 1 (information always shown but
    arriving a tick late)."""
    cands = sorted(v.key for v in puzzle.variables
                   if v.obs is Observability.VISIBLE and v.kind in (Kind.BOOL, Kind.INT))
    if not cands:
        return None
    key = rng.choice(cands)
    variables = tuple(replace(v, obs=Observability.DELAYED, delay=max(1, v.delay))
                      if v.key == key else v for v in puzzle.variables)
    return _clean(replace(puzzle, variables=variables))


def flip_persistence(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Flip whether a variable survives a Reset (make a reset partial / persist state across it).
    Toggling the same variable twice restores the puzzle (invertible)."""
    cands = sorted(v.key for v in puzzle.variables)
    if not cands:
        return None
    key = rng.choice(cands)
    variables = tuple(replace(v, persistent=not v.persistent) if v.key == key else v
                      for v in puzzle.variables)
    return _clean(replace(puzzle, variables=variables))


def synchronize_subsystems(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Synchronize two subsystems: add an invariant tying two same-Kind variables equal, so they
    must move together."""
    by_kind: dict[Kind, list[str]] = {}
    for v in puzzle.variables:
        by_kind.setdefault(v.kind, []).append(v.key)
    cands: list[tuple[str, str]] = []
    for keys in by_kind.values():
        ks = sorted(keys)
        cands.extend((ks[i], ks[j]) for i in range(len(ks)) for j in range(i + 1, len(ks)))
    cands.sort()
    if not cands:
        return None
    x, y = rng.choice(cands)
    obj = replace(puzzle.objective,
                  invariants=puzzle.objective.invariants + (Eq(Var(x), Var(y)),))
    return _clean(replace(puzzle, objective=obj))


def add_reset_action(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Introduce reset (time-loop) semantics: add a parameterless action that Resets all
    non-persistent state. None if the puzzle already has any reset action."""
    if any(_has_reset(a) or a.name == "loop_reset" for a in puzzle.actions):
        return None
    action = Action(name="loop_reset", precondition=Const(True), effects=(Reset(),))
    return _clean(replace(puzzle, actions=puzzle.actions + (action,)))


# --- Information ----------------------------------------------------------------------------


def hide_variable(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Hide a variable's initial value: VISIBLE -> HIDDEN with a belief support spanning its whole
    (>=2-value) domain, so the player must deduce it."""
    cands: list[str] = []
    for v in puzzle.variables:
        if v.obs is not Observability.VISIBLE or v.kind not in (Kind.BOOL, Kind.INT):
            continue
        lo, hi = domain_of(puzzle, v.key)
        if hi > lo:
            cands.append(v.key)
    cands.sort()
    if not cands:
        return None
    key = rng.choice(cands)
    lo, hi = domain_of(puzzle, key)
    variables = tuple(replace(v, obs=Observability.HIDDEN) if v.key == key else v
                      for v in puzzle.variables)
    belief = dict(puzzle.initial_belief)
    belief[key] = tuple(range(lo, hi + 1))
    return _clean(replace(puzzle, variables=variables, initial_belief=belief))


def reveal_variable(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Reveal a variable through a new sensing action: add an action that senses a variable no
    action currently senses (the information channel a hidden fact needs)."""
    sensed = {k for a in puzzle.actions for k in a.senses}
    names = {a.name for a in puzzle.actions}
    cands = sorted(v.key for v in puzzle.variables
                   if v.key not in sensed and f"sense_{v.key}" not in names)
    if not cands:
        return None
    key = rng.choice(cands)
    action = Action(name=f"sense_{key}", precondition=Const(True), effects=(), senses=(key,))
    return _clean(replace(puzzle, actions=puzzle.actions + (action,)))


def make_observation_costly(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Make an observation costly: raise the cost of a sensing action (information no longer
    free). None if the puzzle has no sensing action."""
    cands = sorted(i for i, a in enumerate(puzzle.actions) if a.senses)
    if not cands:
        return None
    i = rng.choice(cands)
    a = puzzle.actions[i]
    return _clean(_replace_action(puzzle, i, replace(a, cost=a.cost + 1)))


def add_decoy_action(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Add a false affordance: an always-enabled decoy action that only writes a variable to its
    own value (a genuine but inert choice that widens the search without helping)."""
    if not puzzle.variables or any(a.name == "decoy" for a in puzzle.actions):
        return None
    key = sorted(v.key for v in puzzle.variables)[0]
    action = Action(name="decoy", precondition=Const(True), effects=(Assign(key, Var(key)),))
    return _clean(replace(puzzle, actions=puzzle.actions + (action,)))


# --- Goal / constraint ----------------------------------------------------------------------


def invert_goal(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Invert the goal: replace it with its negation — a different objective over the same
    state."""
    obj = replace(puzzle.objective, goal=Not(puzzle.objective.goal))
    return _clean(replace(puzzle, objective=obj))


def add_resource_budget(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Add a resource budget: a fresh ``budget`` counter one action spends, gated on the budget
    remaining (a scarcity constraint). None if a ``budget`` variable already exists."""
    if "budget" in puzzle.variables_by_key():
        return None
    spenders = sorted(i for i, a in enumerate(puzzle.actions) if not _has_reset(a))
    if not spenders:
        return None
    cap = max(1, puzzle.objective.max_horizon)
    i = rng.choice(spenders)
    a = puzzle.actions[i]
    new = replace(a, precondition=all_of(a.precondition, Le(Const(1), Var("budget"))),
                  effects=a.effects + (Assign("budget", Sub(Var("budget"), Const(1))),))
    p = replace(puzzle, variables=puzzle.variables + (Variable("budget", Kind.INT, 0, cap),),
                initial={**puzzle.initial, "budget": cap})
    return _clean(_replace_action(p, i, new))


def require_invariant(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Require an invariant: add a conservative domain-bounding invariant on one variable — a new
    always-checked constraint the certified plan must respect."""
    cands = sorted(v.key for v in puzzle.variables)
    if not cands:
        return None
    key = rng.choice(cands)
    _, hi = domain_of(puzzle, key)
    obj = replace(puzzle.objective,
                  invariants=puzzle.objective.invariants + (Le(Var(key), Const(hi)),))
    return _clean(replace(puzzle, objective=obj))


def remove_redundant_clue(puzzle: Puzzle, rng: random.Random) -> Puzzle | None:
    """Remove a redundant clue: drop one invariant constraint (loosening the puzzle). None if
    there is no invariant to remove."""
    invs = puzzle.objective.invariants
    if not invs:
        return None
    j = rng.randrange(len(invs))
    obj = replace(puzzle.objective, invariants=invs[:j] + invs[j + 1:])
    return _clean(replace(puzzle, objective=obj))


# --- Registry -------------------------------------------------------------------------------

STRUCTURAL: tuple[Operator, ...] = (
    couple_variables, transfer_property, reverse_edge, compose_actions,
)
TEMPORAL: tuple[Operator, ...] = (
    delay_effect, flip_persistence, synchronize_subsystems, add_reset_action,
)
INFORMATION: tuple[Operator, ...] = (
    hide_variable, reveal_variable, make_observation_costly, add_decoy_action,
)
GOAL: tuple[Operator, ...] = (
    invert_goal, add_resource_budget, require_invariant, remove_redundant_clue,
)

FAMILIES: dict[str, tuple[Operator, ...]] = {
    "structural": STRUCTURAL,
    "temporal": TEMPORAL,
    "information": INFORMATION,
    "goal": GOAL,
}
OPERATORS: tuple[Operator, ...] = STRUCTURAL + TEMPORAL + INFORMATION + GOAL


__all__ = [
    "Operator",
    "FAMILIES",
    "OPERATORS",
    "STRUCTURAL",
    "TEMPORAL",
    "INFORMATION",
    "GOAL",
    "couple_variables",
    "transfer_property",
    "reverse_edge",
    "compose_actions",
    "delay_effect",
    "flip_persistence",
    "synchronize_subsystems",
    "add_reset_action",
    "hide_variable",
    "reveal_variable",
    "make_observation_costly",
    "add_decoy_action",
    "invert_goal",
    "add_resource_budget",
    "require_invariant",
    "remove_redundant_clue",
]

