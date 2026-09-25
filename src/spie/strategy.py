"""Bounded-rational strategy solving and the surprise proxy (Phase 5, stage 5: EVALUATION).

The quality vector (:mod:`spie.quality`) measures a puzzle's *structure*. This module adds the
last two EVALUATION signals the roadmap asks for and that structure alone cannot give:

* a **human-like difficulty** read, from a deliberately *myopic* solver that plays the puzzle
  the way a bounded-rational person would -- greedy on a shallow look-ahead, physically
  backtracking out of dead ends -- so its effort (steps taken, backtracks, memory load) is a
  behavioural difficulty signal, not just a graph statistic; and
* **surprise**, defined as the myopic model's *prediction error just before the key inference*:
  how badly the greedy player is fooled at the puzzle's pivotal moment. High surprise is the
  mark of a genuine "aha", which pure difficulty misses.

Both are **deterministic functions of the puzzle** -- the discipline every descriptor obeys --
and neither needs any player data. The strategy solver is LLM-free and shares the interpreter's
own semantics; it is the same bounded-rational process the LEARNING stage (Phase 5.4) later turns
into a synthetic player, so difficulty here and observed effort there are commensurable.

Two regimes, mirroring :func:`spie.quality.descriptors` and :func:`spie.certificate.certify`:

* **Fully observable** -- greedy best-first DFS with chronological backtracking over the
  ``_live``-pruned reachability graph (:mod:`spie.search`). The heuristic ``h_L`` counts
  unsatisfied goal conjuncts, minimised over a look-ahead of :data:`LOOKAHEAD` edges, so a
  deception deeper than the horizon fools it. Surprise is *regret*: at each step of the
  canonical solution, how much further from the goal the greedy move would have landed than the
  forced move, read against the exact reachability oracle :func:`spie.search.goal_distance`.
* **Partially observable** -- the strategy read is taken from the certified contingent plan (its
  worst-case depth, branch factor, action count); a correct strong plan never physically
  backtracks, so ``backtracks`` is ``0`` by construction. Surprise is *belief collapse*: the
  largest single-step drop in log-belief-size along the plan, in bits, normalised by the total
  hidden information ``log2(|B0|)`` -- the moment the most uncertainty is resolved at once.

**Deliberate separation of concerns.** The strategy solver's heuristic **never** consults
:func:`spie.search.goal_distance`; that exact distance is reserved as *surprise's* reality
oracle. If the player could see the true distance it could not be fooled, and surprise -- the
gap between the myopic prediction and reality -- would collapse to zero. Keeping the two apart is
what makes the prediction error meaningful rather than circular.

**Reduction anchor.** On a clean linear puzzle the greedy player never backtracks
(``backtracks == 0``), takes exactly the optimal number of steps (``inference_depth`` equals the
difficulty depth), and is never surprised (``score == 0.0``) -- the degenerate values these
proxies must take when there is nothing to deduce. Surprise is a *reported* descriptor only; it
is intentionally kept out of the MAP-Elites fitness (rewarding deceptiveness there would invite
trap-spam), so adding it perturbs no archive or certificate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import epistemic, search
from . import expr as E
from .evaluate import Context, eval_bool
from .ir import Puzzle
from .results import Plan

# The myopic player's planning horizon: how many edges ahead ``h_L`` looks. A deception whose
# payoff lies deeper than this is invisible to the heuristic, so the player commits to it and
# must backtrack -- the mechanism that turns a deep trap into measured effort and surprise.
LOOKAHEAD = 2

# Effort guard, mirroring ``search.DEFAULT_MAX_STATES``: a run exceeding this many descents plus
# backtracks reports ``complete=False`` instead of exploring an intractable space. Generous
# enough that no hand puzzle approaches it; the reachable graph is already bounded upstream.
MAX_STRATEGY_STEPS = 4 * search.DEFAULT_MAX_STATES

_NO_PIVOT = -1


@dataclass(frozen=True)
class StrategyResult:
    """What the bounded-rational player experiences solving the puzzle.

    ``inference_depth`` is the length of the path it finally commits to (optimal on a clean
    puzzle). ``branching_faced`` is the widest choice it met; ``backtracks`` counts dead-end
    retreats (``0`` for a puzzle with no deception, or any contingent plan); ``memory_load`` is
    the deepest committed stack it had to hold; ``steps_taken`` is total forward descents
    (strictly more than ``inference_depth`` exactly when it was fooled into a detour).
    ``complete`` is ``False`` only if the effort guard :data:`MAX_STRATEGY_STEPS` was hit."""

    solvable: bool
    inference_depth: int
    branching_faced: int
    backtracks: int
    memory_load: int
    steps_taken: int
    complete: bool


@dataclass(frozen=True)
class Surprise:
    """The myopic model's prediction error at the puzzle's pivotal moment.

    ``score`` is in ``[0, 1)`` for the fully-observable regret regime and ``[0, 1]`` for the
    belief-collapse regime; ``0.0`` means the greedy player is never fooled. ``pivot_index`` is
    where the pivot falls (a step index on the canonical solution, or a pre-order index among the
    plan's decision nodes), ``-1`` when there is no surprise. ``pivot_kind`` is ``"plan-flip"``
    (regret), ``"belief-collapse"`` (information), or ``"none"``. ``prediction_error`` /
    ``regret_steps`` / ``bits_resolved`` expose the raw pivot magnitude (regret in steps for the
    observable regime, bits of belief resolved for the hidden one)."""

    score: float
    pivot_index: int
    pivot_kind: str
    prediction_error: float
    bits_resolved: float
    regret_steps: int


def _no_surprise() -> Surprise:
    """The degenerate verdict: the greedy model predicted the pivotal move correctly."""
    return Surprise(0.0, _NO_PIVOT, "none", 0.0, 0.0, 0)


# Degenerate singletons for an unmeasurable / default puzzle -- the values a trivial puzzle takes,
# reused as the ``QualityVector`` field defaults so the descriptor stays additive.
DEGENERATE_STRATEGY = StrategyResult(
    solvable=True,
    inference_depth=0,
    branching_faced=0,
    backtracks=0,
    memory_load=0,
    steps_taken=0,
    complete=True,
)
DEGENERATE_SURPRISE = _no_surprise()


# --- the myopic heuristic ------------------------------------------------------------------


def _lookahead_heuristic(puzzle: Puzzle, graph: search.ReachGraph):
    """Build the bounded-rational heuristic ``h_L`` for a fully-observable puzzle.

    ``base_h(n)`` counts the goal conjuncts unsatisfied at state ``n`` (via the interpreter's own
    :func:`spie.evaluate.eval_bool`, so it cannot drift from the runtime). ``h_L(n)`` minimises
    ``base_h`` over every node within :data:`LOOKAHEAD` edges of ``n`` -- a shallow, greedy
    estimate that is fooled by any deception whose payoff lies deeper than the horizon. It
    **never** consults :func:`spie.search.goal_distance`; that exact oracle is reserved for
    surprise. Both layers are memoised per node index (each is a pure function of the node)."""
    ctx = Context.from_puzzle(puzzle)
    goal = puzzle.objective.goal
    conjuncts = goal.operands if isinstance(goal, E.And) else (goal,)
    base_cache: dict[int, int] = {}
    hl_cache: dict[int, int] = {}

    def base_h(node: int) -> int:
        cached = base_cache.get(node)
        if cached is None:
            sd = dict(zip(graph.var_keys, graph.states[node], strict=True))
            cached = sum(1 for c in conjuncts if not eval_bool(c, sd, ctx))
            base_cache[node] = cached
        return cached

    def hl(node: int) -> int:
        cached = hl_cache.get(node)
        if cached is not None:
            return cached
        best = base_h(node)
        frontier = {node}
        seen = {node}
        for _ in range(LOOKAHEAD):
            nxt: set[int] = set()
            for u in frontier:
                for _, w in graph.adj.get(u, ()):
                    if w not in seen:
                        seen.add(w)
                        nxt.add(w)
                        b = base_h(w)
                        if b < best:
                            best = b
            if not nxt:
                break
            frontier = nxt
        hl_cache[node] = best
        return best

    return hl


# --- fully-observable regime ---------------------------------------------------------------


def _strategy_fo(puzzle: Puzzle, graph: search.ReachGraph) -> StrategyResult:
    """Play the puzzle myopically: greedy best-first DFS with chronological backtracking.

    At each node the player descends into the child minimising ``h_L`` (ties broken by ground
    action name, then node index -- the same total spine :func:`spie.search.canonical_solution`
    uses, so the walk is deterministic). A ``visited``-on-graph guard forbids revisiting any node
    (self-loops and back-edges in ``graph.adj`` are thereby skipped), and an exhausted frame is
    popped -- a physical backtrack. ``inference_depth`` is the committed root-to-goal path length
    at success; ``steps_taken`` counts every forward descent (it exceeds ``inference_depth``
    exactly when the player was lured into a dead end and had to retreat)."""
    solvable = graph.initial_live and bool(graph.goals)
    if not solvable:
        return StrategyResult(False, 0, 0, 0, 0, 0, True)

    hl = _lookahead_heuristic(puzzle, graph)
    i0 = graph.index[graph.initial]

    def frame(node: int) -> list:
        children = sorted(graph.adj.get(node, ()), key=lambda e: (hl(e[1]), e[0], e[1]))
        return [node, children, 0]

    visited = {i0}
    stack = [frame(i0)]
    steps = 0
    backtracks = 0
    branching_faced = graph.out_degree(i0)
    memory_load = 1

    while stack:
        if steps + backtracks >= MAX_STRATEGY_STEPS:
            return StrategyResult(True, 0, branching_faced, backtracks, memory_load, steps, False)
        node, children, _ = stack[-1]
        if node in graph.goals:
            return StrategyResult(
                True, len(stack) - 1, branching_faced, backtracks, memory_load, steps, True
            )
        nxt: int | None = None
        while stack[-1][2] < len(children):
            cand = children[stack[-1][2]][1]
            stack[-1][2] += 1
            if cand not in visited:
                nxt = cand
                break
        if nxt is None:
            stack.pop()
            backtracks += 1
            continue
        visited.add(nxt)
        steps += 1
        stack.append(frame(nxt))
        memory_load = max(memory_load, len(stack))
        branching_faced = max(branching_faced, graph.out_degree(nxt))

    return StrategyResult(True, 0, branching_faced, backtracks, memory_load, steps, True)


def _surprise_fo(puzzle: Puzzle, graph: search.ReachGraph) -> Surprise:
    """Regret of the greedy move against the reachability oracle, at the canonical solution's
    most misleading step.

    Walk the canonical (forced-optimal) path. At each on-path node ``n`` the greedy player would
    instead pick the ``h_L``-minimising successor ``g`` (excluding the self-loop -- staying put is
    never a genuine move). The exact remaining distance ``rd`` is
    :func:`spie.search.goal_distance` (nodes that cannot reach the goal are capped at
    ``INF = |states|``). Regret is how much further the greedy move lands than the forced one::

        rho(t) = (1 + rd[g]) - rd[n]        (>= 0, since the forced move is optimal)

    The pivot is the earliest step of maximal regret; the score ``rho / (rho + D)`` normalises it
    by the optimal depth ``D`` so a deep puzzle is not automatically more surprising. Zero regret
    everywhere -- an undeceptive puzzle -- yields the degenerate no-surprise verdict."""
    if not (graph.initial_live and graph.goals):
        return _no_surprise()

    rd = search.goal_distance(graph)
    inf = len(graph.states)
    denom = max(graph.min_goal_dist() or 0, 1)
    hl = _lookahead_heuristic(puzzle, graph)

    canon = search.canonical_solution(puzzle)
    if not canon.solvable or not canon.state_path:
        return _no_surprise()
    node_path = [graph.index[s] for s in canon.state_path]

    best_regret = 0
    best_index = _NO_PIVOT
    for t, n in enumerate(node_path[:-1]):
        moves = [(hl(w), action, w) for action, w in graph.adj.get(n, ()) if w != n]
        if not moves:
            continue
        greedy = min(moves)[2]
        regret = (1 + rd.get(greedy, inf)) - rd.get(n, inf)
        if regret > best_regret:
            best_regret = regret
            best_index = t

    if best_regret <= 0:
        return _no_surprise()
    score = round(best_regret / (best_regret + denom), 6)
    return Surprise(score, best_index, "plan-flip", float(best_regret), 0.0, best_regret)


# --- partially-observable regime -----------------------------------------------------------


def _strategy_hidden(strong: epistemic.StrongSolution) -> StrategyResult:
    """The bounded-rational read for a hidden puzzle, taken from the certified contingent plan.

    A strong plan reaches the goal on *every* world without ever entering a losing state, so the
    player never physically backtracks (``backtracks == 0`` by construction). ``inference_depth``
    is the plan's worst-case depth, ``branching_faced`` its widest sensing fan-out, ``memory_load``
    the same (the deepest simultaneous set of live contingencies the player must hold), and
    ``steps_taken`` the count of decision nodes (actions committed across all branches)."""
    plan = strong.plan
    if not strong.solvable or plan is None:
        return StrategyResult(False, 0, 0, 0, 0, 0, not strong.truncated)
    return StrategyResult(
        solvable=True,
        inference_depth=plan.depth(),
        branching_faced=plan.branch_factor(),
        backtracks=0,
        memory_load=plan.branch_factor(),
        steps_taken=plan.internal_count(),
        complete=not strong.truncated,
    )


def _surprise_hidden(puzzle: Puzzle, strong: epistemic.StrongSolution) -> Surprise:
    """Belief collapse: the largest single-step drop in log-belief-size along the plan.

    Following the canonical plan through the reachable belief space (rebuilt here,
    deterministically, so observation keys and successor ids align with ``strong.plan``), each
    decision node splits a belief of ``before`` worlds into observation cells; the player's
    worst-case posterior is the largest cell. The information resolved at that step is::

        bits(t) = log2(before) - log2(max_cell)

    The pivot is the earliest node of maximal ``bits``; the score normalises it by the total hidden
    information ``log2(|B0|)``, so a step that resolves *all* remaining uncertainty scores ``1.0``.
    A singleton ``B0`` (nothing hidden) or a leaf plan yields the degenerate no-surprise verdict."""
    plan = strong.plan
    if not strong.solvable or plan is None or plan.is_leaf:
        return _no_surprise()

    graph = epistemic._build(puzzle, epistemic.DEFAULT_MAX_BELIEFS)
    if graph.b0 is None:
        return _no_surprise()
    b0_size = len(graph.beliefs[graph.b0])
    if b0_size <= 1:
        return _no_surprise()

    records: list[tuple[int, float]] = []
    counter = [0]

    def walk(bid: int, node: Plan) -> None:
        if node.is_leaf:
            return
        idx = counter[0]
        counter[0] += 1
        branches = None
        for action, brs in graph.succ.get(bid, ()):
            if action == node.action:
                branches = brs
                break
        if branches is None:
            return
        before = len(graph.beliefs[bid])
        max_cell = max(len(graph.beliefs[cid]) for _, cid in branches)
        records.append((idx, math.log2(before) - math.log2(max_cell)))
        cid_by_obs = {obs: cid for obs, cid in branches}
        for obs_key, child in node.branches:
            cid = cid_by_obs.get(obs_key)
            if cid is not None:
                walk(cid, child)

    walk(graph.b0, plan)
    if not records:
        return _no_surprise()
    best_index, best_bits = max(records, key=lambda r: (r[1], -r[0]))
    if best_bits <= 0.0:
        return _no_surprise()
    score = round(best_bits / math.log2(b0_size), 6)
    return Surprise(
        score, best_index, "belief-collapse", round(best_bits, 6), round(best_bits, 6), 0
    )


# --- public routing ------------------------------------------------------------------------


def strategy_of(
    puzzle: Puzzle,
    *,
    graph: search.ReachGraph | None = None,
    strong: epistemic.StrongSolution | None = None,
) -> StrategyResult:
    """The bounded-rational difficulty read, routed on observability (mirrors
    :func:`spie.quality.descriptors`). A non-empty ``initial_belief`` selects the hidden regime.
    A prebuilt ``graph`` / ``strong`` is reused when supplied, so a caller that already solved the
    puzzle pays nothing extra."""
    if puzzle.initial_belief:
        if strong is None:
            strong = epistemic.solve_strong(puzzle)
        return _strategy_hidden(strong)
    if graph is None:
        graph = search.explore(puzzle)
    return _strategy_fo(puzzle, graph)


def surprise_of(
    puzzle: Puzzle,
    *,
    graph: search.ReachGraph | None = None,
    strong: epistemic.StrongSolution | None = None,
) -> Surprise:
    """The myopic model's prediction error, routed on observability like :func:`strategy_of`:
    regret against the reachability oracle when fully observable, belief collapse when hidden."""
    if puzzle.initial_belief:
        if strong is None:
            strong = epistemic.solve_strong(puzzle)
        return _surprise_hidden(puzzle, strong)
    if graph is None:
        graph = search.explore(puzzle)
    return _surprise_fo(puzzle, graph)


__all__ = [
    "LOOKAHEAD",
    "MAX_STRATEGY_STEPS",
    "StrategyResult",
    "Surprise",
    "DEGENERATE_STRATEGY",
    "DEGENERATE_SURPRISE",
    "strategy_of",
    "surprise_of",
]
