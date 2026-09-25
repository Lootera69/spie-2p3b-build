"""Multi-world bounded model checking — the symbolic epistemic solver (Phase 3, Method B).

This is the symbolic counterpart of :mod:`spie.epistemic`. Where Method A proves strong
solvability *concretely* (a retrograde fixpoint over the powerset of live worlds), this
module proves the same facts *symbolically*, by bounded model checking a **contingent plan**
directly in Z3. The two share no solving code — Method A walks beliefs with the Python
interpreter's semantics; Method B emits SMT constraints — so when they agree on solvability,
worst-case depth, and uniqueness, the epistemic proof is cross-validated (gate **G2**, lifted
to partial observability). The only thing reused here is :func:`spie.z3_compile.compile_expr`
— the single symbolic source of expression semantics — exactly as :mod:`spie.solver` reuses
it; re-deriving the AST→Z3 mapping would risk drift from that source.

The encoding
------------
The finite initial belief ``B0`` is enumerated as concrete worlds (the cross product of the
hidden-variable supports, keeping only live worlds — the same set Method A's
``build_initial_belief`` produces, derived here independently). Each world gets its own BMC
trajectory: a fresh ``v@w{j}@t{t}`` Int per variable/tick, its own transition relation, with
the goal asserted at the final tick and ``loss``/invariants forbidden throughout. A plan is
*strong* iff every world reaches the goal.

Two constraints turn a bag of independent trajectories into one **contingent plan**:

* **Uniformity (no clairvoyance).** For every pair of worlds ``j, k`` a boolean
  ``indist(j,k,t)`` tracks whether they have produced identical *observations* through tick
  ``t`` — the always-visible variables plus whatever the chosen action ``senses``. Worlds
  still indistinguishable when the action at tick ``t`` is chosen must choose the **same**
  action. A plan may branch only where an observation has actually told the worlds apart.
* **Idling at the goal.** A synthetic ``__stay__`` action (enabled only once the goal holds,
  framing every variable) plus a goal-absorbing constraint let a world that wins early hold
  at the goal while slower branches finish. The minimal horizon at which *all* worlds win is
  therefore the plan's worst-case depth — the same size measure Method A reports.

Reduction anchor
----------------
With no hidden variable ``B0`` is a singleton: one trajectory, no pairs, so uniformity is
vacuous; ``__stay__`` can never fire at the minimal horizon (the goal is not yet true) and
the absorbing constraint is vacuous there too. The encoding collapses to ordinary
single-world BMC, so on the 14 fully-observable puzzles it returns the same minimal depth and
uniqueness verdict as :mod:`spie.solver`.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import z3

from . import augment
from .evaluate import Context, eval_bool
from .ground import GroundAction, ground_all
from .interpreter import domain_of, initial_state
from .ir import Observability, Puzzle
from .results import EQUIVALENCE, Uniqueness
from .z3_compile import compile_bool, compile_expr

SOLVER_NAME = "z3-epistemic-bmc"


def solver_version() -> str:
    return z3.get_version_string()


@dataclass(frozen=True)
class StrongResult:
    """Method B's verdict on strong solvability and minimal worst-case depth — the symbolic
    analogue of :class:`spie.epistemic.StrongSolution` (without the reconstructed plan tree,
    which Method A already provides; Method B's role is the independent cross-check)."""

    solvable: bool
    depth: int
    world_count: int


def _live_initial(puzzle: Puzzle, ctx: Context, domains: dict[str, tuple[int, int]],
                  world: dict[str, int]) -> bool:
    """Whether a candidate initial world is a genuine possibility: every variable in range,
    every invariant satisfied, the loss predicate not already triggered. Identical in meaning
    to :func:`spie.epistemic._live`, so both methods enumerate the same ``B0``."""
    for key, (lo, hi) in domains.items():
        if not (lo <= world[key] <= hi):
            return False
    for inv in puzzle.objective.invariants:
        if not eval_bool(inv, world, ctx):
            return False
    if puzzle.objective.loss is not None and eval_bool(puzzle.objective.loss, world, ctx):
        return False
    return True


def initial_worlds(puzzle: Puzzle) -> list[dict[str, int]]:
    """Enumerate ``B0`` as concrete world states: the declared initial state with each
    ``HIDDEN`` variable taking every value in its support, keeping only live worlds. With no
    hidden variables this is the single declared initial state (or empty if it is not live).
    Worlds are ordered by the sorted hidden-key cross product for determinism."""
    puzzle = augment.desugar(puzzle)
    ctx = Context.from_puzzle(puzzle)
    domains = {var.key: domain_of(puzzle, var.key) for var in puzzle.variables}
    init = initial_state(puzzle)
    hidden_keys = sorted(puzzle.initial_belief.keys())
    supports = [puzzle.initial_belief[k] for k in hidden_keys]

    worlds: list[dict[str, int]] = []
    for combo in itertools.product(*supports):
        world = dict(init)
        for k, val in zip(hidden_keys, combo, strict=True):
            world[k] = val
        if _live_initial(puzzle, ctx, domains, world):
            worlds.append(world)
    return worlds


@dataclass
class _MultiWorld:
    """A multi-world unrolling to a fixed horizon, with every strong-plan constraint asserted
    on ``solver`` (goal on all worlds included). ``v`` maps ``(var, world, tick)`` to its Int
    constant; ``fire`` maps ``(world, action_index, tick)`` to its selector Bool (the action
    index ``len(ground)`` is the synthetic ``__stay__``)."""

    puzzle: Puzzle
    worlds: list[dict[str, int]]
    horizon: int
    ctx: Context
    ground: list[GroundAction]
    v: dict[tuple[str, int, int], z3.ArithRef]
    fire: dict[tuple[int, int, int], z3.BoolRef]
    solver: z3.Solver

    def read_joint_path(self, model: z3.ModelRef) -> tuple[tuple[tuple[int, ...], ...], ...]:
        """The canonical joint state-path: for each world, its s0..sH sequence of variable
        tuples (declared order). This is the equivalence object the uniqueness check blocks —
        two contingent plans are the same iff every world traces the same states."""
        keys = [var.key for var in self.puzzle.variables]
        return tuple(
            tuple(
                tuple(
                    model.eval(self.v[(k, j, t)], model_completion=True).as_long() for k in keys
                )
                for t in range(self.horizon + 1)
            )
            for j in range(len(self.worlds))
        )

    def block_joint_path(self, path: tuple[tuple[tuple[int, ...], ...], ...]) -> None:
        """Forbid this exact joint state-path, so a re-solve must differ in some world."""
        keys = [var.key for var in self.puzzle.variables]
        eqs = [
            self.v[(k, j, t)] == path[j][t][i]
            for j in range(len(self.worlds))
            for t in range(self.horizon + 1)
            for i, k in enumerate(keys)
        ]
        self.solver.add(z3.Not(z3.And(eqs)))


def _build(puzzle: Puzzle, worlds: list[dict[str, int]], horizon: int) -> _MultiWorld:
    """Assert every constraint of the multi-world contingent encoding at ``horizon``."""
    ctx = Context.from_puzzle(puzzle)
    ground = ground_all(puzzle)
    var_list = list(puzzle.variables)
    domains = {var.key: domain_of(puzzle, var.key) for var in var_list}
    visible = [var.key for var in var_list if var.obs is Observability.VISIBLE]
    goal = puzzle.objective.goal
    m = len(worlds)
    n_real = len(ground)
    solver = z3.Solver()

    v: dict[tuple[str, int, int], z3.ArithRef] = {}
    for j in range(m):
        for var in var_list:
            lo, hi = domains[var.key]
            for t in range(horizon + 1):
                c = z3.Int(f"{var.key}@w{j}@t{t}")
                v[(var.key, j, t)] = c
                solver.add(c >= lo, c <= hi)

    def var_at(j: int, t: int) -> dict[str, z3.ArithRef]:
        return {var.key: v[(var.key, j, t)] for var in var_list}

    # Pin each world's initial state; assert invariants/loss/goal per world per tick.
    for j, world in enumerate(worlds):
        for var in var_list:
            solver.add(v[(var.key, j, 0)] == world[var.key])
        for t in range(horizon + 1):
            va = var_at(j, t)
            for inv in puzzle.objective.invariants:
                solver.add(compile_bool(inv, va, ctx))
            if puzzle.objective.loss is not None:
                solver.add(z3.Not(compile_bool(puzzle.objective.loss, va, ctx)))
        # The goal is absorbing (so a world that wins early may idle) and must hold at the end.
        for t in range(horizon):
            solver.add(
                z3.Implies(compile_bool(goal, var_at(j, t), ctx),
                           compile_bool(goal, var_at(j, t + 1), ctx))
            )
        solver.add(compile_bool(goal, var_at(j, horizon), ctx))

    # Transition relation per world/tick, with an exactly-one-action selector including __stay__.
    fire: dict[tuple[int, int, int], z3.BoolRef] = {}
    for j in range(m):
        for t in range(horizon):
            cur = var_at(j, t)
            selectors: list[z3.BoolRef] = []
            for i, ga in enumerate(ground):
                sel = z3.Bool(f"fire_{i}@w{j}@t{t}")
                fire[(j, i, t)] = sel
                selectors.append(sel)
                written = {e.key for e in ga.effects}
                cons = [compile_bool(ga.precondition, cur, ctx)]
                cons += [
                    v[(e.key, j, t + 1)] == compile_expr(e.value, cur, ctx) for e in ga.effects
                ]
                cons += [
                    v[(var.key, j, t + 1)] == v[(var.key, j, t)]
                    for var in var_list
                    if var.key not in written
                ]
                solver.add(z3.Implies(sel, z3.And(cons)))
            # __stay__: enabled only once the goal holds, frames every variable (a true no-op).
            stay = z3.Bool(f"fire_stay@w{j}@t{t}")
            fire[(j, n_real, t)] = stay
            selectors.append(stay)
            stay_cons = [compile_bool(goal, cur, ctx)]
            stay_cons += [v[(var.key, j, t + 1)] == v[(var.key, j, t)] for var in var_list]
            solver.add(z3.Implies(stay, z3.And(stay_cons)))
            solver.add(z3.PbEq([(s, 1) for s in selectors], 1))

    # Uniformity: worlds with identical observation history choose identical actions.
    _assert_uniformity(solver, worlds, horizon, ground, v, fire, visible)

    return _MultiWorld(puzzle, worlds, horizon, ctx, ground, v, fire, solver)


def _assert_uniformity(
    solver: z3.Solver,
    worlds: list[dict[str, int]],
    horizon: int,
    ground: list[GroundAction],
    v: dict[tuple[str, int, int], z3.ArithRef],
    fire: dict[tuple[int, int, int], z3.BoolRef],
    visible: list[str],
) -> None:
    """The no-clairvoyance constraint, pairwise over worlds.

    ``indist(j,k,t)`` holds when worlds ``j`` and ``k`` have produced identical observations
    through tick ``t``: at ``t=0`` the visible variables coincide (they always do — every
    ``B0`` world shares the declared visible initial state); at each later tick it also
    requires that the variables *sensed* by the action taken at the previous tick coincide.
    Whenever two worlds are indistinguishable at the moment an action is chosen, that action
    must be the same in both — so the plan branches only after an observation splits them.
    """
    m = len(worlds)
    n_sel = len(ground) + 1  # real actions plus __stay__

    for j in range(m):
        for k in range(j + 1, m):
            indist: list[z3.BoolRef] = []
            for t in range(horizon):
                visible_match = z3.And(
                    [v[(vv, j, t)] == v[(vv, k, t)] for vv in visible]
                ) if visible else z3.BoolVal(True)
                if t == 0:
                    same = visible_match
                else:
                    # A sensed variable is observed only if the action that senses it was the
                    # one fired at the previous tick (the worlds fire the same action there,
                    # since they were indistinguishable then).
                    sense_terms = [
                        z3.Implies(
                            fire[(j, i, t - 1)],
                            z3.And([v[(s, j, t)] == v[(s, k, t)] for s in ga.senses]),
                        )
                        for i, ga in enumerate(ground)
                        if ga.senses
                    ]
                    sense_match = z3.And(sense_terms) if sense_terms else z3.BoolVal(True)
                    same = z3.And(indist[t - 1], visible_match, sense_match)
                flag = z3.Bool(f"indist_{j}_{k}@t{t}")
                solver.add(flag == same)
                indist.append(flag)
                # Same information ⇒ same decision.
                solver.add(
                    z3.Implies(
                        flag,
                        z3.And([fire[(j, i, t)] == fire[(k, i, t)] for i in range(n_sel)]),
                    )
                )


def _minimal_depth(puzzle: Puzzle, worlds: list[dict[str, int]]) -> int | None:
    """Search the horizon upward for the least at which a strong contingent plan exists, or
    ``None`` if none exists within ``max_horizon`` (mirrors ``solver.solve``'s upward search)."""
    for horizon in range(puzzle.objective.max_horizon + 1):
        mw = _build(puzzle, worlds, horizon)
        if mw.solver.check() == z3.sat:
            return horizon
    return None


def solve_strong(puzzle: Puzzle) -> StrongResult:
    """Decide strong solvability and the minimal worst-case depth symbolically."""
    puzzle = augment.desugar(puzzle)
    worlds = initial_worlds(puzzle)
    if not worlds:
        return StrongResult(False, puzzle.objective.max_horizon, 0)
    depth = _minimal_depth(puzzle, worlds)
    if depth is None:
        return StrongResult(False, puzzle.objective.max_horizon, len(worlds))
    return StrongResult(True, depth, len(worlds))


# Named to mirror ``epistemic.solve`` / ``solver.solve``.
solve = solve_strong


def check_uniqueness(puzzle: Puzzle) -> Uniqueness:
    """Decide plan uniqueness under the joint-state-path equivalence: find the minimal-depth
    plan, block its exact per-world state-paths, and re-solve. ``unsat`` means no genuinely
    different strong plan of the same worst-case depth exists. Mirrors
    :func:`spie.solver.check_uniqueness` (and reduces to it when nothing is hidden).

    Relationship to Method A. This joint-state-path equivalence is *at least as fine* as
    Method A's belief-trajectory equivalence: if two optimal plans reach different successor
    *beliefs* they necessarily assign some tracked world a different state, so a differing
    joint path exists — hence **B-unique ⟹ A-unique** (Method B never over-certifies
    uniqueness). The converse can fail only for an exotic "swap-symmetric" pair of optimal
    actions that permutes which world maps to which successor while leaving every belief set
    unchanged; no such puzzle exists in the corpus, so the two verdicts coincide on everything
    tested. Should a future fixture expose the gap, the reconciliation is to block the plan's
    observable decision structure (observation-history → action) rather than the raw per-world
    state-paths — the cross-check test is what will catch it."""
    puzzle = augment.desugar(puzzle)
    worlds = initial_worlds(puzzle)
    if not worlds:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)
    depth = _minimal_depth(puzzle, worlds)
    if depth is None:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)
    mw = _build(puzzle, worlds, depth)
    assert mw.solver.check() == z3.sat  # depth came from a sat check at this horizon
    path = mw.read_joint_path(mw.solver.model())
    mw.block_joint_path(path)
    if mw.solver.check() == z3.sat:
        return Uniqueness(unique=False, equivalence=EQUIVALENCE)
    return Uniqueness(unique=True, equivalence=EQUIVALENCE)


__all__ = [
    "SOLVER_NAME",
    "solver_version",
    "StrongResult",
    "initial_worlds",
    "solve",
    "solve_strong",
    "check_uniqueness",
]
