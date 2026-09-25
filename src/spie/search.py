"""Explicit-state search — the second, independent solver (Phase 2, deliverable D1).

The roadmap's decision gate **G2** demands *two independent solving methods* whose
certificates agree. The Z3 backend (:mod:`spie.solver`) proves reachability symbolically,
by bounded model checking. This module proves the same facts *concretely*, by enumerating
the reachable state space with the deterministic interpreter's own semantics
(:func:`spie.evaluate.eval_bool` / :func:`spie.evaluate.apply_effects`). It shares **zero**
encoding code with Z3 — a genuinely different paradigm — so when the two agree on
solvability, minimal length, and uniqueness, the *whole* proof is cross-validated, not just
the single trace Z3 happened to report.

To agree with Z3 the search must prune exactly what Z3's constraints prune. Z3 asserts, at
every tick, that each variable stays within its declared domain and that every invariant
holds and the loss predicate does not. So a successor state here is **live** — worth
entering and expanding — only when it satisfies all three. This mirroring is the whole
correctness argument for cross-validation.

The reachable-state graph this builds does triple duty for the rest of Phase 2: its
structure powers the dead-state (trap) scan, its branching powers the difficulty proxy, and
Dijkstra over :attr:`~spie.ir.Action.cost` powers the shortcut gate.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, replace

from .evaluate import Context, apply_effects, eval_bool
from .ground import ground_all, path_cost
from .interpreter import domain_of, initial_state
from .ir import Puzzle
from .results import EQUIVALENCE, Solution, Uniqueness

SOLVER_NAME = "explicit-search"
SOLVER_VERSION = "1.0"

# Safety bound: the reachable set is finite (every variable is domain-bounded) but can be
# large for future puzzles, so exploration degrades gracefully rather than hanging.
DEFAULT_MAX_STATES = 100_000

State = tuple[int, ...]  # canonical state: variable values in declared order


def _var_keys(puzzle: Puzzle) -> tuple[str, ...]:
    return tuple(v.key for v in puzzle.variables)


def _to_tuple(state: dict[str, int], var_keys: tuple[str, ...]) -> State:
    return tuple(state[k] for k in var_keys)


def _to_dict(state: State, var_keys: tuple[str, ...]) -> dict[str, int]:
    return dict(zip(var_keys, state, strict=True))


def _live(puzzle: Puzzle, ctx: Context, domains: dict[str, tuple[int, int]],
          state: dict[str, int]) -> bool:
    """Would Z3 admit this state at a tick? True iff every variable is within its declared
    domain, every invariant holds, and the loss predicate does not. This is exactly the
    conjunction Z3 asserts per tick, so the two backends prune identically."""
    for key, (lo, hi) in domains.items():
        if not (lo <= state[key] <= hi):
            return False
    for inv in puzzle.objective.invariants:
        if not eval_bool(inv, state, ctx):
            return False
    if puzzle.objective.loss is not None and eval_bool(puzzle.objective.loss, state, ctx):
        return False
    return True


@dataclass
class ReachGraph:
    """The reachable state space of a puzzle, over *live* states only.

    Nodes are indices into ``states`` (canonical state tuples, discovery order). ``adj``
    maps a node to every live outgoing ``(action_name, target)`` edge — including edges back
    to already-seen states, so out-degree is the true count of legal moves (the branching
    the difficulty proxy reads). ``dist`` is BFS distance from the initial state; ``goals``
    are the goal-satisfying nodes. ``truncated`` is set if the ``max_states`` bound was hit,
    in which case trap/uniqueness conclusions drawn from the graph are not complete.
    """

    var_keys: tuple[str, ...]
    initial: State
    initial_live: bool
    states: list[State]
    index: dict[State, int]
    adj: dict[int, list[tuple[str, int]]]
    dist: dict[int, int]
    goals: set[int]
    truncated: bool
    max_states: int

    def out_degree(self, node: int) -> int:
        return len(self.adj.get(node, ()))

    def min_goal_dist(self) -> int | None:
        dists = [self.dist[g] for g in self.goals]
        return min(dists) if dists else None

    def traps(self) -> set[int]:
        """Reachable live states from which no goal is reachable — silent dead-ends.

        Computed by reverse reachability from the goal set over live edges; every node not
        reaching a goal is a trap. With no goals at all, every reachable state is a trap."""
        n = len(self.states)
        if not self.goals:
            return set(range(n))
        reverse: dict[int, list[int]] = {i: [] for i in range(n)}
        for u, outs in self.adj.items():
            for _, w in outs:
                reverse[w].append(u)
        seen = set(self.goals)
        stack = list(self.goals)
        while stack:
            node = stack.pop()
            for pred in reverse[node]:
                if pred not in seen:
                    seen.add(pred)
                    stack.append(pred)
        return set(range(n)) - seen


def explore(puzzle: Puzzle, max_states: int = DEFAULT_MAX_STATES) -> ReachGraph:
    """Breadth-first enumeration of the reachable live state space from the initial state.

    Every ground action whose precondition holds is applied; a successor is entered only if
    it is :func:`_live`. Non-live successors (domain/invariant/loss violations) are the
    states Z3 would prune, so they are dropped, never expanded. Bounded by ``max_states``.
    """
    ctx = Context.from_puzzle(puzzle)
    ground = ground_all(puzzle)
    var_keys = _var_keys(puzzle)
    domains = {v.key: domain_of(puzzle, v.key) for v in puzzle.variables}
    goal = puzzle.objective.goal

    init_dict = initial_state(puzzle)
    init = _to_tuple(init_dict, var_keys)

    states: list[State] = []
    index: dict[State, int] = {}
    adj: dict[int, list[tuple[str, int]]] = {}
    dist: dict[int, int] = {}
    goals: set[int] = set()

    if not _live(puzzle, ctx, domains, init_dict):
        return ReachGraph(var_keys, init, False, states, index, adj, dist, goals, False, max_states)

    def add(state: State) -> int:
        node = index.get(state)
        if node is None:
            node = len(states)
            states.append(state)
            index[state] = node
            adj[node] = []
        return node

    i0 = add(init)
    dist[i0] = 0
    if eval_bool(goal, init_dict, ctx):
        goals.add(i0)

    truncated = False
    queue = deque([i0])
    while queue:
        u = queue.popleft()
        u_dict = _to_dict(states[u], var_keys)
        for ga in ground:
            if not eval_bool(ga.precondition, u_dict, ctx):
                continue
            nxt_dict = apply_effects(ga.effects, u_dict, ctx)
            if not _live(puzzle, ctx, domains, nxt_dict):
                continue
            w_state = _to_tuple(nxt_dict, var_keys)
            is_new = w_state not in index
            if is_new and len(states) >= max_states:
                truncated = True
                continue
            w = add(w_state)
            adj[u].append((ga.name, w))
            if is_new:
                dist[w] = dist[u] + 1
                if eval_bool(goal, nxt_dict, ctx):
                    goals.add(w)
                queue.append(w)

    return ReachGraph(var_keys, init, True, states, index, adj, dist, goals, truncated, max_states)


def _reconstruct(parent: dict[int, tuple[int, str]], goal: int,
                 states: list[State]) -> tuple[list[str], tuple[State, ...]]:
    """Walk ``parent`` back from ``goal`` to the root, returning the forward action trace
    and the canonical state-path (init .. goal)."""
    trace: list[str] = []
    idxs: list[int] = [goal]
    cur = goal
    while cur in parent:
        prev, action = parent[cur]
        trace.append(action)
        idxs.append(prev)
        cur = prev
    trace.reverse()
    idxs.reverse()
    return trace, tuple(states[i] for i in idxs)


def solve_bfs(puzzle: Puzzle, max_states: int = DEFAULT_MAX_STATES) -> Solution:
    """Minimal-**length** solution via breadth-first search — the concrete mirror of the
    Z3 backend's minimal-horizon search. The first goal dequeued is at minimal distance."""
    graph = explore(puzzle, max_states)
    if not graph.initial_live or not graph.goals:
        return Solution(solvable=False, horizon=puzzle.objective.max_horizon)

    i0 = graph.index[graph.initial]
    parent: dict[int, tuple[int, str]] = {}
    seen = {i0}
    queue = deque([i0])
    found: int | None = None
    while queue:
        u = queue.popleft()
        if u in graph.goals:
            found = u
            break
        for action, w in graph.adj.get(u, ()):
            if w not in seen:
                seen.add(w)
                parent[w] = (u, action)
                queue.append(w)
    if found is None:
        return Solution(solvable=False, horizon=puzzle.objective.max_horizon)

    trace, state_path = _reconstruct(parent, found, graph.states)
    return Solution(
        solvable=True,
        horizon=len(trace),
        trace=trace,
        state_path=state_path,
        cost=path_cost(puzzle, trace),
    )


# The public "minimal-length" entry point, named to mirror ``solver.solve``.
solve = solve_bfs


def solve_min_cost(puzzle: Puzzle, max_states: int = DEFAULT_MAX_STATES) -> Solution:
    """Minimal-**cost** solution via Dijkstra over :attr:`~spie.ir.Action.cost`.

    Uses the same live reachable graph as everything else, so it prunes identically. Costs
    are non-negative, so Dijkstra is exact; ties are broken by a deterministic insertion
    sequence for reproducibility."""
    graph = explore(puzzle, max_states)
    if not graph.initial_live or not graph.goals:
        return Solution(solvable=False, horizon=puzzle.objective.max_horizon)

    cost_of = {g.name: g.cost for g in ground_all(puzzle)}
    i0 = graph.index[graph.initial]
    best = {i0: 0}
    parent: dict[int, tuple[int, str]] = {}
    visited: set[int] = set()
    seq = 0
    heap: list[tuple[int, int, int]] = [(0, 0, i0)]
    while heap:
        cost, _, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        if u in graph.goals:
            trace, state_path = _reconstruct(parent, u, graph.states)
            return Solution(True, len(trace), trace, state_path, cost)
        for action, w in graph.adj.get(u, ()):
            new_cost = cost + cost_of[action]
            if w not in best or new_cost < best[w]:
                best[w] = new_cost
                parent[w] = (u, action)
                seq += 1
                heapq.heappush(heap, (new_cost, seq, w))
    return Solution(solvable=False, horizon=puzzle.objective.max_horizon)


def _enumerate_shortest_state_paths(graph: ReachGraph, limit: int) -> list[tuple[int, ...]]:
    """Distinct shortest state-paths from the initial state to any goal, up to ``limit``.

    Follows only shortest-path-DAG edges (``dist[w] == dist[u] + 1``). Two parallel edges
    (different actions, same target) collapse to one state-path, so results are deduped by
    node sequence — the same equivalence the Z3 uniqueness check uses. Stops early once
    ``limit`` distinct paths are found, which is all a uniqueness verdict needs."""
    d_min = graph.min_goal_dist()
    if d_min is None:
        return []
    i0 = graph.index[graph.initial]
    results: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    path: list[int] = [i0]

    def dfs(u: int) -> None:
        if len(results) >= limit:
            return
        if len(path) - 1 == d_min:
            if u in graph.goals:
                key = tuple(path)
                if key not in seen:
                    seen.add(key)
                    results.append(key)
            return
        for _, w in graph.adj.get(u, ()):
            if graph.dist.get(w) == graph.dist[u] + 1:
                path.append(w)
                dfs(w)
                path.pop()
                if len(results) >= limit:
                    return

    dfs(i0)
    return results


def _trace_for_path(graph: ReachGraph, idx_path: tuple[int, ...]) -> list[str]:
    """Any concrete action trace realizing a node sequence: the first live edge per step."""
    trace: list[str] = []
    for a, b in zip(idx_path, idx_path[1:], strict=False):
        for action, w in graph.adj.get(a, ()):
            if w == b:
                trace.append(action)
                break
    return trace


def check_uniqueness(puzzle: Puzzle, solution: Solution | None = None,
                     max_states: int = DEFAULT_MAX_STATES) -> Uniqueness:
    """Decide uniqueness by *enumeration*: count distinct shortest state-paths to the goal.

    Mirrors :func:`spie.solver.check_uniqueness` exactly — same equivalence relation, same
    verdict shape — but reaches it concretely instead of by blocking-and-re-solving. Two or
    more distinct minimal state-paths ⇒ not unique, with a witness trace for one that
    differs from ``solution``."""
    graph = explore(puzzle, max_states)
    if not graph.initial_live or not graph.goals:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)

    paths = _enumerate_shortest_state_paths(graph, limit=2)
    if len(paths) <= 1:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)

    primary = solution.state_path if (solution and solution.state_path) else None
    for candidate in paths:
        state_path = tuple(graph.states[i] for i in candidate)
        if primary is None or state_path != primary:
            return Uniqueness(
                unique=False, equivalence=EQUIVALENCE, witness=_trace_for_path(graph, candidate)
            )
    return Uniqueness(
        unique=False, equivalence=EQUIVALENCE, witness=_trace_for_path(graph, paths[1])
    )


def goal_distance(graph: ReachGraph) -> dict[int, int]:
    """Min number of live edges from each node to the nearest goal (reverse BFS from goals).

    A node ``u`` lies on some *shortest* solution iff ``dist[u] + goal_distance[u]`` equals
    the minimal goal distance from the initial state — the standard shortest-path-DAG test.
    """
    reverse: dict[int, list[int]] = {i: [] for i in range(len(graph.states))}
    for u, outs in graph.adj.items():
        for _, w in outs:
            reverse[w].append(u)
    rd: dict[int, int] = {g: 0 for g in graph.goals}
    queue = deque(graph.goals)
    while queue:
        node = queue.popleft()
        for pred in reverse[node]:
            if pred not in rd:
                rd[pred] = rd[node] + 1
                queue.append(pred)
    return rd


def canonical_solution(puzzle: Puzzle, max_states: int = DEFAULT_MAX_STATES) -> Solution:
    """The *reproducible* minimal solution: the lexicographically-smallest action trace among
    all minimal-length solutions.

    A puzzle can have several equally-minimal solutions (the non-unique case), and a solver's
    model merely names *one* of them — arbitrarily, and not always the same one across runs.
    Recording that raw model makes a certificate non-reproducible. This instead returns a
    solution determined by the puzzle alone: walk the shortest-path DAG greedily, always
    taking the lexicographically-least action that still completes a shortest path to a goal.
    Because the earliest action dominates lexicographic order, greedy selection yields the
    global minimum, so certificates stay byte-identical even for non-unique puzzles.
    """
    graph = explore(puzzle, max_states)
    if not graph.initial_live or not graph.goals:
        return Solution(solvable=False, horizon=puzzle.objective.max_horizon)
    d = graph.min_goal_dist()
    rd = goal_distance(graph)
    u = graph.index[graph.initial]
    trace: list[str] = []
    idxs: list[int] = [u]
    while u not in graph.goals:
        k = graph.dist[u]
        # Edges that advance exactly one step along a shortest path to a goal.
        candidates = [
            (action, w)
            for action, w in graph.adj.get(u, ())
            if graph.dist.get(w) == k + 1 and w in rd and k + 1 + rd[w] == d
        ]
        action, u = min(candidates)  # lexicographic by (action name, then node index)
        trace.append(action)
        idxs.append(u)
    state_path = tuple(graph.states[i] for i in idxs)
    return Solution(True, len(trace), trace, state_path, path_cost(puzzle, trace))


# --- ablation: the shared "load-bearing element" notion ------------------------------


def _drop(seq: tuple, i: int) -> tuple:
    return seq[:i] + seq[i + 1:]


def signature(puzzle: Puzzle) -> tuple:
    """A behavioural fingerprint of a puzzle over its reachable state space.

    Two puzzles with equal signatures are indistinguishable to every reachability-based
    check, so an element whose removal leaves the signature unchanged has no measurable
    function. It folds in solvability, minimal length, minimal cost, uniqueness, and the
    shape of the reachable graph (state / trap / goal counts) — so an element that only
    affects, say, the set of reachable trap states (a loss predicate) still registers.

    This is the single source of the minimality notion, shared by the verification
    minimality gate and the elegance descriptor, so the two can never drift apart.
    """
    graph = explore(puzzle)
    solvable = graph.initial_live and bool(graph.goals)
    if not solvable:
        return (False, -1, -1, True, len(graph.states), len(graph.traps()), len(graph.goals))
    return (
        True,
        graph.min_goal_dist(),
        solve_min_cost(puzzle).cost,
        check_uniqueness(puzzle).unique,
        len(graph.states),
        len(graph.traps()),
        len(graph.goals),
    )


def ablations(puzzle: Puzzle):
    """Yield ``(label, variant)`` for each structurally-removable element — one action,
    edge, invariant, or the loss predicate dropped. An element is *load-bearing* iff
    :func:`signature` differs between ``puzzle`` and the variant that omits it."""
    for i, a in enumerate(puzzle.actions):
        yield f"action {a.name!r}", replace(puzzle, actions=_drop(puzzle.actions, i))
    for i, e in enumerate(puzzle.edges):
        yield f"edge {e[0]}->{e[1]}", replace(puzzle, edges=_drop(puzzle.edges, i))
    obj = puzzle.objective
    for i in range(len(obj.invariants)):
        newobj = replace(obj, invariants=_drop(obj.invariants, i))
        yield f"invariant #{i}", replace(puzzle, objective=newobj)
    if obj.loss is not None:
        yield "loss predicate", replace(puzzle, objective=replace(obj, loss=None))


def solver_version() -> str:
    return SOLVER_VERSION


__all__ = [
    "SOLVER_NAME",
    "SOLVER_VERSION",
    "solver_version",
    "DEFAULT_MAX_STATES",
    "State",
    "ReachGraph",
    "explore",
    "solve",
    "solve_bfs",
    "solve_min_cost",
    "canonical_solution",
    "check_uniqueness",
    "goal_distance",
    "signature",
    "ablations",
]
