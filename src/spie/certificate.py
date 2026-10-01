"""Assemble the machine-verifiable certificate — the whole proof loop in one call.

``certify`` runs the pipeline the roadmap prescribes: static validation, cross-solver
reachability (Z3 *and* explicit-state search — gate G2), uniqueness, and conformance replay.
It records the result as an :class:`~spie.ir.Certificate` whose fields are exactly what a
later audit needs to re-check the claim: solver identity and version, the horizon, the
ordered solution, the uniqueness verdict and its equivalence relation, whether conformance
held, any validation warnings, and one :class:`~spie.ir.SolverEvidence` per method so an
auditor sees two independent solvers stand behind the proof. Serialization to canonical JSON
lives in :mod:`spie.serialize`, so two runs on the same seed produce identical bytes.
"""

from __future__ import annotations

from . import chance, epistemic, search
from .conformance import check_conformance, check_plan_conformance
from .crosscheck import cross_solve, epistemic_cross_solve
from .ir import Certificate, Puzzle, Step
from .solver import SOLVER_NAME, solver_version
from .validate import validate


def certify(puzzle: Puzzle) -> Certificate:
    """Run validate -> cross-solve -> conformance and package a Certificate.

    The pipeline branches on whether the puzzle carries randomness or hidden initial state, in
    that priority. A puzzle with a non-empty :attr:`~spie.ir.Puzzle.initial_dist` takes the
    Item-4 *chance* path and certifies an exact optimal expected success probability. Otherwise a
    *fully-observable* puzzle (empty :attr:`~spie.ir.Puzzle.initial_belief`) takes the Phase-1/2
    linear path unchanged, so its certificate is byte-identical to before — the reduction anchor.
    A puzzle *with* hidden state but no distribution is solved as a contingent plan under partial
    observability and cross-checked by the two epistemic methods (gate G2 lifted). Any
    cross-solver disagreement becomes a warning so it can never pass silently.
    """
    warnings = [f"{f.rule}: {f.message}" for f in validate(puzzle)]
    if puzzle.initial_dist:
        return _certify_chance(puzzle, warnings)
    if puzzle.initial_belief:
        return _certify_contingent(puzzle, warnings)
    return _certify_linear(puzzle, warnings)


def _certify_linear(puzzle: Puzzle, warnings: list[str]) -> Certificate:
    """The fully-observable proof loop (Phase 1/2), verbatim.

    Z3 supplies the reachability/uniqueness proof and the explicit-state search corroborates
    it (gate G2); both methods' independent evidence is recorded. The *recorded* solution,
    however, is the canonical (lexicographically-least) minimal trace from
    :func:`spie.search.canonical_solution` — a function of the puzzle alone — so the
    certificate is byte-reproducible even when the puzzle has several minimal solutions and a
    solver's model would otherwise name an arbitrary one.
    """
    cross = cross_solve(puzzle)
    solution = search.canonical_solution(puzzle)
    uniqueness = cross.uniqueness
    conformance = check_conformance(puzzle, solution)
    if not cross.agree:
        warnings.append("cross-solver: " + "; ".join(cross.discrepancies))

    steps = tuple(Step(tick=i, action=name) for i, name in enumerate(solution.trace))
    return Certificate(
        puzzle_id=puzzle.id,
        seed=puzzle.seed,
        solver=SOLVER_NAME,
        solver_version=solver_version(),
        horizon=solution.horizon,
        solvable=solution.solvable,
        solution=steps,
        unique=uniqueness.unique,
        equivalence=uniqueness.equivalence,
        conformance_ok=conformance.ok,
        warnings=warnings,
        solvers=cross.evidence,
    )


def _certify_contingent(puzzle: Puzzle, warnings: list[str]) -> Certificate:
    """The partial-observability proof loop: cross-check the two epistemic methods, replay the
    certified contingent plan over every world of ``B0``, and package the epistemic certificate.

    The certified ``plan`` is Method A's canonical contingent plan (byte-reproducible);
    :func:`~spie.crosscheck.epistemic_cross_solve` confirms Method B agrees on solvability,
    worst-case depth, and uniqueness, and :func:`~spie.conformance.check_plan_conformance`
    proves — against the interpreter — that the plan reaches the goal legally on *every* world
    and branches only on observed history. The linear ``solution`` spine is recorded only when
    the plan does not branch; otherwise the full policy tree lives in ``plan``.
    """
    cross = epistemic_cross_solve(puzzle)
    if not cross.agree:
        warnings.append("epistemic cross-solver: " + "; ".join(cross.discrepancies))
    plan = cross.plan
    conformance = check_plan_conformance(puzzle, plan)

    linear = plan.linear_trace() if plan is not None else None
    steps = tuple(Step(tick=i, action=a) for i, a in enumerate(linear)) if linear else ()
    return Certificate(
        puzzle_id=puzzle.id,
        seed=puzzle.seed,
        solver=epistemic.SOLVER_NAME,
        solver_version=epistemic.solver_version(),
        horizon=cross.depth,
        solvable=cross.solvable,
        solution=steps,
        unique=cross.unique,
        equivalence=cross.equivalence,
        conformance_ok=conformance.ok,
        warnings=warnings,
        solvers=(),
        plan=plan,
        epistemic=cross.evidence,
        world_replays=conformance.world_replays,
    )


def _certify_chance(puzzle: Puzzle, warnings: list[str]) -> Certificate:
    """The Item-4 chance proof loop: certify the exact optimal expected success probability ``P``.

    :func:`spie.chance.chance_cross_solve` runs three independent exact computations — the
    weight-aware belief DP (``P_A`` + the canonical contingent plan), the per-world
    reference-interpreter replay tally (``P_B``), and the three-solver reachability upper bound
    (``U``) — and reports agreement structurally. Any disagreement (``P_A != P_B``, ``P > U``, a
    non-uniform/clairvoyant plan, node-cap truncation, or a reachability solver split) is recorded
    here as a warning and made a hard failure by :mod:`spie.verify`; nothing is smoothed.

    ``success_probability`` is the exact :class:`~fractions.Fraction` ``P`` and
    ``success_probability_upper_bound`` is ``U``. ``solvable`` means *fully* winnable (``P == 1``),
    not merely ``P > 0``. The linear ``solution`` spine is recorded only when the plan does not
    branch; otherwise the full policy tree lives in ``plan``.
    """
    cross = chance.chance_cross_solve(puzzle)
    if not cross.agree:
        warnings.append("chance cross-solver: " + "; ".join(cross.discrepancies))
    plan = cross.plan

    linear = plan.linear_trace() if plan is not None else None
    steps = tuple(Step(tick=i, action=a) for i, a in enumerate(linear)) if linear else ()
    return Certificate(
        puzzle_id=puzzle.id,
        seed=puzzle.seed,
        solver=chance.SOLVER_NAME,
        solver_version=chance.solver_version(),
        horizon=plan.depth() if plan is not None else 0,
        solvable=(cross.probability == 1),
        solution=steps,
        unique=False,
        equivalence="max-expected-success",
        conformance_ok=cross.agree,
        warnings=warnings,
        solvers=(),
        plan=plan,
        epistemic=(),
        world_replays=cross.world_replays,
        success_probability=cross.probability,
        success_probability_upper_bound=cross.upper_bound,
    )


__all__ = ["certify"]
