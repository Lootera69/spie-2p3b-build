"""The machine quality vector (Phase 2, D4): difficulty, novelty, elegance, fairness.

MAP-Elites (a later phase) will use these descriptors as niche axes and for ranking, so they
must be a *deterministic* function of the puzzle — the discipline the determinism gate
enforces on certificates. Every proxy here is computed from the explicit-state reachability
graph (:mod:`spie.search`) or, for a puzzle with hidden state, the belief-space solver
(:mod:`spie.epistemic`) and the certified contingent plan — both pure functions of the puzzle.

The descriptors branch on :attr:`~spie.ir.Puzzle.initial_belief` exactly as
:func:`spie.certificate.certify` does: a fully-observable puzzle keeps the Phase-2 concrete
path unchanged (and its epistemic proxies vanish to their degenerate values, so its band and
novelty are byte-identical to before), while a puzzle with hidden state is measured through the
contingent plan — belief size ``|B0|``, sensing count, plan branching, depth spread, and the
information gain of the branches.

A deliberate omission: Z3's decision/conflict statistics, floated in the roadmap as a
secondary difficulty signal, are *not* used. They vary with solver internals and are not
guaranteed stable across runs, which would make the vector non-reproducible and unfit as a
niche coordinate. Difficulty is therefore read entirely from the concrete/belief search.

Fairness is no longer a proxy. The Phase-3 information layer lets us *prove* it: a certified
contingent plan is uniform (no-clairvoyance) by construction, so :func:`_fairness` replays the
plan through :func:`spie.conformance.check_plan_conformance` and reports the audited property
rather than the old ``1 - trap_density`` estimate.

The numeric folds (the 1-5 difficulty band, the elegance score) are transparent, monotone,
and explicitly *provisional* — the roadmap calls for human calibration much later. What is
committed to now is the set of proxies and their determinism, not the exact constants.
Surprise and a human-like difficulty read are no longer deferred: a bounded-rational strategy
solver (:mod:`spie.strategy`) supplies both, as deterministic functions of the puzzle. They are
*reported* descriptors — surprise is deliberately kept out of the MAP-Elites fitness (rewarding
deceptiveness there would invite trap-spam), so their addition perturbs no niche, archive, or
certificate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import conformance, epistemic, fingerprint, search, strategy
from .examples_src import BUILDERS
from .fingerprint import Fingerprint
from .ir import Puzzle
from .results import Plan
from .search import ReachGraph
from .serialize import dumps, puzzle_to_json


@dataclass(frozen=True)
class Difficulty:
    """Search-derived difficulty proxies and the provisional 1-5 band they fold into.

    The last five fields are the Phase-3 epistemic proxies. They take their degenerate values
    (``belief_count=1``, ``sensing_actions=0``, ``plan_branching=1``, ``depth_spread=0``,
    ``information_gain=0.0``) on a fully-observable puzzle, so ``raw``/``band`` there are
    byte-identical to Phase 2; a puzzle with hidden state gets real values read from its
    certified contingent plan:

    * ``belief_count``    — ``|B0|``, the number of worlds the player cannot initially rule out.
    * ``sensing_actions`` — how many actions declare a ``senses`` set (the sensing budget).
    * ``plan_branching``  — the plan's maximum observation-branch factor (``1`` = linear).
    * ``depth_spread``    — worst-case minus best-case plan depth (how uneven contingencies are).
    * ``information_gain``— ``log2(leaf_count)``: bits of hidden state the plan resolves."""

    band: int
    depth: int
    reachable_states: int
    mean_branching: float
    max_branching: int
    free_choices: int
    forced_steps: int
    trap_density: float
    raw: float
    belief_count: int = 1
    sensing_actions: int = 0
    plan_branching: int = 1
    depth_spread: int = 0
    information_gain: float = 0.0


@dataclass(frozen=True)
class Novelty:
    """Distance to the nearest corpus neighbour (``[0, 1]``) and that neighbour's id."""

    score: float
    nearest_id: str | None


@dataclass(frozen=True)
class Elegance:
    """Compactness and minimality proxies; ``score`` rewards few, all-load-bearing rules."""

    score: float
    rule_count: int
    description_length: int
    minimality_ratio: float


@dataclass(frozen=True)
class Fairness:
    """The fairness verdict — a *proven* property, not a proxy.

    ``uniform`` is the theorem the Phase-3 information layer lets us audit: the certified
    contingent plan branches only on observed history (no-clairvoyance), verified by replaying
    it through the interpreter over every world of ``B0``. ``score`` is ``1.0`` exactly when the
    plan is uniform and reaches the goal on all worlds, ``0.0`` otherwise. ``partial`` is now
    always ``False`` — fairness is decided, not estimated."""

    score: float
    uniform: bool
    partial: bool
    note: str


# Degenerate strategy/surprise singletons, reused as the additive ``QualityVector`` defaults so a
# vector's shape is unchanged and a trivial puzzle reads the no-effort / no-surprise values. Named
# at module scope (not referenced as ``strategy.`` inside the class body, where the field named
# ``strategy`` would shadow the module).
_DEFAULT_STRATEGY = strategy.DEGENERATE_STRATEGY
_DEFAULT_SURPRISE = strategy.DEGENERATE_SURPRISE


@dataclass(frozen=True)
class QualityVector:
    """The full quality vector for one puzzle — the descriptors MAP-Elites will consume.

    ``strategy`` and ``surprise`` are the Phase-5 EVALUATION additions from the bounded-rational
    solver (:mod:`spie.strategy`): a human-like difficulty read and the myopic model's prediction
    error at the puzzle's pivotal moment. They are reported alongside the structural descriptors
    but, unlike ``difficulty``, do **not** drive niches or fitness (see the module docstring)."""

    puzzle_id: str
    solvable: bool
    difficulty: Difficulty
    novelty: Novelty
    elegance: Elegance
    fairness: Fairness
    strategy: strategy.StrategyResult = _DEFAULT_STRATEGY
    surprise: strategy.Surprise = _DEFAULT_SURPRISE


def _sensing_count(puzzle: Puzzle) -> int:
    """How many of the puzzle's actions declare a non-empty ``senses`` set."""
    return sum(1 for a in puzzle.actions if a.senses)


def _difficulty(puzzle: Puzzle, graph: ReachGraph) -> Difficulty:
    """The concrete (fully-observable) difficulty. The epistemic proxies are degenerate here
    (``|B0|=1``, no genuine branching, no depth spread, no information to gain), so ``raw`` and
    ``band`` are byte-identical to Phase 2 — the reduction anchor for the difficulty band."""
    sensing = _sensing_count(puzzle)
    n = len(graph.states)
    solvable = graph.initial_live and bool(graph.goals)
    if not solvable or n == 0:
        return Difficulty(1, 0, n, 0.0, 0, 0, 0, 0.0, 0.0, sensing_actions=sensing)

    degrees = [graph.out_degree(i) for i in range(n)]
    mean_branching = round(sum(degrees) / n, 6)
    max_branching = max(degrees)
    trap_density = round(len(graph.traps()) / n, 6)

    # Classify each step of the *canonical* solution (the one the certificate records) as
    # forced (a single action keeps us on a shortest path) or free (several do): the count
    # of genuine decision points, not mere branching.
    depth = graph.min_goal_dist()
    rd = search.goal_distance(graph)
    node_path = [graph.index[s] for s in search.canonical_solution(puzzle).state_path]
    free = forced = 0
    for u in node_path[:-1]:
        k = graph.dist[u]
        advancing = {
            w
            for _, w in graph.adj.get(u, ())
            if graph.dist.get(w) == k + 1 and w in rd and k + 1 + rd[w] == depth
        }
        if len(advancing) > 1:
            free += 1
        else:
            forced += 1

    # Epistemic terms vanish for a fully-observable puzzle, so this fold reduces exactly to the
    # Phase-2 formula (round(x + 0.0, 6) == round(x, 6)).
    depth_spread = 0
    information_gain = 0.0
    raw = round(
        depth
        + 2.0 * free
        + 1.5 * (max_branching - 1 if max_branching > 1 else 0)
        + 3.0 * trap_density
        + 2.0 * depth_spread
        + information_gain,
        6,
    )
    band = 1 + min(4, int(raw // 4))  # provisional cut points, pending human calibration
    return Difficulty(
        band, depth, n, mean_branching, max_branching, free, forced, trap_density, raw,
        belief_count=1, sensing_actions=sensing, plan_branching=1,
        depth_spread=depth_spread, information_gain=information_gain,
    )


def _plan_branch_stats(plan: Plan) -> tuple[int, int, int, int]:
    """Walk a contingent plan and count ``(branching_nodes, single_nodes, total_branches,
    internal_nodes)`` — a branching node has >=2 observation outcomes (a genuine decision),
    a single node exactly one (a forced continuation). Used to lift the free/forced-choice and
    mean-branching difficulty proxies from a linear trace to a policy tree."""
    branching = single = total = internal = 0
    stack = [plan]
    while stack:
        node = stack.pop()
        if node.is_leaf:
            continue
        internal += 1
        b = len(node.branches)
        total += b
        if b >= 2:
            branching += 1
        else:
            single += 1
        stack.extend(child for _, child in node.branches)
    return branching, single, total, internal


def _epistemic_difficulty(puzzle: Puzzle, strong: epistemic.StrongSolution) -> Difficulty:
    """Difficulty of a puzzle with hidden state, read from its certified contingent plan.

    The plan-shape metrics replace their linear-trace analogues: free choices become genuine
    sensing branches, mean/max branching are measured over the plan's internal nodes, and the
    fold gains ``2*depth_spread + information_gain`` so uneven, information-rich contingencies
    band higher. ``trap_density`` is ``0`` by construction — a strong plan provably reaches the
    goal without ``loss`` on every world."""
    belief_count = len(epistemic.build_initial_belief(puzzle))
    sensing = _sensing_count(puzzle)
    plan = strong.plan
    if not strong.solvable or plan is None:
        return Difficulty(
            1, 0, strong.belief_count, 0.0, 0, 0, 0, 0.0, 0.0,
            belief_count=belief_count, sensing_actions=sensing, plan_branching=0,
        )

    depth = plan.depth()
    plan_branching = plan.branch_factor()
    depth_spread = depth - plan.min_depth()
    information_gain = round(math.log2(plan.leaf_count()), 6)
    branching, single, total, internal = _plan_branch_stats(plan)
    mean_branching = round(total / internal, 6) if internal else 0.0
    trap_density = 0.0

    raw = round(
        depth
        + 2.0 * branching
        + 1.5 * (plan_branching - 1 if plan_branching > 1 else 0)
        + 3.0 * trap_density
        + 2.0 * depth_spread
        + information_gain,
        6,
    )
    band = 1 + min(4, int(raw // 4))
    return Difficulty(
        band, depth, strong.belief_count, mean_branching, plan_branching, branching, single,
        trap_density, raw, belief_count=belief_count, sensing_actions=sensing,
        plan_branching=plan_branching, depth_spread=depth_spread,
        information_gain=information_gain,
    )


def _elegance(puzzle: Puzzle) -> Elegance:
    obj = puzzle.objective
    rule_count = len(puzzle.actions) + len(obj.invariants) + (1 if obj.loss is not None else 0)
    description_length = len(dumps(puzzle_to_json(puzzle)))

    variants = list(search.ablations(puzzle))
    if not variants:
        minimality_ratio = 1.0
    else:
        baseline = search.signature(puzzle)
        load_bearing = sum(1 for _, v in variants if search.signature(v) != baseline)
        minimality_ratio = round(load_bearing / len(variants), 6)

    # Provisional, monotone: full minimality is ideal, lightly penalised by rule count.
    score = round(minimality_ratio / (1.0 + 0.05 * rule_count), 6)
    return Elegance(score, rule_count, description_length, minimality_ratio)


def _fairness(puzzle: Puzzle, plan: Plan | None) -> Fairness:
    """Audit fairness as a theorem: replay the certified contingent ``plan`` over every world
    of ``B0`` and confirm it is *uniform* (decisions depend only on observed history) and
    reaches the goal on all worlds. Certified plans are fair by construction, so this confirms
    the property rather than estimating it — the Phase-3 replacement for the old
    ``1 - trap_density`` proxy. On a fully-observable puzzle ``B0`` is a singleton and the
    audit reduces to a single clean replay (``uniform`` trivially holds)."""
    pc = conformance.check_plan_conformance(puzzle, plan)
    fair = pc.ok and pc.uniform
    return Fairness(
        score=1.0 if fair else 0.0,
        uniform=pc.uniform,
        partial=False,
        note=(
            f"audited: plan is {'uniform' if pc.uniform else 'NON-UNIFORM'} and "
            f"{'reaches' if pc.reached_goal_all else 'does NOT reach'} the goal on all "
            f"{len(pc.world_replays)} B0 world(s) — {pc.detail}"
        ),
    )


def descriptors(
    puzzle: Puzzle, corpus: list[tuple[str, Fingerprint]] | None = None
) -> QualityVector:
    """The quality vector for ``puzzle``. ``corpus`` is the novelty neighbourhood; it
    defaults to the built-in example corpus. Deterministic for a fixed puzzle and corpus.

    The routing mirrors :func:`spie.certificate.certify`: a puzzle with hidden state
    (:attr:`~spie.ir.Puzzle.initial_belief` non-empty) is measured through the belief-space
    solver and its contingent plan; a fully-observable puzzle keeps the concrete path, so its
    difficulty band and novelty are unchanged from Phase 2."""
    if corpus is None:
        corpus = fingerprint.corpus_fingerprints([b() for b in BUILDERS])
    score, nearest_id = fingerprint.nearest(puzzle, corpus)
    if puzzle.initial_belief:
        strong = epistemic.solve_strong(puzzle)
        solvable = strong.solvable
        difficulty = _epistemic_difficulty(puzzle, strong)
        fairness = _fairness(puzzle, strong.plan)
        strategy_result = strategy.strategy_of(puzzle, strong=strong)
        surprise = strategy.surprise_of(puzzle, strong=strong)
    else:
        graph = search.explore(puzzle)
        solvable = graph.initial_live and bool(graph.goals)
        difficulty = _difficulty(puzzle, graph)
        fairness = _fairness(puzzle, epistemic.canonical_plan(puzzle))
        strategy_result = strategy.strategy_of(puzzle, graph=graph)
        surprise = strategy.surprise_of(puzzle, graph=graph)
    return QualityVector(
        puzzle_id=puzzle.id,
        solvable=solvable,
        difficulty=difficulty,
        novelty=Novelty(round(score, 6), nearest_id),
        elegance=_elegance(puzzle),
        fairness=fairness,
        strategy=strategy_result,
        surprise=surprise,
    )


def quality_to_json(q: QualityVector) -> dict:
    """A plain-data view for canonical serialization / CLI output."""
    return {
        "puzzle_id": q.puzzle_id,
        "solvable": q.solvable,
        "difficulty": {
            "band": q.difficulty.band,
            "depth": q.difficulty.depth,
            "reachable_states": q.difficulty.reachable_states,
            "mean_branching": q.difficulty.mean_branching,
            "max_branching": q.difficulty.max_branching,
            "free_choices": q.difficulty.free_choices,
            "forced_steps": q.difficulty.forced_steps,
            "trap_density": q.difficulty.trap_density,
            "raw": q.difficulty.raw,
            "belief_count": q.difficulty.belief_count,
            "sensing_actions": q.difficulty.sensing_actions,
            "plan_branching": q.difficulty.plan_branching,
            "depth_spread": q.difficulty.depth_spread,
            "information_gain": q.difficulty.information_gain,
        },
        "novelty": {"score": q.novelty.score, "nearest_id": q.novelty.nearest_id},
        "elegance": {
            "score": q.elegance.score,
            "rule_count": q.elegance.rule_count,
            "description_length": q.elegance.description_length,
            "minimality_ratio": q.elegance.minimality_ratio,
        },
        "fairness": {
            "score": q.fairness.score,
            "uniform": q.fairness.uniform,
            "partial": q.fairness.partial,
            "note": q.fairness.note,
        },
        "strategy": {
            "solvable": q.strategy.solvable,
            "inference_depth": q.strategy.inference_depth,
            "branching_faced": q.strategy.branching_faced,
            "backtracks": q.strategy.backtracks,
            "memory_load": q.strategy.memory_load,
            "steps_taken": q.strategy.steps_taken,
            "complete": q.strategy.complete,
        },
        "surprise": {
            "score": q.surprise.score,
            "pivot_index": q.surprise.pivot_index,
            "pivot_kind": q.surprise.pivot_kind,
            "prediction_error": q.surprise.prediction_error,
            "bits_resolved": q.surprise.bits_resolved,
            "regret_steps": q.surprise.regret_steps,
        },
    }


__all__ = [
    "Difficulty",
    "Novelty",
    "Elegance",
    "Fairness",
    "QualityVector",
    "descriptors",
    "quality_to_json",
]
