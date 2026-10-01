"""Path B — a deterministic, LLM-free formal auditor over the authored question bank.

The pipeline is a straight line, each stage pure and side-effect-free:

    load_bank            (bank.py)       batch-*.json -> ordered BankRecords
    recognize            (recognize.py)  BankRecord   -> Problem | None  (abstain)
    decide_problem       (problem.py)    Problem      -> Decision        (formal solver)
    audit_bank           (audit.py)      -> AuditReport (AGREE / DISAGREE / UNRECOGNIZED)
    render_text/json     (report.py)     -> byte-reproducible output

No language model touches parsing or deciding. Recognizers abstain unless certain, so coverage is
only ever understated; a DISAGREE is a formal disproof of an authored answer, not a guess.
"""

from __future__ import annotations

from .audit import DEFAULT_BANK, AuditReport, Verdict, audit_bank, audit_record
from .bank import BankRecord, load_bank, normalize
from .categorical import CatStmt, CatVerdict, decide_categorical
from .problem import Decision, Problem, decide_problem
from .recognize import recognize
from .report import render_json, render_text, report_to_dict

__all__ = [
    "AuditReport",
    "BankRecord",
    "CatStmt",
    "CatVerdict",
    "DEFAULT_BANK",
    "Decision",
    "Problem",
    "Verdict",
    "audit_bank",
    "audit_record",
    "decide_categorical",
    "decide_problem",
    "load_bank",
    "normalize",
    "recognize",
    "render_json",
    "render_text",
    "report_to_dict",
]
