"""Phase 5.4 -- LEARNING, part 1: a synthetic player and honestly-labeled telemetry.

The EVALUATION stage (:mod:`spie.strategy`) gives a *deterministic* human-like difficulty read.
LEARNING asks a harder question -- do the machine metrics actually *predict* how hard a puzzle
plays? -- and to answer it without fabricating human data, this module simulates a population of
**synthetic players**: a seeded, stochastic, deliberately noisier cousin of the strategy solver.

Honesty is the whole point, so it is enforced structurally:

* Every :class:`TelemetryRecord` is stamped ``synthetic=True`` and
  ``source="strategy-solver-simulation"`` and carries **no human-provenance field**. This is
  simulated effort, labelled as such; it is never presented as real playtest data.
* The synthetic player is a genuinely *distinct process* from the difficulty evaluator, not a
  re-encoding of it: each player draws its own myopic look-ahead, makes epsilon-greedy mistakes,
  asks for hints when it distrusts its heuristic, loses patience in dead ends, and restarts. These
  behavioural dynamics have no analogue in the structural difficulty formula, so calibrating that
  formula against this signal (:mod:`spie.calibrate`) is not circular -- and is honest only if it
  *generalises* to held-out puzzles.
* It is nonetheless fully **deterministic**: every player's randomness comes from a per-player
  seed derived by a stable (process-independent) hash of the puzzle id and the run's base seed,
  so a telemetry run is byte-reproducible -- the determinism discipline lifted to the player.

Two regimes mirror :func:`spie.strategy.strategy_of`. A fully-observable puzzle is *played*: a
noisy greedy DFS with chronological backtracking over the ``_live``-pruned reachability graph
(:mod:`spie.search`), where deeper, branchier, trap-heavy puzzles genuinely cost more steps,
backtracks, hints, and restarts. A hidden puzzle is *executed*: the player walks the certified
contingent plan, and its uncertainty (scaled by ``|B0|``) shows up as sensing-branch confusion --
paid hints and restarts -- so an information-rich plan costs more effort. Effort is a single
behavioural scalar (:func:`_effort`) aggregated per puzzle into an observed-difficulty signal.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

from . import epistemic, search
from . import expr as E
from .evaluate import Context, eval_bool
from .ir import Puzzle

# Population size and behavioural guards. A run simulates DEFAULT_PLAYERS independent players;
# each may restart up to MAX_RESTARTS times, and each attempt is step-bounded so an unsolvable or
# adversarial graph can never loop (mirroring search.DEFAULT_MAX_STATES's role).
DEFAULT_PLAYERS = 20
MAX_RESTARTS = 3

# Effort weights: the behavioural cost of each event in "step-equivalents". A dead-end retreat, a
# paid hint, and a full restart each cost progressively more than one forward move. Fixed and
# documented (provisional, like the quality folds); effort is a reported signal, not a certificate.
_W_STEP = 1
_W_BACKTRACK = 2
_W_HINT = 3
_W_RESTART = 8


@dataclass(frozen=True)
class TelemetryRecord:
    """One synthetic player's experience of one puzzle.

    ``solved`` is whether it reached the goal before exhausting its restarts/budget; ``steps`` is
    forward moves, ``backtracks`` dead-end retreats (always ``0`` in the hidden regime -- a strong
    plan never physically backtracks), ``hints_used`` oracle look-ups it paid for, ``restarts`` how
    often it abandoned an attempt and began again, and ``effort`` the behavioural scalar folding
    them together. ``synthetic``/``source`` are the honest provenance labels: this is simulated
    effort, never human data, and the record deliberately carries no field resembling one."""

    puzzle_id: str
    player_seed: int
    solved: bool
    steps: int
    backtracks: int
    hints_used: int
    restarts: int
    effort: int
    synthetic: bool = True
    source: str = "strategy-solver-simulation"


@dataclass(frozen=True)
class ObservedDifficulty:
    """A puzzle's telemetry aggregated over the synthetic population -- the *observed* difficulty
    signal LEARNING calibrates against. ``mean_effort`` is the headline; the solved fraction and
    per-event means are reported alongside it. All means rounded for byte-reproducibility."""

    puzzle_id: str
    players: int
    solved_fraction: float
    mean_effort: float
    mean_steps: float
    mean_backtracks: float
    mean_hints: float
    mean_restarts: float


def _player_seed(puzzle_id: str, index: int, base_seed: int) -> int:
    """A stable, process-independent seed for player ``index`` on ``puzzle_id``. Uses SHA-256 (not
    the salted built-in ``hash``, which varies per process) so the same ``(puzzle_id, index,
    base_seed)`` always yields the same seed -- the foundation of telemetry's
    byte-reproducibility."""
    digest = hashlib.sha256(f"{puzzle_id}|{base_seed}|{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _effort(steps: int, backtracks: int, hints: int, restarts: int) -> int:
    """Fold the behavioural event counts into one effort scalar (weighted sum, step-equivalents)."""
    return _W_STEP * steps + _W_BACKTRACK * backtracks + _W_HINT * hints + _W_RESTART * restarts


def _player_heuristic(puzzle: Puzzle, graph: search.ReachGraph, lookahead: int):
    """The synthetic player's own myopic heuristic ``h_L``: goal conjuncts unsatisfied at a node,
    minimised over ``lookahead`` edges. It deliberately mirrors the strategy solver's counting
    heuristic but is the *player's*, with its own per-player horizon -- and, like it, never consults
    :func:`spie.search.goal_distance` (that oracle backs only the paid hint, where the player buys
    ground truth)."""
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
        for _ in range(lookahead):
            nxt: set[int] = set()
            for u in frontier:
                for _action, w in graph.adj.get(u, ()):
                    if w not in seen:
                        seen.add(w)
                        nxt.add(w)
                        best = min(best, base_h(w))
            if not nxt:
                break
            frontier = nxt
        hl_cache[node] = best
        return best

    return hl


def _simulate_fo(
    puzzle: Puzzle, graph: search.ReachGraph, rng: random.Random
) -> tuple[bool, int, int, int, int]:
    """Simulate one noisy player on a fully-observable puzzle: greedy best-first DFS with
    chronological backtracking, epsilon-greedy mistakes, paid hints (the one oracle look-up), and
    patience-limited restarts. Returns ``(solved, steps, backtracks, hints, restarts)``."""
    if not (graph.initial_live and graph.goals):
        return False, 0, 0, 0, MAX_RESTARTS
    hl = _player_heuristic(puzzle, graph, rng.choice((1, 2, 3)))
    rd = search.goal_distance(graph)
    inf = len(graph.states)
    i0 = graph.index[graph.initial]
    epsilon = rng.uniform(0.05, 0.35)
    hint_prob = rng.uniform(0.15, 0.55)
    patience = rng.randint(2, 8)
    budget = max(16, 4 * len(graph.states))

    steps = backtracks = hints = restarts = 0
    solved = False
    for attempt in range(MAX_RESTARTS + 1):
        if attempt:
            restarts += 1
        visited = {i0}
        stack = [i0]
        attempt_bt = 0
        while stack:
            if steps + backtracks >= budget or attempt_bt > patience:
                break
            node = stack[-1]
            if node in graph.goals:
                solved = True
                break
            neigh = [(a, w) for a, w in graph.adj.get(node, ()) if w != node and w not in visited]
            if not neigh:
                stack.pop()
                backtracks += 1
                attempt_bt += 1
                continue
            roll = rng.random()
            if roll < epsilon:
                _, w = rng.choice(neigh)  # exploratory mistake
            elif roll < epsilon + hint_prob:
                _, w = min(neigh, key=lambda aw: (rd.get(aw[1], inf), aw[0], aw[1]))  # paid hint
                hints += 1
            else:
                _, w = min(neigh, key=lambda aw: (hl(aw[1]), aw[0], aw[1]))  # trust the heuristic
            visited.add(w)
            steps += 1
            stack.append(w)
        if solved:
            break
    return solved, steps, backtracks, hints, restarts


def _simulate_hidden(
    strong: object, b0_size: int, rng: random.Random
) -> tuple[bool, int, int, int, int]:
    """Simulate one noisy player *executing* a certified contingent plan. It walks a random
    root-to-leaf path; at each sensing branch its uncertainty (scaled by ``|B0|``) may confuse it
    into a paid hint, and too many confusions in one attempt cost a restart. A strong plan never
    physically backtracks, so ``backtracks`` is ``0``. Returns the same 5-tuple as
    :func:`_simulate_fo`."""
    plan = getattr(strong, "plan", None)
    if not getattr(strong, "solvable", False) or plan is None:
        return False, 0, 0, 0, MAX_RESTARTS
    if plan.is_leaf:
        return True, 0, 0, 0, 0
    epsilon = rng.uniform(0.05, 0.35)
    confusion = min(0.9, epsilon * (1.0 + math.log2(max(b0_size, 2))))
    patience = rng.randint(1, 4)

    steps = hints = restarts = 0
    solved = False
    for attempt in range(MAX_RESTARTS + 1):
        if attempt:
            restarts += 1
        node = plan
        confusions = 0
        aborted = False
        while not node.is_leaf:
            steps += 1
            branches = node.branches
            if len(branches) >= 2 and rng.random() < confusion:
                hints += 1
                confusions += 1
                if confusions > patience:
                    aborted = True
                    break
            _obs, node = rng.choice(branches)
        if not aborted:
            solved = True
            break
    return solved, steps, 0, hints, restarts


def simulate_player(
    puzzle: Puzzle,
    player_seed: int,
    *,
    graph: search.ReachGraph | None = None,
    strong: object | None = None,
) -> TelemetryRecord:
    """Simulate one synthetic player (identified by its stable ``player_seed``) on ``puzzle``,
    routing on observability like :func:`spie.strategy.strategy_of`. A prebuilt ``graph``/``strong``
    is reused when supplied, so a whole population shares one solve."""
    rng = random.Random(player_seed)
    if puzzle.initial_belief:
        if strong is None:
            strong = epistemic.solve_strong(puzzle)
        b0 = len(epistemic.build_initial_belief(puzzle))
        solved, steps, backtracks, hints, restarts = _simulate_hidden(strong, b0, rng)
    else:
        if graph is None:
            graph = search.explore(puzzle)
        solved, steps, backtracks, hints, restarts = _simulate_fo(puzzle, graph, rng)
    return TelemetryRecord(
        puzzle_id=puzzle.id,
        player_seed=player_seed,
        solved=solved,
        steps=steps,
        backtracks=backtracks,
        hints_used=hints,
        restarts=restarts,
        effort=_effort(steps, backtracks, hints, restarts),
    )


def simulate_puzzle(
    puzzle: Puzzle, players: int = DEFAULT_PLAYERS, base_seed: int = 0
) -> list[TelemetryRecord]:
    """Simulate a population of ``players`` synthetic players on ``puzzle``. The reachability graph
    (or strong solution) is built once and shared; each player gets a stable per-player seed, so the
    whole population is byte-reproducible for a fixed ``(puzzle, players, base_seed)``."""
    graph: search.ReachGraph | None = None
    strong: object | None = None
    if puzzle.initial_belief:
        strong = epistemic.solve_strong(puzzle)
    else:
        graph = search.explore(puzzle)
    return [
        simulate_player(puzzle, _player_seed(puzzle.id, i, base_seed), graph=graph, strong=strong)
        for i in range(players)
    ]


def observe(
    puzzle: Puzzle, players: int = DEFAULT_PLAYERS, base_seed: int = 0
) -> ObservedDifficulty:
    """Aggregate a puzzle's synthetic population into its observed-difficulty signal."""
    recs = simulate_puzzle(puzzle, players, base_seed)
    n = len(recs) or 1

    def mean(total: int) -> float:
        return round(total / n, 6)

    return ObservedDifficulty(
        puzzle_id=puzzle.id,
        players=len(recs),
        solved_fraction=mean(sum(1 for r in recs if r.solved)),
        mean_effort=mean(sum(r.effort for r in recs)),
        mean_steps=mean(sum(r.steps for r in recs)),
        mean_backtracks=mean(sum(r.backtracks for r in recs)),
        mean_hints=mean(sum(r.hints_used for r in recs)),
        mean_restarts=mean(sum(r.restarts for r in recs)),
    )


def collect(
    puzzles: list[Puzzle], players: int = DEFAULT_PLAYERS, base_seed: int = 0
) -> list[ObservedDifficulty]:
    """Observed difficulty for each puzzle, in the given order -- the LEARNING dataset's target."""
    return [observe(p, players, base_seed) for p in puzzles]


def record_to_json(r: TelemetryRecord) -> dict:
    """A plain-data view of one telemetry record, provenance labels included."""
    return {
        "puzzle_id": r.puzzle_id,
        "player_seed": r.player_seed,
        "solved": r.solved,
        "steps": r.steps,
        "backtracks": r.backtracks,
        "hints_used": r.hints_used,
        "restarts": r.restarts,
        "effort": r.effort,
        "synthetic": r.synthetic,
        "source": r.source,
    }


def observed_to_json(o: ObservedDifficulty) -> dict:
    """A plain-data view of a puzzle's aggregated observed difficulty."""
    return {
        "puzzle_id": o.puzzle_id,
        "players": o.players,
        "solved_fraction": o.solved_fraction,
        "mean_effort": o.mean_effort,
        "mean_steps": o.mean_steps,
        "mean_backtracks": o.mean_backtracks,
        "mean_hints": o.mean_hints,
        "mean_restarts": o.mean_restarts,
    }


__all__ = [
    "DEFAULT_PLAYERS",
    "MAX_RESTARTS",
    "TelemetryRecord",
    "ObservedDifficulty",
    "simulate_player",
    "simulate_puzzle",
    "observe",
    "collect",
    "record_to_json",
    "observed_to_json",
]
