"""Chance puzzles — an exact-rational success probability over a random initial state (Item 4).

Item 4 lets a puzzle's *initial* state be drawn from an independent, per-hidden-variable
distribution of exact :class:`~fractions.Fraction` weights (:attr:`~spie.ir.Puzzle.initial_dist`);
everything downstream stays deterministic. The engine then certifies the **exact optimal expected
success probability** ``P`` — the greatest weight of initial worlds a single contingent plan can
win under partial observability, choosing only actions legal in *every* world it still holds
possible (no clairvoyance). No float ever appears: ``P`` is an exact ``Fraction``.

The existing contingent layer (:mod:`spie.epistemic`) is **strong / all-or-nothing** — it returns
a plan only when *every* live world is jointly winnable — so it cannot express a meaningful
``P < 1``. This module adds the missing **weight-aware best-effort** planner and certifies ``P``
with three exact, independent cross-checks (a discrepancy is surfaced structurally, never smoothed):

* **Method A′** — a weighted belief DP over nodes that *keep initial-world provenance* (a node is a
  ``frozenset`` of ``(initial_world, current_state)`` pairs, so the weight of the initial worlds it
  carries is always recoverable). Exact horizon-bounded value iteration computes
  ``V(node) = max(stop-now weight, best legal action's Σ over observed successors)``; ``P_A =
  V(B0)`` and a canonical (lexicographically-least, progress-preferring) plan is read off it.
* **Method B′** — the certified plan is replayed per initial world through the *reference
  interpreter* (:func:`spie.conformance.check_plan_conformance`); ``P_B`` is the summed weight of
  the worlds whose replay reaches the goal. ``P_A == P_B`` is asserted exactly (a top-down
  interpreter tally vs a bottom-up evaluator DP).
* **Upper bound U** — for each initial world the existing three-solver reachability cross-check
  (:func:`spie.crosscheck.cross_solve`, Z3 ∧ explicit-search ∧ clingo) decides whether that world
  is winnable *with full knowledge*; ``U`` is their summed weight. ``P <= U`` is asserted (you
  cannot win a world you could not win even if you knew it), and when ``P == U`` the optimum is
  independently sandwiched.

The whole module is stdlib-only (``fractions`` + ``itertools``), deterministic, and inert unless
:attr:`~spie.ir.Puzzle.initial_dist` is non-empty — so every deterministic and every existing
epistemic puzzle certifies byte-for-byte unchanged.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from fractions import Fraction

from . import augment
from .conformance import check_plan_conformance
from .crosscheck import cross_solve
from .evaluate import Context, apply_effects, eval_bool
from .ground import GroundAction, ground_all
from .interpreter import domain_of, initial_state
from .ir import Observability, Puzzle, WorldReplay
from .results import Plan

SOLVER_NAME = "chance-belief-dp"
SOLVER_VERSION = "1.0"

DEFAULT_MAX_NODES = 100_000
"""Belief-node exploration cap, mirroring :data:`spie.epistemic.DEFAULT_MAX_BELIEFS`. Reaching it
sets ``truncated=True`` (a recorded discrepancy), never a silently-wrong probability."""

# A world/current state is the variable vector in declared (desugared) order; a belief node keeps
# each initial world's provenance so its exact weight is always recoverable.
WorldState = tuple[int, ...]
BeliefNode = frozenset[tuple[WorldState, WorldState]]


def solver_version() -> str:
    """The Method-A′ planner version stamped into the certificate's solver evidence."""
    return SOLVER_VERSION


@dataclass(frozen=True)
class ChanceSolution:
    """Method A′'s verdict: the exact optimal expected success probability ``P`` (an exact
    :class:`~fractions.Fraction`), the canonical contingent plan that achieves it, how many live
    initial worlds ``B0`` held, and whether the node cap forced early truncation."""

    probability: Fraction
    plan: Plan
    world_count: int
    truncated: bool


@dataclass(frozen=True)
class ChanceCrossResult:
    """The three-way cross-check of ``P``: the belief-DP value ``probability`` (P_A), the
    per-world reference-replay tally ``probability_replay`` (P_B), and the reachability
    ``upper_bound`` (U). ``agree`` is True iff ``P_A == P_B``, ``P <= U``, the plan is uniform,
    nothing truncated, and the reachability solvers themselves agreed; every failure is spelled
    out in ``discrepancies`` (never smoothed)."""

    agree: bool
    probability: Fraction
    probability_replay: Fraction
    upper_bound: Fraction
    plan: Plan
    world_replays: tuple[WorldReplay, ...]
    uniform: bool
    world_count: int
    truncated: bool
    reachability_disagreement: bool
    discrepancies: tuple[str, ...]


def _weight_maps(
    puzzle: Puzzle, hidden_keys: list[str]
) -> dict[str, dict[int, Fraction]]:
    """Per-hidden-variable ``value -> exact weight`` map. A variable with an explicit
    :attr:`~spie.ir.Puzzle.initial_dist` entry uses those weights; one without (e.g. a singleton
    aux variable introduced by :func:`spie.augment.desugar`) falls back to a uniform
    ``Fraction(1, |support|)`` — so a lone value carries weight exactly ``1`` and adds no
    randomness."""
    maps: dict[str, dict[int, Fraction]] = {}
    for key in hidden_keys:
        support = puzzle.initial_belief[key]
        if key in puzzle.initial_dist:
            maps[key] = {value: weight for value, weight in puzzle.initial_dist[key]}
        else:
            uniform = Fraction(1, len(support)) if support else Fraction(0)
            maps[key] = {value: uniform for value in support}
    return maps


def _observable_keys(puzzle: Puzzle) -> tuple[str, ...]:
    """Variables observed every tick without sensing — the ``VISIBLE`` ones, sorted. Reimplemented
    here (not imported) so the chance layer depends on no solver; identical to the private helper
    :func:`spie.conformance._observable_keys` the reference replay uses, so obs-keys line up."""
    return tuple(sorted(v.key for v in puzzle.variables if v.obs is Observability.VISIBLE))


def _initial_live(
    puzzle: Puzzle,
    ctx: Context,
    domains: dict[str, tuple[int, int]],
    state: dict[str, int],
) -> bool:
    """Would the runtime admit this world at the start? Every variable in range, every invariant
    satisfied, ``loss`` not already triggered — byte-identical to :func:`spie.conformance._live`,
    so the DP's ``B0`` is exactly the belief the reference replay enumerates."""
    for key, (lo, hi) in domains.items():
        if not (lo <= state[key] <= hi):
            return False
    for inv in puzzle.objective.invariants:
        if not eval_bool(inv, state, ctx):
            return False
    loss = puzzle.objective.loss
    return not (loss is not None and eval_bool(loss, state, ctx))


def _world_weights(puzzle: Puzzle) -> dict[WorldState, Fraction]:
    """Exact weight of every *live* initial world of an already-desugared puzzle: the product of
    its per-hidden-variable weights (the variables are independent). Live worlds only, keyed by the
    full variable vector in declared order — the identical key the reference replay records."""
    ctx = Context.from_puzzle(puzzle)
    domains = {v.key: domain_of(puzzle, v.key) for v in puzzle.variables}
    var_keys = [v.key for v in puzzle.variables]
    init = initial_state(puzzle)
    hidden_keys = sorted(puzzle.initial_belief.keys())
    supports = [puzzle.initial_belief[k] for k in hidden_keys]
    maps = _weight_maps(puzzle, hidden_keys)

    weights: dict[WorldState, Fraction] = {}
    for combo in itertools.product(*supports):
        world = dict(init)
        weight = Fraction(1)
        for key, value in zip(hidden_keys, combo, strict=True):
            world[key] = value
            weight *= maps[key][value]
        if not _initial_live(puzzle, ctx, domains, world):
            continue
        weights[tuple(world[k] for k in var_keys)] = weight
    return weights


def initial_world_weights(puzzle: Puzzle) -> dict[WorldState, Fraction]:
    """The **sole source of world mass** (Item 4): the exact weight of every live initial world.
    Desugars first so history-observability puzzles present their real variable vector, then defers
    to :func:`_world_weights`. A future *joint* distribution would change only this helper."""
    return _world_weights(augment.desugar(puzzle))


class _ChanceDP:
    """Exact horizon-bounded value iteration over provenance-keeping belief nodes (Method A′).

    A node is a ``frozenset`` of ``(initial_world, current_state)`` pairs; ``value(node, h)`` is the
    greatest initial-world weight winnable from it within ``h`` remaining action steps, choosing
    only actions legal in *every* member (precondition holds and the successor stays live) — no
    clairvoyance. Value and the canonical plan are both exact and RNG-free."""

    def __init__(
        self,
        puzzle: Puzzle,
        ctx: Context,
        var_keys: list[str],
        obs_base: tuple[str, ...],
        actions: list[GroundAction],
        weights: dict[WorldState, Fraction],
        max_nodes: int,
    ) -> None:
        self.puzzle = puzzle
        self.ctx = ctx
        self.var_keys = var_keys
        self.obs_base = obs_base
        self.actions = actions  # sorted by name ⇒ deterministic, lex-least tie-breaks
        self.weights = weights
        self.max_nodes = max_nodes
        self.memo: dict[tuple[BeliefNode, int], Fraction] = {}
        self.node_count = 0
        self.truncated = False

    def _dict(self, tup: WorldState) -> dict[str, int]:
        return dict(zip(self.var_keys, tup, strict=True))

    def _stop_value(self, node: BeliefNode) -> Fraction:
        """Weight of the member worlds whose goal holds *now* — the value of stopping here."""
        total = Fraction(0)
        for init_tuple, cur_tuple in node:
            if eval_bool(self.puzzle.objective.goal, self._dict(cur_tuple), self.ctx):
                total += self.weights[init_tuple]
        return total

    def _step_live(self, state: dict[str, int]) -> bool:
        """Mirror :func:`spie.interpreter._check_invariants`: invariants hold and ``loss`` is not
        triggered. Matching the interpreter exactly is what makes ``P_A == P_B`` hold by
        construction (domain bounds are intentionally left to the reachability upper bound)."""
        for inv in self.puzzle.objective.invariants:
            if not eval_bool(inv, state, self.ctx):
                return False
        loss = self.puzzle.objective.loss
        return not (loss is not None and eval_bool(loss, state, self.ctx))

    def _successors(
        self, node: BeliefNode, ga: GroundAction
    ) -> dict[WorldState, BeliefNode] | None:
        """Group members by their post-action observation if ``ga`` is legal in *every* member;
        ``None`` if it is illegal in any (precondition fails or the successor is not live). The
        obs-key is ``tuple(succ[k] for k in sorted(obs_base | senses))`` — byte-identical to
        :func:`spie.conformance._plan_trace_for_world`, so DP branches match the replay's."""
        groups: dict[WorldState, list[tuple[WorldState, WorldState]]] = {}
        observed = sorted(set(self.obs_base) | set(ga.senses))
        for init_tuple, cur_tuple in node:
            cur = self._dict(cur_tuple)
            if not eval_bool(ga.precondition, cur, self.ctx):
                return None
            succ = apply_effects(ga.effects, cur, self.ctx)
            if not self._step_live(succ):
                return None
            obs_key = tuple(succ[k] for k in observed)
            succ_tuple = tuple(succ[k] for k in self.var_keys)
            groups.setdefault(obs_key, []).append((init_tuple, succ_tuple))
        return {obs_key: frozenset(members) for obs_key, members in groups.items()}

    def value(self, node: BeliefNode, h: int) -> Fraction:
        """``V(node, h) = max(stop-now weight, max over legal actions of Σ observed children)``.
        Exact and memoized on ``(node, h)``; ``h`` strictly decreases so recursion terminates at
        the horizon. Past the node cap it returns the stop value (a valid lower bound) and records
        ``truncated`` — never a silently-optimistic answer."""
        cached = self.memo.get((node, h))
        if cached is not None:
            return cached
        if self.node_count >= self.max_nodes:
            self.truncated = True
            return self._stop_value(node)
        self.node_count += 1

        best = self._stop_value(node)
        if h > 0:
            for ga in self.actions:
                groups = self._successors(node, ga)
                if groups is None:
                    continue
                total = sum(
                    (self.value(child, h - 1) for child in groups.values()), Fraction(0)
                )
                if total > best:
                    best = total
        self.memo[(node, h)] = best
        return best

    def extract(self, node: BeliefNode, h: int) -> Plan:
        """Read the canonical plan off the memoized values: among value-achieving choices prefer a
        real action that *strictly* beats stopping (so the plan makes progress), and among those
        the lexicographically-least action name; otherwise stop (a leaf). Deterministic, RNG-free,
        and — because a chosen action decrements ``h`` — terminating at the horizon."""
        stop = self._stop_value(node)
        best = self.value(node, h)
        if h > 0 and best > stop:
            for ga in self.actions:  # sorted ⇒ first match is lex-least
                groups = self._successors(node, ga)
                if groups is None:
                    continue
                total = sum(
                    (self.value(child, h - 1) for child in groups.values()), Fraction(0)
                )
                if total == best:
                    branches = tuple(
                        (obs_key, self.extract(groups[obs_key], h - 1))
                        for obs_key in sorted(groups)
                    )
                    return Plan(action=ga.name, branches=branches)
        return Plan(action=None, branches=())


def solve_max_success(puzzle: Puzzle, max_nodes: int = DEFAULT_MAX_NODES) -> ChanceSolution:
    """Method A′: certify the exact optimal expected success probability P and its canonical plan.
    Desugars, builds B0, runs value iteration to the horizon, reads off the canonical plan."""
    puzzle = augment.desugar(puzzle)
    ctx = Context.from_puzzle(puzzle)
    var_keys = [v.key for v in puzzle.variables]
    obs_base = _observable_keys(puzzle)
    actions = sorted(ground_all(puzzle), key=lambda g: g.name)
    weights = _world_weights(puzzle)
    if not weights:
        return ChanceSolution(Fraction(0), Plan(action=None, branches=()), 0, False)
    b0: BeliefNode = frozenset((world, world) for world in weights)
    dp = _ChanceDP(puzzle, ctx, var_keys, obs_base, actions, weights, max_nodes)
    horizon = puzzle.objective.max_horizon
    probability = dp.value(b0, horizon)
    plan = dp.extract(b0, horizon)
    return ChanceSolution(probability, plan, len(weights), dp.truncated)


def _reachable_upper_bound(
    puzzle: Puzzle, weights: dict[WorldState, Fraction], var_keys: list[str]
) -> tuple[Fraction, bool, list[str]]:
    """Upper bound U: the summed weight of the initial worlds individually winnable with full
    knowledge, decided by the existing three-solver reachability cross-check (Z3 ∧ search ∧
    clingo). Each world is a pinned, chance-free first-order query. Returns
    ``(U, solvers_disagreed, discrepancies)``; a solver disagreement is surfaced, not resolved."""
    upper = Fraction(0)
    disagreement = False
    discrepancies: list[str] = []
    for world in sorted(weights):
        concrete = replace(
            puzzle,
            initial={key: world[i] for i, key in enumerate(var_keys)},
            initial_belief={},
            initial_dist={},
        )
        result = cross_solve(concrete)
        if not result.agree:
            disagreement = True
            discrepancies.append(
                f"world {world}: reachability solvers disagree ({result.discrepancies})"
            )
        if result.solvable:
            upper += weights[world]
    return upper, disagreement, discrepancies


def chance_cross_solve(puzzle: Puzzle) -> ChanceCrossResult:
    """Run all three exact checks and report agreement structurally (a discrepancy is never
    smoothed): Method A′ (belief DP → P_A + plan), Method B′ (per-world reference replay → P_B),
    and the reachability upper bound U. ``agree`` requires P_A == P_B, P_A <= U, a uniform plan,
    no truncation, and agreeing reachability solvers."""
    desugared = augment.desugar(puzzle)
    var_keys = [v.key for v in desugared.variables]
    weights = _world_weights(desugared)

    solution = solve_max_success(puzzle)
    probability, plan = solution.probability, solution.plan

    conformance = check_plan_conformance(puzzle, plan)
    replay = Fraction(0)
    for wr in conformance.world_replays:
        if wr.reached_goal:
            replay += weights.get(wr.world, Fraction(0))

    upper, reach_disagree, reach_disc = _reachable_upper_bound(desugared, weights, var_keys)

    discrepancies: list[str] = []
    if probability != replay:
        discrepancies.append(
            f"probability disagreement: belief-DP P_A={probability} vs replay P_B={replay}"
        )
    if probability > upper:
        discrepancies.append(f"probability exceeds reachable bound: P={probability} > U={upper}")
    if solution.truncated:
        discrepancies.append("belief DP truncated at node cap; P may be under-approximate")
    if not conformance.uniform:
        discrepancies.append(f"plan is not uniform (clairvoyance): {conformance.detail}")
    discrepancies.extend(reach_disc)

    return ChanceCrossResult(
        agree=not discrepancies,
        probability=probability,
        probability_replay=replay,
        upper_bound=upper,
        plan=plan,
        world_replays=conformance.world_replays,
        uniform=conformance.uniform,
        world_count=solution.world_count,
        truncated=solution.truncated,
        reachability_disagreement=reach_disagree,
        discrepancies=tuple(discrepancies),
    )


__all__ = [
    "ChanceCrossResult",
    "ChanceSolution",
    "DEFAULT_MAX_NODES",
    "SOLVER_NAME",
    "SOLVER_VERSION",
    "chance_cross_solve",
    "initial_world_weights",
    "solve_max_success",
    "solver_version",
]




