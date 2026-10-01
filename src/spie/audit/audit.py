"""Path B orchestration: re-decide the recognizable subset of the authored bank and compare each
formal verdict to the authored answer, honestly abstaining on everything else.

Every record gets exactly one status:

* **AGREE** — recognized, formally decided, and the formal verdict matches the authored answer.
* **DISAGREE** — recognized and formally decided, but the proof contradicts the authored answer.
  This is a genuine finding: a counter-model (or a validity proof) shows the authored answer wrong.
* **UNRECOGNIZED** — no deterministic recognizer matched. This is *abstention, not a pass*: it is
  counted apart from AGREE so coverage is never overstated.

Coverage is reported plainly (recognized / total). The point of the contribution is not to cover
the whole bank — most of it is open-world knowledge no solver can touch — but that every verdict it
*does* make is backed by a formal proof, and every DISAGREE is a checkable disproof.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass

from .bank import BankRecord, load_bank
from .problem import decide_problem
from .recognize import recognize

# The authored bank lives beside the engine, in the sibling puzzle-batch project.
_ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))
DEFAULT_BANK = os.path.join(_ENGINE_ROOT, "puzzle-batch", "output")


@dataclass(frozen=True)
class Verdict:
    """One recognized record's audit result (UNRECOGNIZED records are aggregated, not stored)."""

    uid: str
    category: str
    rec_type: str
    status: str  # "AGREE" | "DISAGREE"
    family: str
    frame: str
    formal_valid: bool
    answer_polarity: bool
    method: str
    checker: str
    detail: str
    question: str
    correct_answer: str


@dataclass(frozen=True)
class AuditReport:
    root: str
    total: int
    recognized: int
    agree: int
    disagree: int
    by_family: tuple[tuple[str, int, int], ...]  # (family, agree, disagree)
    by_frame: tuple[tuple[str, int, int], ...]  # (frame, agree, disagree)
    unrecognized_by_category: tuple[tuple[str, int], ...]
    verdicts: tuple[Verdict, ...]  # AGREE and DISAGREE, in bank order

    @property
    def disagreements(self) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if v.status == "DISAGREE")


def audit_record(record: BankRecord) -> Verdict | None:
    """Re-decide one record formally; ``None`` if no recognizer matched (abstention)."""
    prob = recognize(record)
    if prob is None:
        return None
    dec = decide_problem(prob)
    agrees = dec.valid == prob.answer_polarity
    return Verdict(
        uid=record.uid,
        category=record.category,
        rec_type=record.rec_type,
        status="AGREE" if agrees else "DISAGREE",
        family=prob.family,
        frame=prob.frame,
        formal_valid=dec.valid,
        answer_polarity=prob.answer_polarity,
        method=dec.method,
        checker=dec.checker,
        detail=dec.detail,
        question=record.question,
        correct_answer=record.correct_answer,
    )


def audit_bank(root: str | None = None) -> AuditReport:
    """Load the bank and audit every record, deterministically and in load order."""
    root = DEFAULT_BANK if root is None else root
    records = load_bank(root)
    verdicts: list[Verdict] = []
    fam: Counter[tuple[str, str]] = Counter()
    frame: Counter[tuple[str, str]] = Counter()
    unrec: Counter[str] = Counter()
    for record in records:
        v = audit_record(record)
        if v is None:
            unrec[record.category] += 1
            continue
        verdicts.append(v)
        fam[(v.family, v.status)] += 1
        frame[(v.frame, v.status)] += 1
    agree = sum(1 for v in verdicts if v.status == "AGREE")
    disagree = len(verdicts) - agree

    def _rollup(counter: Counter[tuple[str, str]]) -> tuple[tuple[str, int, int], ...]:
        keys = sorted({k for k, _ in counter})
        return tuple((k, counter[(k, "AGREE")], counter[(k, "DISAGREE")]) for k in keys)

    return AuditReport(
        root=root,
        total=len(records),
        recognized=len(verdicts),
        agree=agree,
        disagree=disagree,
        by_family=_rollup(fam),
        by_frame=_rollup(frame),
        unrecognized_by_category=tuple(sorted(unrec.items())),
        verdicts=tuple(verdicts),
    )


__all__ = ["AuditReport", "DEFAULT_BANK", "Verdict", "audit_bank", "audit_record"]
