"""The verification suite — the roadmap's design-quality gates, each an auditable check.

Where the :class:`~spie.ir.Certificate` proves a puzzle is *solvable, unique, and conformant*
(corroborated by two solvers — see :mod:`spie.crosscheck`), this module audits the puzzle's
*design*: that its goal is reachable and cross-validated, that it honours its own uniqueness
declaration, that the intended (minimal-length) solution has no unintended cheaper shortcut,
that no *silent* dead-end contradicts the declared trap policy, that every retained element is
load-bearing, and that certification is byte-reproducible.

Each gate returns a :class:`GateResult` carrying a PASS/FAIL/INFO status and structured
:class:`~spie.validate.Finding` records (the same shape static validation emits), so the whole
report is machine-auditable. ``INFO`` marks a gate that is deferred rather than skipped: the
concept-relevance gate is INFO for a hand-authored puzzle (no concept provenance to ablate) and
becomes a real PASS/FAIL check once a *generated* puzzle carries a concept -> action-name map.

The determinism gate certifies by *running* :func:`spie.certificate.certify` twice and
comparing canonical bytes, which is why this module sits above ``certificate``: the suite is
never invoked from inside ``certify`` (that would recurse).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from . import epistemic, search
from .certificate import certify
from .chance import ChanceCrossResult, chance_cross_solve
from .conformance import check_plan_conformance
from .crosscheck import (
    CrossResult,
    EpistemicCrossResult,
    cross_solve,
    epistemic_cross_solve,
)
from .ir import Puzzle
from .operationalize import Provenance
from .search import ReachGraph
from .serialize import certificate_to_json, dumps
from .validate import Finding, validate


class GateStatus(str, Enum):
    """A gate either holds (PASS), is violated (FAIL), or is deferred (INFO)."""

    PASS = "pass"
    FAIL = "fail"
    INFO = "info"


@dataclass(frozen=True)
class GateResult:
    """One verification gate's verdict: a stable ``name``, a status, findings, and detail."""

    name: str
    status: GateStatus
    findings: tuple[Finding, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class VerifyReport:
    """The full verification suite result for one puzzle — one :class:`GateResult` per gate."""

    puzzle_id: str
    gates: tuple[GateResult, ...]

    @property
    def ok(self) -> bool:
        """True iff no gate FAILed (INFO/deferred gates never fail the report)."""
        return all(g.status is not GateStatus.FAIL for g in self.gates)

    @property
    def findings(self) -> list[Finding]:
        return [f for g in self.gates for f in g.findings]


# --- individual gates ----------------------------------------------------------------


def _reachability_gate(puzzle: Puzzle, cross: CrossResult) -> GateResult:
    if not cross.solvable:
        h = puzzle.objective.max_horizon
        return GateResult(
            "reachability",
            GateStatus.FAIL,
            (Finding("unreachable-goal", f"goal not reachable within horizon {h}"),),
        )
    if not cross.agree:
        return GateResult(
            "reachability",
            GateStatus.FAIL,
            (Finding("solver-disagreement", "; ".join(cross.discrepancies)),),
        )
    return GateResult(
        "reachability",
        GateStatus.PASS,
        detail=f"goal reachable at horizon {cross.horizon}; Z3, search and ASP agree",
    )


def _uniqueness_gate(puzzle: Puzzle, cross: CrossResult) -> GateResult:
    requires = puzzle.objective.requires_unique
    if requires and not cross.unique:
        msg = "requires_unique is set but a second minimal solution exists"
        return GateResult(
            "uniqueness", GateStatus.FAIL, (Finding("uniqueness-violated", msg),)
        )
    return GateResult(
        "uniqueness",
        GateStatus.PASS,
        detail=f"requires_unique={requires}; actual unique={cross.unique}",
    )


def _shortcut_gate(puzzle: Puzzle) -> GateResult:
    by_length = search.solve(puzzle)
    by_cost = search.solve_min_cost(puzzle)
    if not by_length.solvable:
        return GateResult("shortcut", GateStatus.PASS, detail="unsolvable; nothing to shortcut")
    if by_cost.cost < by_length.cost:
        msg = (
            f"a cheaper path (cost {by_cost.cost}) undercuts the minimal-length "
            f"solution (cost {by_length.cost})"
        )
        return GateResult("shortcut", GateStatus.FAIL, (Finding("cost-shortcut", msg),))
    return GateResult(
        "shortcut",
        GateStatus.PASS,
        detail=f"minimal-length solution is cost-optimal (cost {by_length.cost})",
    )


def _dead_state_gate(puzzle: Puzzle, graph: ReachGraph) -> GateResult:
    traps = graph.traps()
    policy = puzzle.objective.trap_policy
    caveat = " (scan incomplete: state bound hit)" if graph.truncated else ""
    if policy == "signaled" and traps:
        findings = tuple(
            Finding("silent-trap", f"live state {graph.states[t]} cannot reach the goal")
            for t in sorted(traps)
        )
        return GateResult(
            "dead-state",
            GateStatus.FAIL,
            findings,
            detail=f"trap_policy=signaled but {len(traps)} silent trap(s) present{caveat}",
        )
    return GateResult(
        "dead-state",
        GateStatus.PASS,
        detail=f"trap_policy={policy}; {len(traps)} trap(s){caveat}",
    )


def _minimality_gate(puzzle: Puzzle) -> GateResult:
    baseline = search.signature(puzzle)
    findings = tuple(
        Finding("redundant-element", f"{label} not load-bearing")
        for label, variant in search.ablations(puzzle)
        if search.signature(variant) == baseline
    )
    if findings:
        return GateResult("minimality", GateStatus.FAIL, findings)
    detail = (
        f"all {len(puzzle.actions)} action(s), {len(puzzle.edges)} edge(s) and every clue "
        "are load-bearing"
    )
    return GateResult("minimality", GateStatus.PASS, detail=detail)


def _determinism_gate(puzzle: Puzzle) -> GateResult:
    first = dumps(certificate_to_json(certify(puzzle)))
    second = dumps(certificate_to_json(certify(puzzle)))
    if first != second:
        msg = "certificate bytes differ across two runs"
        return GateResult("determinism", GateStatus.FAIL, (Finding("nondeterministic", msg),))
    return GateResult("determinism", GateStatus.PASS, detail="byte-identical across two runs")


def inert_concepts(puzzle: Puzzle, provenance: Provenance) -> tuple[str, ...]:
    """The source concepts that are *not* load-bearing, in sorted order.

    A concept is *used* only if removing all the actions it contributed changes the puzzle's
    behavioral :func:`spie.search.signature` (solvability, minimal solution structure, or
    reachable-state shape) — the roadmap-p4 criterion. A concept whose removal leaves the
    signature identical contributed nothing the solver can observe. This is the shared kernel of
    the concept-relevance gate and the pipeline's Ablate stage (:func:`spie.invent.invent`), so
    both prune by exactly the same standard :func:`_minimality_gate` uses for single elements."""
    baseline = search.signature(puzzle)
    inert: list[str] = []
    for concept in sorted(provenance):
        names = set(provenance[concept])
        variant = replace(
            puzzle, actions=tuple(a for a in puzzle.actions if a.name not in names)
        )
        if search.signature(variant) == baseline:
            inert.append(concept)
    return tuple(inert)


def concept_relevance(puzzle: Puzzle, provenance: Provenance) -> tuple[Finding, ...]:
    """Report the source concepts of ``puzzle`` that are not load-bearing as ``inert-concept``
    findings (see :func:`inert_concepts` for the criterion). An empty result means every concept
    the generator kept genuinely earns its place — the roadmap-p4 relevance property."""
    return tuple(
        Finding(
            "inert-concept",
            f"concept {concept!r} contributes {len(provenance[concept])} action(s) whose "
            "removal leaves the puzzle's behavior unchanged",
        )
        for concept in inert_concepts(puzzle, provenance)
    )


def _concept_relevance_gate(puzzle: Puzzle, provenance: Provenance | None) -> GateResult:
    """Real gate for a generated puzzle carrying provenance; deferred (INFO) otherwise.

    A hand-authored puzzle has no concept provenance to ablate, so this stays INFO exactly as
    before — the 20-corpus verify reports are byte-identical. A generated puzzle carries a
    concept -> action-name map, and every one of its source concepts must be load-bearing."""
    if provenance is None:
        return GateResult(
            "concept-relevance",
            GateStatus.INFO,
            detail="deferred to the semantics phase — no concepts exist to ablate yet",
        )
    findings = concept_relevance(puzzle, provenance)
    if findings:
        return GateResult(
            "concept-relevance",
            GateStatus.FAIL,
            findings,
            detail=f"{len(findings)} of {len(provenance)} source concept(s) not load-bearing",
        )
    return GateResult(
        "concept-relevance",
        GateStatus.PASS,
        detail=f"all {len(provenance)} source concept(s) are load-bearing",
    )


# --- Phase-3 gates: the declared information model, sensing necessity, and the reduction
# --- anchor. These run for every puzzle; they are trivially satisfied by a fully-observable
# --- one (no info model to check, no senses to ablate, and the epistemic plan is already the
# --- linear trace), and carry real content only once hidden state is declared. -------------

# The static-validation rule slugs that concern the partial-information model (see
# spie.validate._validate_information). A finding under any of these means the declared
# observability / belief / sensing model is internally inconsistent.
_INFO_RULES = frozenset(
    {
        "hidden-without-belief",
        "negative-delay",
        "delayed-without-delay",
        "belief-unknown-var",
        "belief-not-hidden",
        "empty-belief-support",
        "belief-out-of-range",
        "belief-initial-not-in-support",
        "senses-unknown-var",
        # Item-4 chance layer: a malformed initial_dist is an information-model violation too.
        "dist-without-belief",
        "dist-support-mismatch",
        "dist-negative-weight",
        "dist-not-normalized",
    }
)


def _observability_gate(puzzle: Puzzle) -> GateResult:
    """The declared information model is internally consistent — every static-validation
    finding that concerns observability, belief support, or sensing must be absent."""
    findings = tuple(f for f in validate(puzzle) if f.rule in _INFO_RULES)
    if findings:
        return GateResult(
            "observability",
            GateStatus.FAIL,
            findings,
            detail=f"{len(findings)} information-model violation(s)",
        )
    return GateResult(
        "observability",
        GateStatus.PASS,
        detail="declared observability / belief / sensing model is consistent",
    )


def _information_necessity_gate(puzzle: Puzzle) -> GateResult:
    """Every declared sense is load-bearing: removing any one action's ``senses`` must break
    strong-solvability. A sense that can be dropped while the puzzle stays strongly solvable is
    redundant information — the puzzle does not actually require observing it."""
    sensing_actions = [a for a in puzzle.actions if a.senses]
    if not sensing_actions:
        return GateResult(
            "information-necessity",
            GateStatus.PASS,
            detail="no sensing actions to ablate",
        )
    findings = []
    for target in sensing_actions:
        blinded = replace(target, senses=())
        variant = replace(
            puzzle,
            actions=tuple(blinded if a is target else a for a in puzzle.actions),
        )
        if epistemic.solve_strong(variant).solvable:
            findings.append(
                Finding(
                    "redundant-sense",
                    f"action {target.name!r} still strong-solvable with its sense removed",
                )
            )
    if findings:
        return GateResult("information-necessity", GateStatus.FAIL, tuple(findings))
    return GateResult(
        "information-necessity",
        GateStatus.PASS,
        detail=f"all {len(sensing_actions)} sensing action(s) are load-bearing",
    )


def _epistemic_reduction_gate(puzzle: Puzzle) -> GateResult:
    """The reduction anchor, audited as a gate. A fully-observable puzzle's canonical
    contingent plan must be *linear* and recover exactly the explicit-state canonical trace —
    the epistemic layer must collapse to Phase-2 semantics when nothing is hidden. A puzzle
    that *declares* hidden state, conversely, must genuinely branch on observation: a strong
    plan that never senses means the information model is vacuous."""
    plan = epistemic.canonical_plan(puzzle)
    if not puzzle.initial_belief:
        sol = search.canonical_solution(puzzle)
        if not sol.solvable:
            return GateResult(
                "epistemic-reduction",
                GateStatus.PASS,
                detail="fully-observable and unsolvable; nothing to reduce",
            )
        linear = plan.linear_trace() if plan is not None else None
        if linear != list(sol.trace):
            msg = "fully-observable plan does not reduce to the canonical linear trace"
            return GateResult(
                "epistemic-reduction",
                GateStatus.FAIL,
                (Finding("reduction-violated", msg),),
            )
        return GateResult(
            "epistemic-reduction",
            GateStatus.PASS,
            detail="epistemic plan collapses to the linear certificate trace",
        )
    if plan is None:
        return GateResult(
            "epistemic-reduction",
            GateStatus.PASS,
            detail="hidden state declared but puzzle is unsolvable (handled by reachability)",
        )
    if plan.branch_factor() < 2:
        msg = "hidden state declared but the certified plan never branches on an observation"
        return GateResult(
            "epistemic-reduction",
            GateStatus.FAIL,
            (Finding("vacuous-information-model", msg),),
        )
    return GateResult(
        "epistemic-reduction",
        GateStatus.PASS,
        detail=f"contingent plan branches on observation (branch factor {plan.branch_factor()})",
    )


# --- epistemic-mode analogues of the reachability / uniqueness / conformance gates ---------


def _epistemic_reachability_gate(puzzle: Puzzle, cross: EpistemicCrossResult) -> GateResult:
    if not cross.solvable:
        h = puzzle.objective.max_horizon
        return GateResult(
            "reachability",
            GateStatus.FAIL,
            (Finding("unreachable-goal", f"goal not strongly reachable within horizon {h}"),),
        )
    if not cross.agree:
        return GateResult(
            "reachability",
            GateStatus.FAIL,
            (Finding("solver-disagreement", "; ".join(cross.discrepancies)),),
        )
    return GateResult(
        "reachability",
        GateStatus.PASS,
        detail=f"goal strongly reachable at depth {cross.depth}; belief-search and Z3 agree",
    )


def _epistemic_uniqueness_gate(puzzle: Puzzle, cross: EpistemicCrossResult) -> GateResult:
    requires = puzzle.objective.requires_unique
    if requires and not cross.unique:
        msg = "requires_unique is set but a second minimal contingent plan exists"
        return GateResult(
            "uniqueness", GateStatus.FAIL, (Finding("uniqueness-violated", msg),)
        )
    return GateResult(
        "uniqueness",
        GateStatus.PASS,
        detail=f"requires_unique={requires}; actual unique={cross.unique}",
    )


def _epistemic_conformance_gate(puzzle: Puzzle, cross: EpistemicCrossResult) -> GateResult:
    """Replay the certified contingent plan over every world of ``B0``: it must reach the goal
    on all of them and be uniform (branch only on observed history). This is the gate form of
    the fairness theorem — a non-uniform or goal-missing plan fails here rather than passing
    silently."""
    pc = check_plan_conformance(puzzle, cross.plan)
    if not pc.uniform:
        return GateResult(
            "conformance",
            GateStatus.FAIL,
            (Finding("non-uniform-plan", "plan decisions depend on unobserved (hidden) state"),),
            detail=pc.detail,
        )
    if not pc.reached_goal_all:
        return GateResult(
            "conformance",
            GateStatus.FAIL,
            (Finding("plan-goal-miss", "plan does not reach the goal on every B0 world"),),
            detail=pc.detail,
        )
    return GateResult(
        "conformance",
        GateStatus.PASS,
        detail=f"uniform plan reaches the goal on all {len(pc.world_replays)} B0 world(s)",
    )


# --- Item-4 chance-mode analogues: best-effort success under a random initial state. The
# --- certified quantity is the exact optimal expected success probability P, cross-checked
# --- three ways (belief DP P_A, per-world replay P_B, reachability upper bound U). ----------


def _chance_reachability_gate(puzzle: Puzzle, cross: ChanceCrossResult) -> GateResult:
    """The chance analogue of the reachability gate. The certified success probability ``P`` must
    be positive, exactly agreed by the two independent tallies (belief-DP ``P_A`` == replay
    ``P_B``), and bounded by the reachability upper bound (``P <= U``). A node-cap truncation or a
    reachability-solver split is surfaced here too — a discrepancy is a hard FAIL, never
    smoothed."""
    findings: list[Finding] = []
    if cross.probability == 0:
        findings.append(Finding("chance-unwinnable", "no initial world is winnable (P == 0)"))
    if cross.probability != cross.probability_replay:
        findings.append(
            Finding(
                "probability-disagreement",
                f"belief-DP P_A={cross.probability} != replay P_B={cross.probability_replay}",
            )
        )
    if cross.probability > cross.upper_bound:
        findings.append(
            Finding(
                "probability-exceeds-reachable",
                f"P={cross.probability} exceeds reachable upper bound U={cross.upper_bound}",
            )
        )
    if cross.truncated:
        findings.append(
            Finding(
                "belief-dp-truncated",
                "belief DP hit the node cap; P may be under-approximate",
            )
        )
    if cross.reachability_disagreement:
        findings.append(
            Finding("solver-disagreement", "reachability solvers disagree on a pinned world")
        )
    if findings:
        return GateResult("reachability", GateStatus.FAIL, tuple(findings))
    return GateResult(
        "reachability",
        GateStatus.PASS,
        detail=(
            f"P={cross.probability} (belief DP == replay), bounded by U={cross.upper_bound}; "
            "reachability solvers agree"
        ),
    )


def _chance_conformance_gate(puzzle: Puzzle, cross: ChanceCrossResult) -> GateResult:
    """The chance analogue of the conformance gate, made *best-effort-tolerant*: the certified
    plan need not reach the goal on every ``B0`` world (a ``P < 1`` puzzle is precisely one it
    cannot), but it must still be *uniform* — every decision branches only on observed history,
    never on hidden state the player cannot see (no clairvoyance). A non-uniform plan fails here
    rather than inflating ``P`` silently."""
    if not cross.uniform:
        return GateResult(
            "conformance",
            GateStatus.FAIL,
            (Finding("non-uniform-plan", "plan decisions depend on unobserved (hidden) state"),),
        )
    winners = sum(1 for wr in cross.world_replays if wr.reached_goal)
    return GateResult(
        "conformance",
        GateStatus.PASS,
        detail=(
            f"uniform best-effort plan; goal reached on {winners} of "
            f"{len(cross.world_replays)} B0 world(s) (P={cross.probability})"
        ),
    )


def verify(puzzle: Puzzle, provenance: Provenance | None = None) -> VerifyReport:
    """Run every verification gate and collect the results into a :class:`VerifyReport`.

    The suite branches on hidden state exactly as :func:`spie.certificate.certify` does. A
    puzzle with a non-empty :attr:`~spie.ir.Puzzle.initial_dist` runs the Item-4 *chance* mode
    gates (best-effort reachability of the exact optimal ``P`` and uniformity-only conformance);
    otherwise a fully-observable puzzle runs the Phase-1/2 concrete gates (reachability /
    uniqueness / shortcut / dead-state / minimality) and a puzzle with hidden initial state runs
    their epistemic analogues, driven by :func:`spie.crosscheck.epistemic_cross_solve` and the
    certified contingent plan. All modes then run the shared Phase-3 gates (observability,
    information-necessity, epistemic-reduction) and the always-on determinism and
    concept-relevance gates, so the report shape is stable across modes.

    ``provenance`` (a concept -> action-name map from
    :func:`spie.operationalize.operationalize_traced`) turns the concept-relevance gate from a
    deferred INFO into a real check that every source concept is load-bearing. Omit it — as every
    hand-authored caller does — and that gate stays INFO, so the report is unchanged."""
    if puzzle.initial_dist:
        chance_cross = chance_cross_solve(puzzle)
        mode_gates: tuple[GateResult, ...] = (
            _chance_reachability_gate(puzzle, chance_cross),
            _chance_conformance_gate(puzzle, chance_cross),
        )
    elif puzzle.initial_belief:
        cross = epistemic_cross_solve(puzzle)
        mode_gates = (
            _epistemic_reachability_gate(puzzle, cross),
            _epistemic_uniqueness_gate(puzzle, cross),
            _epistemic_conformance_gate(puzzle, cross),
        )
    else:
        cross_fo = cross_solve(puzzle)
        graph = search.explore(puzzle)
        mode_gates = (
            _reachability_gate(puzzle, cross_fo),
            _uniqueness_gate(puzzle, cross_fo),
            _shortcut_gate(puzzle),
            _dead_state_gate(puzzle, graph),
            _minimality_gate(puzzle),
        )
    gates = mode_gates + (
        _observability_gate(puzzle),
        _information_necessity_gate(puzzle),
        _epistemic_reduction_gate(puzzle),
        _determinism_gate(puzzle),
        _concept_relevance_gate(puzzle, provenance),
    )
    return VerifyReport(puzzle.id, gates)


__all__ = ["GateStatus", "GateResult", "VerifyReport", "concept_relevance", "verify"]
