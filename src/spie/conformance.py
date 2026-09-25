"""Conformance: the trust boundary between the solver and the ground-truth runtime.

The roadmap's rule is that a solver proof is only believed once its solution *replays
cleanly* through the deterministic interpreter. This module does exactly that — and nothing
here imports a solver or z3, so the check is genuinely independent of the machinery it audits.

* :func:`check_conformance` is the Phase-1/2 linear check: run the solver's trace in
  :mod:`spie.interpreter` and assert (a) no step is rejected, (b) the goal is reached, and
  (c) the interpreter's state-path is byte-for-byte the one the solver reported.

* :func:`check_plan_conformance` is the Phase-3 generalization to a **contingent plan** under
  partial observability. It replays the policy over **every** world in the initial belief
  ``B0`` through the interpreter: each world follows the plan's branches using only what *that
  world* observes, and its induced linear trace must reach the goal legally (no ``loss``, no
  invariant break). Crucially the **uniformity / no-clairvoyance** property — that a decision
  depends only on observed history — is *checked* against the replayed behaviour, not assumed
  from the plan's tree shape.

Any divergence here means the solver and the ground-truth runtime have drifted, and the
certificate must not be trusted.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

from . import augment
from .evaluate import Context, apply_effects, eval_bool
from .ground import ground_all
from .interpreter import ExecutionError, domain_of, initial_state, run
from .ir import Observability, Puzzle, WorldReplay
from .results import Plan, Solution


@dataclass
class Conformance:
    """Result of replaying a linear solver trace through the interpreter."""

    ok: bool
    reached_goal: bool
    detail: str


def check_conformance(puzzle: Puzzle, solution: Solution) -> Conformance:
    """Replay ``solution.trace`` in the interpreter and compare against the solver's claim."""
    if not solution.solvable:
        return Conformance(ok=True, reached_goal=False, detail="no solution to replay")

    try:
        outcome = run(puzzle, solution.trace)
    except ExecutionError as exc:
        return Conformance(
            ok=False, reached_goal=False, detail=f"interpreter rejected trace: {exc}"
        )

    if not outcome.reached_goal:
        return Conformance(
            ok=False, reached_goal=False, detail="solver trace did not reach the goal at runtime"
        )

    keys = [v.key for v in puzzle.variables]
    interp_path = tuple(tuple(s[k] for k in keys) for s in outcome.states)
    if interp_path != solution.state_path:
        return Conformance(
            ok=False,
            reached_goal=True,
            detail="state-path mismatch: interpreter and solver disagree on the run",
        )

    return Conformance(ok=True, reached_goal=True, detail="trace replays cleanly and reaches goal")


# ---------------------------------------------------------------------------
# Contingent (epistemic) conformance
# ---------------------------------------------------------------------------


@dataclass
class PlanConformance:
    """Result of replaying a contingent plan over every world in ``B0``.

    ``ok`` is the overall verdict: every world's induced trace reached the goal legally *and*
    the replay was uniform. ``reached_goal_all`` and ``uniform`` break that into its two
    independent obligations; ``world_replays`` is the per-world evidence recorded in the
    certificate; ``detail`` names any failure (empty-belief, an illegal step, a missed goal,
    or a uniformity violation)."""

    ok: bool
    reached_goal_all: bool
    uniform: bool
    world_replays: tuple[WorldReplay, ...]
    detail: str


def _live(puzzle: Puzzle, ctx: Context, domains: dict[str, tuple[int, int]],
          state: dict[str, int]) -> bool:
    """Would the runtime admit this world at the start? Every variable in range, every
    invariant satisfied, the loss predicate not already triggered — the same liveness the
    solvers use to build ``B0``, re-derived here so conformance depends on no solver."""
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
    """The variables observed every tick without sensing: the ``VISIBLE`` ones, sorted."""
    return tuple(sorted(v.key for v in puzzle.variables if v.obs is Observability.VISIBLE))


def initial_worlds(
    puzzle: Puzzle,
    ctx: Context | None = None,
    domains: dict[str, tuple[int, int]] | None = None,
) -> list[dict[str, int]]:
    """Enumerate ``B0`` as concrete world dicts, independently of either solver: the declared
    initial state with each ``HIDDEN`` variable taking every value in its support, live worlds
    only. With no hidden variables this is the single declared initial state (fully-observable
    reduction)."""
    if ctx is None:
        ctx = Context.from_puzzle(puzzle)
    if domains is None:
        domains = {v.key: domain_of(puzzle, v.key) for v in puzzle.variables}
    init = initial_state(puzzle)
    hidden_keys = sorted(puzzle.initial_belief.keys())
    supports = [puzzle.initial_belief[k] for k in hidden_keys]

    worlds: list[dict[str, int]] = []
    for combo in itertools.product(*supports):
        world = dict(init)
        for k, val in zip(hidden_keys, combo, strict=True):
            world[k] = val
        if _live(puzzle, ctx, domains, world):
            worlds.append(world)
    return worlds


def _observation(state: dict[str, int], observed_keys: list[str]) -> tuple[tuple[str, int], ...]:
    """A key-tagged observation: the observed variables' values, keyed so two observations are
    equal iff they expose the same variables at the same values (robust across differing
    sense-sets between plan branches)."""
    return tuple((k, state[k]) for k in observed_keys)


def _plan_trace_for_world(
    puzzle: Puzzle,
    ctx: Context,
    ground_by_name: dict,
    obs_base: tuple[str, ...],
    plan: Plan,
    world: dict[str, int],
) -> tuple[list[str], list[tuple[tuple[str, int], ...]], str]:
    """Follow the contingent plan for one concrete world.

    Returns ``(trace, obs_seq, detail)``. ``trace`` is the linear action sequence the plan
    prescribes once this world's observations select branches; ``obs_seq[t]`` is the key-tagged
    observation available *before* deciding action ``t`` (``obs_seq[0]`` is the initial visible
    observation), so ``obs_seq[:t+1]`` is the exact information a uniform decision at ``t`` may
    use. ``detail`` is non-empty iff the plan is malformed for this world (an action illegal
    here, or no branch matching the observation) — a proof the plan is not strong.
    """
    state = dict(world)
    trace: list[str] = []
    obs_seq: list[tuple[tuple[str, int], ...]] = [_observation(state, list(obs_base))]
    node = plan
    while not node.is_leaf:
        ga = ground_by_name.get(node.action)
        if ga is None:
            return trace, obs_seq, f"unknown action {node.action!r}"
        if not eval_bool(ga.precondition, state, ctx):
            return trace, obs_seq, f"precondition failed for {node.action!r}"
        succ = apply_effects(ga.effects, state, ctx)
        observed = sorted(set(obs_base) | set(ga.senses))
        obs_key = tuple(succ[k] for k in observed)
        trace.append(node.action)
        match = [child for branch_key, child in node.branches if branch_key == obs_key]
        if not match:
            return trace, obs_seq, f"no plan branch for observation {obs_key} after {node.action!r}"
        state = succ
        obs_seq.append(_observation(state, observed))
        node = match[0]
    return trace, obs_seq, ""


def _check_uniformity(
    obs_traces: list[tuple[list[tuple[tuple[str, int], ...]], list[str]]],
) -> tuple[bool, str]:
    """Audit no-clairvoyance directly from the replayed behaviour: any two worlds that have
    produced identical observations through the decision at step ``t`` must have taken the same
    action at ``t``. This confirms the certified plan branched only on information the player
    actually had — checked against the runs, not assumed from the plan's shape."""
    n = len(obs_traces)
    for j in range(n):
        obs_j, trace_j = obs_traces[j]
        for k in range(j + 1, n):
            obs_k, trace_k = obs_traces[k]
            for t in range(min(len(trace_j), len(trace_k))):
                if obs_j[: t + 1] == obs_k[: t + 1] and trace_j[t] != trace_k[t]:
                    return False, (
                        f"uniformity violated: two worlds share observations through step {t} "
                        f"but take {trace_j[t]!r} vs {trace_k[t]!r}"
                    )
    return True, ""


def check_plan_conformance(puzzle: Puzzle, plan: Plan | None) -> PlanConformance:
    """Replay a contingent ``plan`` over every world in ``B0`` and audit it end to end.

    For each world the plan induces a linear trace (its branches followed by that world's
    observations); the trace is executed in the interpreter and must reach the goal without a
    precondition, invariant, or ``loss`` violation. Across worlds, uniformity is then checked.
    On a fully-observable puzzle ``B0`` is a singleton and this reduces to a single
    :func:`check_conformance`-style replay."""
    puzzle = augment.desugar(puzzle)
    if plan is None:
        return PlanConformance(
            ok=True, reached_goal_all=False, uniform=True, world_replays=(),
            detail="no plan to replay",
        )

    ctx = Context.from_puzzle(puzzle)
    domains = {v.key: domain_of(puzzle, v.key) for v in puzzle.variables}
    obs_base = _observable_keys(puzzle)
    ground_by_name = {g.name: g for g in ground_all(puzzle)}
    var_keys = [v.key for v in puzzle.variables]

    worlds = initial_worlds(puzzle, ctx, domains)
    if not worlds:
        return PlanConformance(
            ok=False, reached_goal_all=False, uniform=True, world_replays=(),
            detail="initial belief B0 is empty (unsatisfiable start observation)",
        )

    replays: list[WorldReplay] = []
    obs_traces: list[tuple[list[tuple[tuple[str, int], ...]], list[str]]] = []
    details: list[str] = []
    all_ok = True
    all_goal = True

    for world in worlds:
        world_tuple = tuple(world[k] for k in var_keys)
        trace, obs_seq, walk_detail = _plan_trace_for_world(
            puzzle, ctx, ground_by_name, obs_base, plan, world
        )
        obs_traces.append((obs_seq, trace))
        if walk_detail:
            replays.append(WorldReplay(world_tuple, tuple(trace), False, False))
            details.append(f"world {world_tuple}: {walk_detail}")
            all_ok = False
            all_goal = False
            continue
        concrete = replace(puzzle, initial=dict(world))
        try:
            outcome = run(concrete, trace)
            reached = outcome.reached_goal
            if not reached:
                details.append(f"world {world_tuple}: trace did not reach the goal at runtime")
        except ExecutionError as exc:
            reached = False
            details.append(f"world {world_tuple}: interpreter rejected trace: {exc}")
        replays.append(WorldReplay(world_tuple, tuple(trace), reached, reached))
        all_ok = all_ok and reached
        all_goal = all_goal and reached

    uniform, uni_detail = _check_uniformity(obs_traces)
    if not uniform:
        all_ok = False
        details.append(uni_detail)

    detail = "; ".join(details) if details else (
        f"plan replays cleanly and reaches the goal on all {len(worlds)} world(s)"
    )
    return PlanConformance(
        ok=all_ok, reached_goal_all=all_goal, uniform=uniform,
        world_replays=tuple(replays), detail=detail,
    )


__all__ = [
    "Conformance",
    "check_conformance",
    "PlanConformance",
    "check_plan_conformance",
    "initial_worlds",
]
