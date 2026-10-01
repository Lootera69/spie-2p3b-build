"""Phase 4.5 — Hand-rolled deterministic MAP-Elites: a dependency-free quality-diversity archive.

The genome is a discrete symbolic :class:`~spie.ir.Puzzle`; the behavioral descriptor (the
*niche*) is a small integer tuple read from the existing :class:`~spie.quality.QualityVector`
— ``(difficulty band, |B0| bucket, plan-branching bucket, strategy-backtracks bucket)`` — so
niches are stable and documented. The fourth axis is the bounded-rational strategy solver's
physical ``backtracks`` (Phase 5.5): it separates *deceptive* puzzles (a myopic player is forced
to back out) from *clean* ones sharing the same difficulty/belief/branching cell, so the archive
keeps both instead of one crowding the other out. Fitness *within* a niche is a fixed weighted
blend of novelty + elegance (roadmap p5's within-niche ranking); MAP-Elites keeps the single best
genome per niche.

Correctness is never assumed: a candidate is admitted **only if** it is ``validate``-clean *and*
``verify(puzzle).ok`` *and* ``certify(puzzle)`` proves it solvable — the same hard gates the 20
hand puzzles pass, with no privileged path. A degenerate-but-valid puzzle simply lands in a
low-difficulty niche; an uncertifiable mutant is rejected outright.

Determinism is the discipline lifted to search: every choice (which occupied niche to expand,
which operator to apply, and the operator's own internal pick) is drawn from a single seeded
``random.Random(seed)`` over sorted candidates, and the archive serializes through
:func:`spie.serialize.dumps`. So the whole archive is **byte-reproducible** for a given
``(seeds, iterations, seed)`` — the archive-determinism property test is the standing oracle.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field, replace

from . import fingerprint
from .certificate import certify
from .context_policy import ContextualPolicy
from .decision import FrozenProposer
from .examples_src import BUILDERS
from .ir import Puzzle
from .operators import FAMILIES, OPERATORS
from .quality import QualityVector, descriptors, quality_to_json
from .serialize import (
    certificate_to_json,
    dumps,
    puzzle_from_json,
    puzzle_to_json,
    quality_from_json,
)
from .steering import SteeringPolicy
from .validate import validate
from .verify import GateStatus, verify

# Niche = (difficulty band 1-5, |B0| bucket, plan-branching bucket, strategy-backtracks bucket).
# Fixed, documented cut points so a puzzle always maps to the same cell across runs (a niche
# coordinate must be as reproducible as the certificate it summarizes).
_BELIEF_BUCKETS = (1, 3, 7)  # |B0| <=1 -> 0, <=3 -> 1, <=7 -> 2, else 3 (singleton = 0)
_BRANCH_BUCKETS = (1, 3)  # plan branch factor <=1 -> 0 (linear), <=3 -> 1, else 2
_BACKTRACK_BUCKETS = (0, 2)  # strategy backtracks ==0 -> 0 (clean), <=2 -> 1, else 2 (deceptive)

# Within-niche fitness = a fixed blend of novelty (distance to the corpus) and elegance
# (compact, all-load-bearing rules). Equal weights, provisional like the quality folds.
_W_NOVELTY = 0.5
_W_ELEGANCE = 0.5

Niche = tuple[int, int, int, int]

# operator function -> its invention family (structural / temporal / information / goal). Keyed by
# the function object (not its name) so a name collision across families could never silently
# mislabel a lineage record. Every member of OPERATORS appears here by construction.
_FAMILY_OF = {op: family for family, ops in FAMILIES.items() for op in ops}

def _bucket(value: int, boundaries: tuple[int, ...]) -> int:
    """The index of the first boundary ``value`` does not exceed, else ``len(boundaries)`` —
    a fixed monotone bucketer so niche coordinates are stable and documented."""
    for i, b in enumerate(boundaries):
        if value <= b:
            return i
    return len(boundaries)


def niche_of(quality: QualityVector) -> Niche:
    """The behavioral-descriptor cell for a puzzle: its difficulty band and the buckets of its
    belief size, plan branching, and the strategy solver's physical backtracks (the fourth axis
    separates deceptive puzzles from clean ones in the same difficulty cell) -- roadmap p5
    diversity axes, not raw fitness."""
    d = quality.difficulty
    return (
        d.band,
        _bucket(d.belief_count, _BELIEF_BUCKETS),
        _bucket(d.plan_branching, _BRANCH_BUCKETS),
        _bucket(quality.strategy.backtracks, _BACKTRACK_BUCKETS),
    )


def fitness_of(quality: QualityVector) -> float:
    """The within-niche ranking scalar: a fixed weighted blend of novelty and elegance."""
    return round(_W_NOVELTY * quality.novelty.score + _W_ELEGANCE * quality.elegance.score, 6)


@dataclass(frozen=True)
class Lineage:
    """How a mutant cell came to be (roadmap p14 lineage): the niche and content-digest of the
    parent elite it was mutated from, the operator that produced it and that operator's family,
    and its generation depth (a seed is generation 0; each mutation adds one). ``None`` on a seed
    cell, which has no parent."""

    parent_niche: Niche
    parent_digest: str
    operator: str
    family: str
    generation: int


@dataclass(frozen=True)
class Rejection:
    """A candidate that failed admission, retained as rejection history (roadmap p14): the content
    digest of the rejected puzzle, the ``reason`` it was turned away (a gate slug or
    ``"dominated"``), a short human-readable ``detail``, and the ``lineage`` of the mutation that
    produced it (``None`` for a rejected seed). Retained deterministically: the same seed yields
    the same history."""

    puzzle_digest: str
    reason: str
    detail: str
    lineage: Lineage | None


@dataclass(frozen=True)
class Cell:
    """One archived elite: the certified puzzle occupying a niche, its quality vector, the
    within-niche fitness it won the cell with, a digest of its certificate (proof identity), a
    content-address digest of the puzzle itself, and the lineage of the mutation that produced it
    (``None`` for a seed)."""

    niche: Niche
    puzzle: Puzzle
    quality: QualityVector
    fitness: float
    certificate_digest: str
    puzzle_digest: str
    lineage: Lineage | None = None


@dataclass(frozen=True)
class Admission:
    """The verdict of running a candidate through the hard gates. ``ok`` means it certified;
    a rejected candidate carries the ``reason`` (which gate turned it away), a ``detail`` naming the
    specific finding/gate/comparison, and no cell."""

    ok: bool
    reason: str
    cell: Cell | None = None
    detail: str = ""

@dataclass
class Archive:
    """The MAP-Elites grid: at most one elite per niche, plus the run parameters, a tally of
    admission outcomes, and the full rejection history (parallel to the tally — the integer tally
    counts every outcome; ``rejections`` records each rejected candidate). Mutated during a run;
    serialized canonically for byte-reproducibility."""

    seed: int
    iterations: int
    cells: dict[Niche, Cell] = field(default_factory=dict)
    tally: dict[str, int] = field(default_factory=dict)
    rejections: list[Rejection] = field(default_factory=list)

    def _count(self, reason: str) -> None:
        self.tally[reason] = self.tally.get(reason, 0) + 1


def _certificate_digest(puzzle: Puzzle) -> str:
    """A stable SHA-256 over the puzzle's canonical certificate bytes — a compact proof id that
    two runs reproduce exactly (it is a pure function of the puzzle)."""
    return hashlib.sha256(dumps(certificate_to_json(certify(puzzle))).encode("utf-8")).hexdigest()


def _puzzle_digest(puzzle: Puzzle) -> str:
    """A stable SHA-256 over the puzzle's own canonical JSON bytes — a content address distinct
    from the certificate digest (that addresses the *proof*; this addresses the *puzzle*). Two
    runs, or a write/read round-trip, reproduce it exactly."""
    return hashlib.sha256(dumps(puzzle_to_json(puzzle)).encode("utf-8")).hexdigest()


# Fields that carry a puzzle's *identity / presentation*, not its playable mechanics: the generated
# id, the human title, the provenance notes, and the seed stamp. Two puzzles differing only in these
# are the *same puzzle to play*, so the structural digest strips them before hashing.
_METADATA_FIELDS = ("id", "title", "notes", "seed")


def _structural_digest(puzzle: Puzzle) -> str:
    """A stable SHA-256 over the puzzle's *mechanics only* — its canonical JSON with the
    identity/presentation fields (:data:`_METADATA_FIELDS`) dropped. Distinct from
    :func:`_puzzle_digest` (which addresses the exact serialized puzzle, generated id and all):
    two puzzles that are mechanically identical but differ in id/title/notes/seed share one
    structural digest. This is the cross-run *uniqueness* key — "have we already produced this
    puzzle to play?" — and is never consulted for correctness (the gate alone decides that).
    ``puzzle_to_json`` returns a fresh dict, so popping mutates only this local copy."""
    data = puzzle_to_json(puzzle)
    for field_name in _METADATA_FIELDS:
        data.pop(field_name, None)
    return hashlib.sha256(dumps(data).encode("utf-8")).hexdigest()


def evaluate(
    puzzle: Puzzle, corpus: list | None = None, lineage: Lineage | None = None
) -> Admission:
    """Run a candidate through the hard correctness gates, in order, stopping at the first
    failure: ``validate`` clean -> ``verify(puzzle).ok`` -> ``certify`` solvable. Only a puzzle
    that clears all three earns a :class:`Cell`; the generator has no way to admit an unproven
    puzzle. ``corpus`` is the novelty neighbourhood (defaults to the built-in example corpus);
    ``lineage`` is stamped onto the resulting cell (``None`` for a seed)."""
    findings = validate(puzzle)
    if findings:
        return Admission(False, "invalid", detail=findings[0].rule)
    report = verify(puzzle)
    if not report.ok:
        failed = ",".join(g.name for g in report.gates if g.status is GateStatus.FAIL)
        return Admission(False, "verify-failed", detail=failed)
    if not certify(puzzle).solvable:
        return Admission(False, "unsolvable")
    quality = descriptors(puzzle, corpus)
    cell = Cell(
        niche=niche_of(quality),
        puzzle=puzzle,
        quality=quality,
        fitness=fitness_of(quality),
        certificate_digest=_certificate_digest(puzzle),
        puzzle_digest=_puzzle_digest(puzzle),
        lineage=lineage,
    )
    return Admission(True, "admitted", cell)


def place(
    archive: Archive, puzzle: Puzzle, corpus: list | None = None, lineage: Lineage | None = None
) -> Admission:
    """Gate ``puzzle`` and, if it certifies, place it in its niche — replacing the incumbent only
    when its within-niche fitness is strictly higher (ties keep the incumbent, so placement is
    order-deterministic). Records the outcome in the archive's tally, and appends a
    :class:`Rejection` (in addition to the tally) whenever the candidate is turned away or
    dominated, so the rejection history is retained alongside the integer counts."""
    adm = evaluate(puzzle, corpus, lineage)
    if not adm.ok or adm.cell is None:
        archive._count(adm.reason)
        archive.rejections.append(
            Rejection(_puzzle_digest(puzzle), adm.reason, adm.detail, lineage)
        )
        return adm
    cell = adm.cell
    incumbent = archive.cells.get(cell.niche)
    if incumbent is None:
        archive.cells[cell.niche] = cell
        archive._count("placed")
        return adm
    if cell.fitness > incumbent.fitness:
        archive.cells[cell.niche] = cell
        archive._count("replaced")
        return adm
    archive._count("dominated")
    archive.rejections.append(
        Rejection(
            cell.puzzle_digest,
            "dominated",
            f"fitness {cell.fitness} <= incumbent {incumbent.fitness}",
            lineage,
        )
    )
    return Admission(False, "dominated", cell, detail=f"niche {list(cell.niche)}")

def _corpus_fingerprints() -> list:
    """The fixed novelty neighbourhood: fingerprints of the 20 hand-authored corpus puzzles.
    Computed once per run so every candidate's novelty is measured against the same anchor."""
    return fingerprint.corpus_fingerprints([b() for b in BUILDERS])


# The context vector the contextual steering policy (spie.context_policy) reads: seven quality
# features of the parent elite, each normalized to [0, 1] so the ridge model and its confidence
# radius stay well-scaled. Index 0 is the bias term (a learnable per-operator base survival rate).
# This is the sole definition of the "decision model"'s input; the policy itself is
# dimension-generic and thesis-safe -- these features only steer WHICH operator to try, never
# acceptance.
_CONTEXT_DIM = 7


def _context_features(quality: QualityVector) -> tuple[float, ...]:
    """The parent elite's quality features as a fixed-length, ``[0, 1]``-scaled context vector for
    the contextual operator policy. A pure function of the quality vector (no RNG, no side effects),
    so it never perturbs byte-reproducibility and the ``policy=None`` path stays untouched."""
    d = quality.difficulty
    return (
        1.0,  # bias
        (d.band - 1) / 4.0,  # difficulty band 1..5 -> 0..1
        quality.novelty.score,  # novelty distance to the corpus, already [0, 1]
        quality.elegance.score,  # elegance, already [0, 1]
        quality.elegance.minimality_ratio,  # fraction of load-bearing rules, [0, 1]
        min(d.belief_count, 7) / 7.0,  # epistemic belief-set size, capped + normalized
        min(d.plan_branching, 7) / 7.0,  # plan branching factor, capped + normalized
    )


Policy = SteeringPolicy | ContextualPolicy | FrozenProposer


def evolve(
    seeds: list[Puzzle],
    iterations: int,
    seed: int = 0,
    policy: Policy | None = None,
    history: set[str] | None = None,
) -> Archive:
    """Run a bounded, fully-seeded MAP-Elites search and return the archive.

    Seed the grid by gating each puzzle in ``seeds``, then iterate ``iterations`` times: pick an
    occupied niche, pick an operator, apply it to that niche's elite, and gate the result. With the
    default ``policy=None`` both picks are uniform over the *sorted* candidates (the standing
    byte-reproducibility baseline); pass a :class:`~spie.steering.SteeringPolicy` and the two picks
    are instead driven by its discounted-UCB bandits, credited after each placement with the
    child's *survival* (``placed``/``replaced`` -> 1.0, else 0.0). A
    :class:`~spie.context_policy.ContextualPolicy` instead conditions the operator pick on the
    parent elite's quality features (a LinUCB "decision model") and additionally logs a *calibrated*
    survival confidence for later measurement. A :class:`~spie.decision.FrozenProposer` loads an
    offline-trained, frozen version of that model and only *proposes* ``argmax`` operator (it never
    learns online — its ``reward`` credits only its niche bandit). Either way the policy only steers
    *what to try* -- the ``validate -> verify -> certify`` gate in :func:`place` stays the sole
    authority, so a
    policy can never admit an unproven puzzle. Every draw comes from one ``random.Random(seed)``
    (the bandits are RNG-free and the context is a pure function of the parent), so the archive is
    byte-identical across runs with the same ``(seeds, iterations, seed)`` and policy history.
    Mutants are renamed with a deterministic per-iteration id so distinct cells never collide on an
    authored id.

    ``history`` opts into cross-run de-duplication (roadmap p0 "unique each time"). ``None`` (the
    default) leaves it *off* -- the rng stream, placements, tally and archive are byte-identical to
    the historical search. Any set turns it *on*: a copy seeds the ``seen`` set of
    :func:`_structural_digest` values, every admitted elite (seed or mutant) adds its structural
    digest to ``seen``, and any *mutant* whose structural digest is already in ``seen`` is rejected
    with reason ``"duplicate"`` (tallied + recorded) before the gate ever runs -- so a chained run
    fed the prior archive's :func:`archive_digests` cannot re-emit a mechanically identical puzzle.
    The de-dup check runs *after* the operator (the rng stream is untouched) and only ever
    *rejects*, never admits, so correctness stays wholly with the gate; a duplicate credits the
    policy 0.0, exactly like any other non-survival."""
    rng = random.Random(seed)
    corpus = _corpus_fingerprints()
    archive = Archive(seed=seed, iterations=iterations)
    seen = set(history) if history is not None else None  # None => cross-run de-dup off (default)
    for p in seeds:
        adm = place(archive, p, corpus)
        if seen is not None and adm.ok and adm.cell is not None:
            seen.add(_structural_digest(adm.cell.puzzle))
    op_by_name = {op.__name__: op for op in OPERATORS}
    for i in range(iterations):
        if not archive.cells:
            break
        context: tuple[float, ...] | None = None
        if policy is None:
            parent_niche = rng.choice(sorted(archive.cells))
            operator = rng.choice(OPERATORS)
            parent_cell = archive.cells[parent_niche]
        else:
            parent_niche = policy.choose_niche(archive.cells.keys())
            parent_cell = archive.cells[parent_niche]
            context = _context_features(parent_cell.quality)
            operator = op_by_name[policy.choose_operator(op_by_name.keys(), context)]
        child = operator(parent_cell.puzzle, rng)
        if child is None:
            archive._count("no-op")
            if policy is not None:
                policy.reward(parent_niche, operator.__name__, 0.0, context)
            continue
        child = replace(child, id=f"evo_{i:04d}")
        parent_gen = 0 if parent_cell.lineage is None else parent_cell.lineage.generation
        lineage = Lineage(
            parent_niche=parent_niche,
            parent_digest=parent_cell.puzzle_digest,
            operator=operator.__name__,
            family=_FAMILY_OF[operator],
            generation=parent_gen + 1,
        )
        if seen is not None and _structural_digest(child) in seen:
            archive._count("duplicate")
            archive.rejections.append(
                Rejection(
                    _puzzle_digest(child), "duplicate", "structural match in history", lineage
                )
            )
            if policy is not None:
                policy.reward(parent_niche, operator.__name__, 0.0, context)
            continue
        adm = place(archive, child, corpus, lineage)
        if seen is not None and adm.ok and adm.cell is not None:
            seen.add(_structural_digest(adm.cell.puzzle))
        if policy is not None:
            policy.reward(parent_niche, operator.__name__, 1.0 if adm.ok else 0.0, context)
    return archive


def archive_digests(archive: Archive) -> set[str]:
    """The :func:`_structural_digest` of every elite currently in ``archive`` -- the set to feed
    forward as :func:`evolve`'s ``history`` so a later run does not re-emit a mechanically identical
    puzzle. Keyed on the *structural* digest (id/title/notes/seed stripped), so a puzzle counts as
    already-produced regardless of the generated id it happens to wear."""
    return {_structural_digest(cell.puzzle) for cell in archive.cells.values()}


def _lineage_to_json(lineage: Lineage | None) -> dict | None:
    """A plain-data view of a lineage record, or ``None`` for a seed cell."""
    if lineage is None:
        return None
    return {
        "parent_niche": list(lineage.parent_niche),
        "parent_digest": lineage.parent_digest,
        "operator": lineage.operator,
        "family": lineage.family,
        "generation": lineage.generation,
    }


def _lineage_from_json(d: dict | None) -> Lineage | None:
    """Inverse of :func:`_lineage_to_json`."""
    if d is None:
        return None
    return Lineage(
        parent_niche=tuple(d["parent_niche"]),
        parent_digest=d["parent_digest"],
        operator=d["operator"],
        family=d["family"],
        generation=d["generation"],
    )


def archive_to_json(archive: Archive) -> dict:
    """A plain-data, canonical view of the archive: cells sorted by niche so
    :func:`spie.serialize.dumps` yields byte-identical text for byte-identical archives. Each cell
    carries its content-address ``puzzle_digest`` and ``lineage`` (roadmap p14), and the whole
    archive carries its ``rejections`` history in the deterministic order they occurred."""
    return {
        "seed": archive.seed,
        "iterations": archive.iterations,
        "tally": archive.tally,
        "cells": [
            {
                "niche": list(niche),
                "fitness": cell.fitness,
                "certificate_digest": cell.certificate_digest,
                "puzzle_digest": cell.puzzle_digest,
                "lineage": _lineage_to_json(cell.lineage),
                "quality": quality_to_json(cell.quality),
                "puzzle": puzzle_to_json(cell.puzzle),
            }
            for niche, cell in sorted(archive.cells.items())
        ],
        "rejections": [
            {
                "puzzle_digest": r.puzzle_digest,
                "reason": r.reason,
                "detail": r.detail,
                "lineage": _lineage_to_json(r.lineage),
            }
            for r in archive.rejections
        ],
    }


def archive_from_json(data: dict) -> Archive:
    """Rebuild an :class:`Archive` from its canonical JSON view — the inverse of
    :func:`archive_to_json`, and the read-back the LEARNING stage needs (an archive was previously
    write-only). Reuses :func:`spie.serialize.puzzle_from_json` and
    :func:`spie.serialize.quality_from_json`, so a persisted archive reconstructs exactly:
    ``archive_to_json(archive_from_json(j))`` reproduces ``j`` byte-for-byte."""
    archive = Archive(
        seed=data["seed"],
        iterations=data["iterations"],
        tally=dict(data.get("tally", {})),
    )
    for c in data["cells"]:
        niche = tuple(c["niche"])
        archive.cells[niche] = Cell(
            niche=niche,
            puzzle=puzzle_from_json(c["puzzle"]),
            quality=quality_from_json(c["quality"]),
            fitness=c["fitness"],
            certificate_digest=c["certificate_digest"],
            puzzle_digest=c["puzzle_digest"],
            lineage=_lineage_from_json(c.get("lineage")),
        )
    archive.rejections = [
        Rejection(
            puzzle_digest=r["puzzle_digest"],
            reason=r["reason"],
            detail=r["detail"],
            lineage=_lineage_from_json(r.get("lineage")),
        )
        for r in data.get("rejections", [])
    ]
    return archive


__all__ = [
    "Niche",
    "Cell",
    "Admission",
    "Archive",
    "Lineage",
    "Rejection",
    "niche_of",
    "fitness_of",
    "evaluate",
    "place",
    "evolve",
    "archive_digests",
    "archive_to_json",
    "archive_from_json",
]
