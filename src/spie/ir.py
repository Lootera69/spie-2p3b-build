"""Intermediate representation — a puzzle *is* this data structure, not prose.

A puzzle is a bounded discrete state machine over a directed graph of locations:

* ``World``      — the finite state space: locations, edges, typed variables, initial values.
* ``Action``     — a parameterised guarded transition (precondition -> effects).
* ``Objective``  — goal predicate, loss predicate, invariants, and the search horizon.
* ``Puzzle``     — the whole spec plus presentation metadata and a deterministic seed.
* ``Certificate``— the machine-verifiable proof artifact emitted after solving.

Every field is plain data. Behaviour lives in ``evaluate`` (interpreter) and
``z3_compile`` (solver); this module never imports either, to keep the representation
independent of any particular backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .expr import Assign, Expr, Reset
from .results import Plan

Effect = Assign | Reset
"""An action effect: either a concrete :class:`~spie.expr.Assign` or a :class:`~spie.expr.Reset`
marker that grounding expands into assignments for the non-persistent variables."""


class Kind(str, Enum):
    """The domain of a state variable."""

    BOOL = "Bool"
    INT = "Int"
    LOC = "Loc"  # a bounded int index into World.nodes


class Observability(str, Enum):
    """How a variable's value is exposed to the player — the *information model*.

    Phase 3 turns a puzzle from a fully-observable transition system into one where the
    player may have to *deduce* hidden facts. Every existing variable is ``VISIBLE`` (the
    default), so slice-1/2 puzzles are unchanged.

    * ``VISIBLE``    — always observable (the Phase-1/2 world; the default).
    * ``HIDDEN``     — the initial value is unknown-but-fixed, ranging over a declared
      support in :attr:`Puzzle.initial_belief`; only ever learned through sensing.
    * ``DELAYED``    — becomes observable only ``delay`` ticks after it would otherwise be.
    * ``REMEMBERED`` — observable only at the tick a sensing action reads it (transient); the
      player must carry the fact forward themselves.
    """

    VISIBLE = "visible"
    HIDDEN = "hidden"
    DELAYED = "delayed"
    REMEMBERED = "remembered"


@dataclass(frozen=True)
class Variable:
    """A single state variable. ``lo``/``hi`` bound INT and LOC domains (inclusive).
    For BOOL they are ignored. For LOC they default to the full node range at build
    time when left as ``None``.

    The Phase-3 information fields default to the fully-observable behavior, so every
    slice-1/2 variable is unchanged:

    * ``obs``        — the :class:`Observability` of this variable (default ``VISIBLE``).
    * ``delay``      — for ``DELAYED`` variables, how many ticks its value lags visibility.
    * ``persistent`` — whether the value survives a ``Reset`` (Phase 3.6); knowledge the
      player has learned typically persists, transient world state does not.
    """

    key: str
    kind: Kind
    lo: int | None = None
    hi: int | None = None
    obs: Observability = Observability.VISIBLE
    delay: int = 0
    persistent: bool = False


@dataclass(frozen=True)
class Param:
    """A finite action parameter. ``values`` holds either integer literals (for INT
    params) or location *names* (for NODE params). Grounding takes the cross product
    of all params and substitutes each ``PVal`` accordingly."""

    name: str
    is_node: bool
    values: tuple[int | str, ...]


@dataclass(frozen=True)
class Action:
    """A parameterised guarded transition template.

    Grounding expands ``params`` into concrete actions, substituting every ``PVal`` in
    ``precondition`` and ``effects``. A ground action fires only when its precondition
    holds; its effects assign the next-tick value of the named variables; all other
    variables are framed (held constant). An effect may be an :class:`~spie.expr.Assign` or a
    :class:`~spie.expr.Reset` marker; grounding expands each ``Reset`` in place into the
    assignments that restore the non-persistent variables, so the backends see only ``Assign``s.

    ``senses`` names the variables this action *observes* (Phase 3): firing it reveals
    their current values to the player, which is how information enters a contingent plan.
    Empty for every slice-1/2 action, so behavior is unchanged.
    """

    name: str
    precondition: Expr
    effects: tuple[Effect, ...]
    params: tuple[Param, ...] = ()
    cost: int = 1
    senses: tuple[str, ...] = ()


@dataclass(frozen=True)
class Objective:
    """What counts as solved, lost, and always-true, plus the bounded search horizon.

    * ``goal``       — reached when this becomes true.
    * ``loss``       — a forbidden state; if reachable it must never occur on a solution.
    * ``invariants`` — must hold at every tick.
    * ``max_horizon``— the largest number of action steps the solver will unroll.

    Two Phase-2 declarations record *design intent* for the verification gates (both default
    so every slice-1 puzzle stays valid):

    * ``requires_unique`` — whether a unique minimal solution is intended. The uniqueness
      gate fails a puzzle that violates its own declaration.
    * ``trap_policy``     — how silent dead-ends (reachable live states from which the goal
      is unreachable) are judged. ``"allowed"`` treats them as an intended mechanic;
      ``"signaled"`` requires every dead-end to be caught by ``loss`` (so no *silent* trap
      remains), and the dead-state gate fails any that slips through.
    """

    goal: Expr
    max_horizon: int
    loss: Expr | None = None
    invariants: tuple[Expr, ...] = ()
    requires_unique: bool = True
    trap_policy: str = "allowed"


@dataclass(frozen=True)
class Puzzle:
    """A complete puzzle specification."""

    id: str
    title: str
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    variables: tuple[Variable, ...]
    initial: dict[str, int | bool]
    actions: tuple[Action, ...]
    objective: Objective
    seed: int = 0
    notes: str = ""
    initial_belief: dict[str, tuple[int, ...]] = field(default_factory=dict)
    """Per-``HIDDEN``-variable support: the finite set of possible initial values the
    player cannot distinguish at the start. Empty (the default) ⇒ the initial belief is a
    singleton and the puzzle reduces exactly to the fully-observable Phase-1/2 model."""

    def node_index(self) -> dict[str, int]:
        """Map location name -> its integer index. The canonical name<->int bridge."""
        return {name: i for i, name in enumerate(self.nodes)}

    def variables_by_key(self) -> dict[str, Variable]:
        return {v.key: v for v in self.variables}


# ---------------------------------------------------------------------------
# Solve / certification artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One entry in a solution trace: the ground action name fired at this tick."""

    tick: int
    action: str


@dataclass(frozen=True)
class SolverEvidence:
    """One independent solver's verdict on a puzzle — the unit of cross-solver agreement.

    A certificate carries one of these per method (Z3 bounded model checking, explicit-state
    search, ...). When every method reports the same ``(solvable, horizon, cost, unique)``,
    the proof is corroborated rather than merely asserted by a single tool (gate G2)."""

    name: str
    version: str
    solvable: bool
    horizon: int
    cost: int
    unique: bool


@dataclass(frozen=True)
class EpistemicEvidence:
    """One independent *contingent* solver's verdict under partial observability — the
    epistemic analogue of :class:`SolverEvidence` (gate **G2** lifted to hidden state).

    A puzzle with hidden initial state is solved by two zero-shared-code methods —
    belief-space AND/OR search (:mod:`spie.epistemic`, Method A) and bounded multi-world SMT
    (:mod:`spie.z3_epistemic`, Method B). Each reports the cross-checked triple
    ``(solvable, depth, unique)`` where ``depth`` is the minimal *worst-case* number of
    actions along any root-to-leaf path of the contingent plan (the epistemic analogue of a
    linear ``horizon``). ``cost`` is intentionally absent: the epistemic methods optimise
    worst-case depth, not summed action cost, and Method B never materialises a plan tree to
    sum costs over — so a cross-checked cost does not exist and is not invented here."""

    name: str
    version: str
    solvable: bool
    depth: int
    unique: bool


@dataclass(frozen=True)
class WorldReplay:
    """One world of the initial belief ``B0`` replayed through the interpreter under the
    certified contingent plan — the per-world unit of epistemic conformance.

    ``world`` is the concrete initial state (variable values in declared order, hidden
    variables pinned to this world's value); ``trace`` is the linear action sequence the plan
    prescribes *for this world* once its observations are followed down the branch tree;
    ``reached_goal`` and ``ok`` record whether that trace, replayed in the deterministic
    interpreter, reaches the goal and does so legally (no precondition, invariant, or ``loss``
    violation). A plan is strongly conformant iff every ``B0`` world's replay is ``ok``."""

    world: tuple[int, ...]
    trace: tuple[str, ...]
    reached_goal: bool
    ok: bool


@dataclass(frozen=True)
class Certificate:
    """The machine-verifiable proof artifact for a solved puzzle.

    The Phase-3 epistemic fields default to the fully-observable case so a puzzle with no
    hidden state produces a byte-identical certificate to Phase 1/2: ``plan`` is ``None``, and
    ``epistemic`` / ``world_replays`` are empty. For a puzzle *with* hidden state these carry,
    respectively, the certified contingent plan (a policy tree), the per-method epistemic
    cross-check evidence (Method A vs Method B), and the per-``B0``-world interpreter replay."""

    puzzle_id: str
    seed: int
    solver: str
    solver_version: str
    horizon: int
    solvable: bool
    solution: tuple[Step, ...]
    unique: bool
    equivalence: str
    conformance_ok: bool
    warnings: list[str] = field(default_factory=list)
    solvers: tuple[SolverEvidence, ...] = ()
    plan: Plan | None = None
    epistemic: tuple[EpistemicEvidence, ...] = ()
    world_replays: tuple[WorldReplay, ...] = ()
