"""Belief-space search — the concrete epistemic solver (Phase 3, Method A).

Phase 2's decision gate **G2** demanded two independent solving methods; Phase 3 lifts
that bar to *partial observability*. This module is the belief-space analogue of
:mod:`spie.search`: it proves **strong solvability** — the existence of a contingent plan
that reaches the goal and avoids ``loss`` on *every* world the player cannot rule out —
concretely, by retrograde AND/OR fixpoint over the powerset of live world states, using
only the interpreter's own semantics (:func:`spie.evaluate.eval_bool` /
:func:`spie.evaluate.apply_effects`). Its symbolic counterpart, :mod:`spie.z3_epistemic`
(Method B), will prove the same facts by multi-world SMT and share **zero** code with this
file, so when the two agree the *epistemic* proof is cross-validated, not merely asserted.

Belief-space model
-------------------
A **belief** is the finite set of concrete world states consistent with everything the
player has observed so far (``Belief = frozenset[WorldState]``). The player never sees which
world is real; they may only choose an action that is *known-legal in every world of the
current belief* (the **uniformity / no-clairvoyance** rule — a decision may depend only on
observed history). Firing such an action:

* maps each world through the deterministic transition (the belief's forward *image*), and
* **partitions** that image by what is now observable — the always-visible variables plus
  whatever the action ``senses``. Each cell of the partition is a successor belief; a
  cell-count above one is a genuine *branch* of the contingent plan.

A belief is *winning at depth 0* iff the goal holds in all its worlds; otherwise it is
winning iff some safe action makes **every** resulting cell winning (AND over observation
outcomes, OR over action choices). The least such fixpoint gives the minimal worst-case
depth, the epistemic analogue of ``search``'s horizon.

Reduction anchor
----------------
When no variable is ``HIDDEN`` the initial belief is a singleton, every belief stays a
singleton (the always-visible observation distinguishes every successor), and the partition
never splits: the contingent plan degenerates to a single linear trace. On the 14
fully-observable corpus puzzles this solver therefore returns *exactly* what
:func:`spie.search.canonical_solution` returns — same actions, same length — which is both
the backward-compatibility guarantee and the regression oracle for everything above.
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass

from . import augment
from .evaluate import Context, apply_effects, eval_bool
from .ground import ground_all
from .interpreter import domain_of, initial_state
from .ir import Observability, Puzzle
from .results import EQUIVALENCE, Plan, Uniqueness

SOLVER_NAME = "belief-search"
SOLVER_VERSION = "1.0"

# Safety bound on the number of distinct beliefs explored. Belief space is finite (the
# powerset of a finite live world set) but worst-case exponential, so exploration degrades
# gracefully rather than hanging. Hand puzzles stay far below this.
DEFAULT_MAX_BELIEFS = 100_000

WorldState = tuple[int, ...]  # canonical world: variable values in declared order
Belief = frozenset[WorldState]  # the set of worlds the player still considers possible

# A branch of an expansion: (observed valuation, successor-belief id). An expansion is one
# safe action together with the beliefs its observation outcomes lead to.
_Branch = tuple[tuple[int, ...], int]
_Expansion = tuple[str, tuple[_Branch, ...]]


# --- local semantic helpers (mirrors of spie.search) ---------------------------------
# Re-implemented here rather than imported so this module is a self-contained, independent
# method. Each is a thin composition over evaluate.py's single source of semantics, so it
# cannot drift from search.py's copy without the reduction test firing immediately.


def _var_keys(puzzle: Puzzle) -> tuple[str, ...]:
    return tuple(v.key for v in puzzle.variables)


def _to_tuple(state: dict[str, int], var_keys: tuple[str, ...]) -> WorldState:
    return tuple(state[k] for k in var_keys)


def _to_dict(state: WorldState, var_keys: tuple[str, ...]) -> dict[str, int]:
    return dict(zip(var_keys, state, strict=True))


def _live(puzzle: Puzzle, ctx: Context, domains: dict[str, tuple[int, int]],
          state: dict[str, int]) -> bool:
    """Would Z3 admit this world at a tick? True iff every variable is within its declared
    domain, every invariant holds, and the loss predicate does not — the exact per-tick
    conjunction the other backends assert, so all methods prune identically."""
    for key, (lo, hi) in domains.items():
        if not (lo <= state[key] <= hi):
            return False
    for inv in puzzle.objective.invariants:
        if not eval_bool(inv, state, ctx):
            return False
    if puzzle.objective.loss is not None and eval_bool(puzzle.objective.loss, state, ctx):
        return False
    return True


def _observable_keys(puzzle: Puzzle) -> tuple[str, ...]:
    """The variables the player observes every tick without sensing: the ``VISIBLE`` ones,
    in sorted order for a stable partition-key layout.

    In a fully-observable puzzle this is *every* variable, so a belief's forward image is
    partitioned by the whole successor state — each successor lands in its own cell and a
    singleton belief stays a singleton. (Phase 3.2 treats ``DELAYED`` / ``REMEMBERED`` as
    learned only through an action's ``senses``; their standing-observation refinement is
    deferred.)"""
    return tuple(sorted(v.key for v in puzzle.variables if v.obs is Observability.VISIBLE))


def build_initial_belief(
    puzzle: Puzzle,
    ctx: Context | None = None,
    domains: dict[str, tuple[int, int]] | None = None,
    var_keys: tuple[str, ...] | None = None,
) -> Belief:
    """The initial belief ``B0``: every world consistent with the start observation.

    Visible variables are pinned to their declared initial values; each ``HIDDEN`` variable
    ranges over its :attr:`~spie.ir.Puzzle.initial_belief` support. ``B0`` is the cross
    product of those supports, keeping only *live* worlds. With no hidden variables the
    product is a single combination, so ``B0`` is the singleton ``{initial_state}`` (or
    empty if the initial state is not live) — exactly the Phase-1/2 starting point.
    """
    puzzle = augment.desugar(puzzle)
    if ctx is None:
        ctx = Context.from_puzzle(puzzle)
    if var_keys is None:
        var_keys = _var_keys(puzzle)
    if domains is None:
        domains = {v.key: domain_of(puzzle, v.key) for v in puzzle.variables}

    init_dict = initial_state(puzzle)
    hidden_keys = sorted(puzzle.initial_belief.keys())
    supports = [puzzle.initial_belief[k] for k in hidden_keys]

    worlds: set[WorldState] = set()
    for combo in itertools.product(*supports):
        wd = dict(init_dict)
        for k, val in zip(hidden_keys, combo, strict=True):
            wd[k] = val
        if _live(puzzle, ctx, domains, wd):
            worlds.add(_to_tuple(wd, var_keys))
    return frozenset(worlds)


def _is_goal_belief(puzzle: Puzzle, ctx: Context, var_keys: tuple[str, ...],
                    belief: Belief) -> bool:
    """True iff the goal holds in *every* world of a non-empty belief — the strong-plan
    termination test (the player is certain the goal is reached whatever the real world)."""
    if not belief:
        return False
    goal = puzzle.objective.goal
    return all(eval_bool(goal, _to_dict(w, var_keys), ctx) for w in belief)


def _expand(puzzle: Puzzle, ctx: Context, ground, domains: dict[str, tuple[int, int]],
            obs_base: tuple[str, ...], var_keys: tuple[str, ...],
            belief: Belief) -> list[_Expansion]:
    """Every *safe* action from ``belief`` and the successor beliefs its observations yield.

    An action is safe only when, in **all** worlds of the belief, its precondition holds and
    its successor is live — the uniformity rule (choose only known-legal actions) plus the
    strong-plan requirement that no possible world may hit ``loss``. The safe action's image
    is then partitioned by the observed valuation (visible variables ∪ the action's
    ``senses``); each cell becomes a successor belief. Cells are ordered by their observed
    valuation so the resulting plan is deterministic.
    """
    expansions: list[_Expansion] = []
    world_dicts = [_to_dict(w, var_keys) for w in belief]
    for ga in ground:
        if not all(eval_bool(ga.precondition, wd, ctx) for wd in world_dicts):
            continue
        succ_dicts = [apply_effects(ga.effects, wd, ctx) for wd in world_dicts]
        if not all(_live(puzzle, ctx, domains, sd) for sd in succ_dicts):
            continue
        observed = sorted(set(obs_base) | set(ga.senses))
        cells: dict[tuple[int, ...], set[WorldState]] = {}
        for sd in succ_dicts:
            obs_key = tuple(sd[k] for k in observed)
            cells.setdefault(obs_key, set()).add(_to_tuple(sd, var_keys))
        branches = tuple(
            (obs_key, frozenset(states)) for obs_key, states in sorted(cells.items())
        )
        expansions.append((ga.name, branches))
    return expansions


@dataclass
class _BeliefGraph:
    """The reachable belief space of a puzzle, built breadth-first from ``B0``.

    ``beliefs`` are the distinct beliefs (discovery order); ``succ`` maps a belief id to its
    safe expansions (each an action and its observation-branched successor ids); ``goals`` is
    the set of belief ids where the goal is certain. ``b0`` is the initial belief's id, or
    ``None`` when ``B0`` is empty (the initial observation is unsatisfiable — unsolvable).
    ``truncated`` is set if ``max_beliefs`` was hit, in which case any conclusion drawn is
    not complete.
    """

    var_keys: tuple[str, ...]
    beliefs: list[Belief]
    succ: dict[int, list[_Expansion]]
    goals: set[int]
    b0: int | None
    truncated: bool


def _build(puzzle: Puzzle, max_beliefs: int) -> _BeliefGraph:
    """Breadth-first enumeration of the reachable belief space from ``B0``.

    Goal beliefs are terminal — never expanded — since a strong plan stops the moment the
    goal is certain. Every other belief is expanded through :func:`_expand`; successor cells
    are interned so shared beliefs are visited once.
    """
    puzzle = augment.desugar(puzzle)
    ctx = Context.from_puzzle(puzzle)
    ground = ground_all(puzzle)
    var_keys = _var_keys(puzzle)
    domains = {v.key: domain_of(puzzle, v.key) for v in puzzle.variables}
    obs_base = _observable_keys(puzzle)

    beliefs: list[Belief] = []
    index: dict[Belief, int] = {}
    succ: dict[int, list[_Expansion]] = {}
    goals: set[int] = set()

    b0_belief = build_initial_belief(puzzle, ctx, domains, var_keys)
    if not b0_belief:
        return _BeliefGraph(var_keys, beliefs, succ, goals, None, False)

    def add(belief: Belief) -> int:
        bid = index.get(belief)
        if bid is None:
            bid = len(beliefs)
            beliefs.append(belief)
            index[belief] = bid
            succ[bid] = []
        return bid

    b0 = add(b0_belief)
    truncated = False
    queue = deque([b0])
    while queue:
        bid = queue.popleft()
        belief = beliefs[bid]
        if _is_goal_belief(puzzle, ctx, var_keys, belief):
            goals.add(bid)
            continue
        for action, branches in _expand(puzzle, ctx, ground, domains, obs_base, var_keys, belief):
            child_branches: list[_Branch] | None = []
            for obs_key, cell in branches:
                if cell not in index and len(beliefs) >= max_beliefs:
                    truncated = True
                    child_branches = None  # cannot represent this action completely
                    break
                is_new = cell not in index
                cid = add(cell)
                child_branches.append((obs_key, cid))
                if is_new:  # enqueue genuinely new beliefs only — never a revisit/self-loop
                    queue.append(cid)
            if child_branches is not None:
                succ[bid].append((action, tuple(child_branches)))

    return _BeliefGraph(var_keys, beliefs, succ, goals, b0, truncated)


def _win_depths(graph: _BeliefGraph) -> dict[int, int]:
    """Least-fixpoint minimal worst-case depth per belief (∞ = absent from the result).

    Goal beliefs have depth 0. Any other belief relaxes to ``1 + max(child depths)`` for its
    best safe action whose every observation branch is already winning — the AND (over
    branches) / OR (over actions) recurrence of strong planning. Depth strictly decreases
    along optimal edges, so the winning sub-relation is a DAG.
    """
    depth: dict[int, int] = {bid: 0 for bid in graph.goals}
    changed = True
    while changed:
        changed = False
        for bid in range(len(graph.beliefs)):
            if bid in graph.goals:
                continue
            best: int | None = None
            for _, branches in graph.succ.get(bid, []):
                if all(cid in depth for _, cid in branches):
                    d = 1 + max(depth[cid] for _, cid in branches)
                    if best is None or d < best:
                        best = d
            if best is not None and (bid not in depth or best < depth[bid]):
                depth[bid] = best
                changed = True
    return depth


def _canonical_plan_from(graph: _BeliefGraph, depth: dict[int, int], bid: int) -> Plan:
    """The reproducible optimal contingent plan rooted at belief ``bid``.

    Among the *optimal* safe actions (those achieving the belief's minimal depth) it takes
    the lexicographically-least action name — a choice fixed by the puzzle alone, so the plan
    is byte-reproducible. On singleton beliefs this is precisely
    :func:`spie.search.canonical_solution`'s greedy lex-least step (ground action names are
    unique, so a name tie-break is total), which is why the linear reduction is exact.
    """
    if bid in graph.goals:
        return Plan(action=None)
    d = depth[bid]
    optimal: list[_Expansion] = []
    for action, branches in graph.succ.get(bid, []):
        if all(cid in depth for _, cid in branches):
            if 1 + max(depth[cid] for _, cid in branches) == d:
                optimal.append((action, branches))
    action, branches = min(optimal, key=lambda ab: ab[0])
    children = tuple(
        (obs_key, _canonical_plan_from(graph, depth, cid)) for obs_key, cid in branches
    )
    return Plan(action=action, branches=children)


@dataclass(frozen=True)
class StrongSolution:
    """Outcome of a strong (contingent) solve — the epistemic analogue of ``Solution``.

    ``depth`` is the minimal worst-case number of actions along any root-to-leaf path of the
    plan (equal to a linear ``horizon`` when nothing is hidden); ``belief_count`` and
    ``truncated`` expose the size of the explored belief space and whether the bound was hit.
    On an unsolvable puzzle ``depth`` mirrors ``search``'s convention of reporting the
    objective's ``max_horizon``.
    """

    solvable: bool
    depth: int
    plan: Plan | None
    belief_count: int
    truncated: bool


def solve_strong(puzzle: Puzzle, max_beliefs: int = DEFAULT_MAX_BELIEFS) -> StrongSolution:
    """Decide strong solvability and, if solvable, extract the canonical contingent plan."""
    graph = _build(puzzle, max_beliefs)
    if graph.b0 is None:
        return StrongSolution(False, puzzle.objective.max_horizon, None, 0, graph.truncated)
    depth = _win_depths(graph)
    if graph.b0 not in depth:
        return StrongSolution(
            False, puzzle.objective.max_horizon, None, len(graph.beliefs), graph.truncated
        )
    plan = _canonical_plan_from(graph, depth, graph.b0)
    return StrongSolution(True, depth[graph.b0], plan, len(graph.beliefs), graph.truncated)


# The public "minimal-worst-case-depth" entry point, named to mirror ``search.solve``.
solve = solve_strong


def canonical_plan(puzzle: Puzzle, max_beliefs: int = DEFAULT_MAX_BELIEFS) -> Plan | None:
    """The canonical contingent plan for a puzzle, or ``None`` when it is not strongly
    solvable. On a fully-observable puzzle the plan is linear and its
    :meth:`~spie.results.Plan.linear_trace` equals ``search.canonical_solution``'s trace."""
    return solve_strong(puzzle, max_beliefs).plan


def _unique(graph: _BeliefGraph, depth: dict[int, int], bid: int,
            memo: dict[int, bool]) -> bool:
    """Is the optimal contingent plan unique under the belief-trajectory equivalence?

    Two optimal actions collapse when they reach the *same set of successor beliefs* (the
    epistemic form of ``search``'s parallel-edge / same-state-path collapse); genuinely
    different successor sets mean two distinct plans. A belief is uniquely solvable iff its
    optimal actions induce exactly one such successor set and every cell of it is, in turn,
    uniquely solvable.
    """
    if bid in memo:
        return memo[bid]
    if bid in graph.goals:
        memo[bid] = True
        return True
    d = depth[bid]
    forests: set[frozenset[int]] = set()
    for _, branches in graph.succ.get(bid, []):
        if all(cid in depth for _, cid in branches):
            if 1 + max(depth[cid] for _, cid in branches) == d:
                forests.add(frozenset(cid for _, cid in branches))
    if len(forests) != 1:
        memo[bid] = False
        return False
    result = all(_unique(graph, depth, cid, memo) for cid in next(iter(forests)))
    memo[bid] = result
    return result


def check_uniqueness(puzzle: Puzzle, max_beliefs: int = DEFAULT_MAX_BELIEFS) -> Uniqueness:
    """Decide plan uniqueness by belief-space enumeration, mirroring
    :func:`spie.search.check_uniqueness`'s verdict shape and equivalence. An unsolvable
    puzzle is reported unique (vacuously), as ``search`` does."""
    graph = _build(puzzle, max_beliefs)
    if graph.b0 is None:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)
    depth = _win_depths(graph)
    if graph.b0 not in depth:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)
    unique = _unique(graph, depth, graph.b0, {})
    return Uniqueness(unique=unique, equivalence=EQUIVALENCE, witness=None)


def solver_version() -> str:
    return SOLVER_VERSION


__all__ = [
    "SOLVER_NAME",
    "SOLVER_VERSION",
    "solver_version",
    "DEFAULT_MAX_BELIEFS",
    "WorldState",
    "Belief",
    "StrongSolution",
    "build_initial_belief",
    "solve",
    "solve_strong",
    "canonical_plan",
    "check_uniqueness",
]
