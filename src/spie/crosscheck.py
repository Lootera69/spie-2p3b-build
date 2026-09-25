"""Cross-solver agreement — the operational core of decision gate G2.

The roadmap's gate **G2** requires independent solving methods with solution certificates that
agree. This module runs **three** — the symbolic Z3 backend (:mod:`spie.solver`), the concrete
explicit-state search (:mod:`spie.search`), and the answer-set-programming backend
(:mod:`spie.asp_solver`, clingo) — on the same puzzle and compares their verdicts field for
field. When all three agree, the puzzle's proof is corroborated by three paradigms (SMT,
explicit search, ASP) that share no encoding code; when any disagree, the discrepancy is
surfaced structurally instead of silently trusting one tool.

Agreement is checked on the facts every method decides independently: **solvability**, the
**minimal horizon** (solution length), and **uniqueness** at that horizon. Cost is *not*
asserted equal: at a tied minimal length the solvers may legitimately return different
minimal-length solutions with different costs, so cost is recorded per-method as evidence and
left to the shortcut gate (which reasons about minimal *cost* explicitly via
:func:`spie.search.solve_min_cost`).

The Z3 result is treated as primary — it supplies the canonical trace the certificate records
and conformance replays — while the search and ASP results supply corroborating
:class:`~spie.ir.SolverEvidence`. All three pieces of evidence are folded into the certificate,
so an auditor sees that three methods, not one, stand behind the claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import asp_solver, epistemic, search, solver, z3_epistemic
from .ir import EpistemicEvidence, Puzzle, SolverEvidence
from .results import Plan, Solution, Uniqueness


@dataclass
class CrossResult:
    """Combined verdict of all three solvers plus a record of any disagreement.

    ``agree`` is true iff the three methods matched on solvability and — when solvable — on
    minimal horizon and uniqueness. The flattened ``solvable``/``horizon``/``cost``/``unique``
    fields are the agreed summary (from the primary Z3 result); ``evidence`` holds one
    :class:`~spie.ir.SolverEvidence` per method for the certificate; ``discrepancies`` lists
    human-readable mismatches (empty when ``agree``). ``solution``/``uniqueness`` are the
    primary Z3 artifacts that downstream code (conformance, certificate) consumes.
    """

    agree: bool
    solvable: bool
    horizon: int
    cost: int
    unique: bool
    evidence: tuple[SolverEvidence, ...]
    solution: Solution
    uniqueness: Uniqueness
    discrepancies: list[str] = field(default_factory=list)


def _evidence(name: str, version: str, sol: Solution, uniq: Uniqueness) -> SolverEvidence:
    """Package one solver's independently-derived verdict as certificate evidence."""
    return SolverEvidence(
        name=name,
        version=version,
        solvable=sol.solvable,
        horizon=sol.horizon,
        cost=sol.cost,
        unique=uniq.unique,
    )


def cross_solve(puzzle: Puzzle) -> CrossResult:
    """Run Z3, explicit-state search and ASP independently and compare their verdicts.

    Returns a :class:`CrossResult` carrying the agreed summary and per-method evidence. On any
    mismatch, ``agree`` is false and ``discrepancies`` names each disagreeing field; the caller
    decides how loudly to fail (``certify`` records it as a warning; the verification suite
    fails the reachability gate).
    """
    z3_sol = solver.solve(puzzle)
    z3_uniq = solver.check_uniqueness(puzzle, z3_sol)
    se_sol = search.solve(puzzle)
    se_uniq = search.check_uniqueness(puzzle, se_sol)
    asp_sol = asp_solver.solve(puzzle)
    asp_uniq = asp_solver.check_uniqueness(puzzle, asp_sol)

    methods = (
        (solver.SOLVER_NAME, z3_sol, z3_uniq),
        (search.SOLVER_NAME, se_sol, se_uniq),
        (asp_solver.SOLVER_NAME, asp_sol, asp_uniq),
    )

    def _mismatch(field_name: str, values: list[tuple[str, object]]) -> str | None:
        if len({v for _, v in values}) > 1:
            return f"{field_name}: " + " ".join(f"{n}={v}" for n, v in values)
        return None

    discrepancies: list[str] = []
    solvable_mismatch = _mismatch(
        "solvable", [(n, s.solvable) for n, s, _ in methods]
    )
    if solvable_mismatch is not None:
        discrepancies.append(solvable_mismatch)
    elif z3_sol.solvable:
        # All agree the puzzle is solvable — length and uniqueness must match too.
        horizon_mismatch = _mismatch("horizon", [(n, s.horizon) for n, s, _ in methods])
        if horizon_mismatch is not None:
            discrepancies.append(horizon_mismatch)
        unique_mismatch = _mismatch("unique", [(n, u.unique) for n, _, u in methods])
        if unique_mismatch is not None:
            discrepancies.append(unique_mismatch)

    evidence = (
        _evidence(solver.SOLVER_NAME, solver.solver_version(), z3_sol, z3_uniq),
        _evidence(search.SOLVER_NAME, search.solver_version(), se_sol, se_uniq),
        _evidence(asp_solver.SOLVER_NAME, asp_solver.solver_version(), asp_sol, asp_uniq),
    )
    return CrossResult(
        agree=not discrepancies,
        solvable=z3_sol.solvable,
        horizon=z3_sol.horizon,
        cost=z3_sol.cost,
        unique=z3_uniq.unique,
        evidence=evidence,
        solution=z3_sol,
        uniqueness=z3_uniq,
        discrepancies=discrepancies,
    )


__all__ = [
    "CrossResult",
    "cross_solve",
    "EpistemicCrossResult",
    "epistemic_cross_solve",
]


# ---------------------------------------------------------------------------
# Epistemic cross-solving — gate G2 lifted to partial observability
# ---------------------------------------------------------------------------


@dataclass
class EpistemicCrossResult:
    """Combined verdict of both *epistemic* solvers — gate **G2** under partial observability.

    ``agree`` is true iff Method A (belief-space AND/OR search, :mod:`spie.epistemic`) and
    Method B (multi-world SMT, :mod:`spie.z3_epistemic`) matched on strong-solvability and —
    when solvable — on minimal worst-case depth and plan uniqueness, *and* Method A's
    belief-space enumeration completed (was not truncated). The flattened
    ``solvable``/``depth``/``unique`` fields are the agreed summary (from Method A, which also
    supplies the reconstructed ``plan``); ``world_count`` is ``|B0|``; ``evidence`` holds one
    :class:`~spie.ir.EpistemicEvidence` per method for the certificate; ``discrepancies`` lists
    human-readable mismatches (empty when ``agree``). ``plan`` is the certified contingent plan
    that downstream code (conformance, certificate) consumes."""

    agree: bool
    solvable: bool
    depth: int
    unique: bool
    equivalence: str
    world_count: int
    evidence: tuple[EpistemicEvidence, ...]
    plan: Plan | None
    discrepancies: list[str] = field(default_factory=list)


def _epistemic_evidence(
    name: str, version: str, solvable: bool, depth: int, unique: bool
) -> EpistemicEvidence:
    """Package one epistemic solver's independently-derived verdict as certificate evidence."""
    return EpistemicEvidence(
        name=name, version=version, solvable=solvable, depth=depth, unique=unique
    )


def epistemic_cross_solve(puzzle: Puzzle) -> EpistemicCrossResult:
    """Run the concrete belief-space solver (Method A) and the symbolic multi-world solver
    (Method B) independently and compare their epistemic verdicts.

    The two share no solving code — Method A walks beliefs with the Python interpreter's
    semantics, Method B emits multi-world SMT — so agreement on ``(solvable, depth, unique)``
    corroborates the contingent-planning proof rather than trusting one tool. The recorded
    ``plan`` is Method A's canonical (lexicographically-least) contingent plan, a function of
    the puzzle alone, so the certificate stays byte-reproducible; Method B's role is the
    independent cross-check. A truncated Method A enumeration is treated as a disagreement (the
    proof is not complete), never silently accepted.
    """
    a = epistemic.solve_strong(puzzle)
    a_uniq = epistemic.check_uniqueness(puzzle)
    b = z3_epistemic.solve_strong(puzzle)
    b_uniq = z3_epistemic.check_uniqueness(puzzle)

    discrepancies: list[str] = []
    if a.truncated:
        discrepancies.append(
            f"{epistemic.SOLVER_NAME}: belief space truncated at {a.belief_count} beliefs "
            "— conclusion not complete"
        )
    if a.solvable != b.solvable:
        discrepancies.append(
            f"solvable: {epistemic.SOLVER_NAME}={a.solvable} "
            f"{z3_epistemic.SOLVER_NAME}={b.solvable}"
        )
    elif a.solvable:
        # Both agree it is strongly solvable — worst-case depth and uniqueness must match too.
        if a.depth != b.depth:
            discrepancies.append(
                f"depth: {epistemic.SOLVER_NAME}={a.depth} {z3_epistemic.SOLVER_NAME}={b.depth}"
            )
        if a_uniq.unique != b_uniq.unique:
            discrepancies.append(
                f"unique: {epistemic.SOLVER_NAME}={a_uniq.unique} "
                f"{z3_epistemic.SOLVER_NAME}={b_uniq.unique}"
            )

    evidence = (
        _epistemic_evidence(
            epistemic.SOLVER_NAME, epistemic.solver_version(),
            a.solvable, a.depth, a_uniq.unique,
        ),
        _epistemic_evidence(
            z3_epistemic.SOLVER_NAME, z3_epistemic.solver_version(),
            b.solvable, b.depth, b_uniq.unique,
        ),
    )
    return EpistemicCrossResult(
        agree=not discrepancies,
        solvable=a.solvable,
        depth=a.depth,
        unique=a_uniq.unique,
        equivalence=a_uniq.equivalence,
        world_count=b.world_count,
        evidence=evidence,
        plan=a.plan,
        discrepancies=discrepancies,
    )
