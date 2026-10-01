"""Deterministic rendering of an :class:`~spie.audit.audit.AuditReport` — a plain-text summary for
the terminal and a canonical-JSON form for byte-reproducible artifacts/diffing.

Both renderers are pure functions of the report, and the report is a pure function of the bank, so
the same tree yields byte-identical output on every run. The JSON form reuses the project's
canonical :func:`spie.serialize.dumps` (sorted keys, trailing newline) so audit artifacts diff the
same way every other checked-in artifact does.
"""

from __future__ import annotations

from ..serialize import dumps
from .audit import AuditReport, Verdict


def _pct(part: int, whole: int) -> str:
    return "0.0%" if whole == 0 else f"{part / whole:.1%}"


def report_to_dict(report: AuditReport) -> dict:
    """A JSON-serializable view of the report. DISAGREEMENTS are kept in full (each is a finding to
    verify); AGREE verdicts are summarized by count only, to keep the artifact small and stable."""
    return {
        "root": report.root,
        "total": report.total,
        "recognized": report.recognized,
        "coverage": _pct(report.recognized, report.total),
        "agree": report.agree,
        "disagree": report.disagree,
        "by_family": [
            {"family": f, "agree": a, "disagree": d} for f, a, d in report.by_family
        ],
        "by_frame": [
            {"frame": f, "agree": a, "disagree": d} for f, a, d in report.by_frame
        ],
        "unrecognized_by_category": [
            {"category": c, "count": n} for c, n in report.unrecognized_by_category
        ],
        "disagreements": [_verdict_to_dict(v) for v in report.disagreements],
    }


def _verdict_to_dict(v: Verdict) -> dict:
    return {
        "uid": v.uid,
        "category": v.category,
        "rec_type": v.rec_type,
        "family": v.family,
        "frame": v.frame,
        "formal_valid": v.formal_valid,
        "answer_polarity": v.answer_polarity,
        "method": v.method,
        "checker": v.checker,
        "detail": v.detail,
        "question": v.question,
        "correct_answer": v.correct_answer,
    }


def render_json(report: AuditReport) -> str:
    """Canonical JSON text (sorted keys, trailing newline) — byte-reproducible across runs."""
    return dumps(report_to_dict(report))


def render_text(report: AuditReport, show_disagreements: bool = True) -> str:
    """Human-readable summary. Deterministic: every section is emitted in sorted/bank order."""
    lines: list[str] = []
    lines.append(f"bank audit - {report.root}")
    lines.append(
        f"records: {report.total}   "
        f"recognized: {report.recognized} ({_pct(report.recognized, report.total)})   "
        f"unrecognized: {report.total - report.recognized}"
    )
    lines.append(f"verdicts: AGREE {report.agree}   DISAGREE {report.disagree}")
    lines.append("")
    lines.append("by family:")
    for fam, a, d in report.by_family:
        lines.append(f"  {fam:<16} agree={a} disagree={d}")
    lines.append("")
    lines.append("by frame:")
    for fr, a, d in report.by_frame:
        lines.append(f"  {fr:<34} agree={a} disagree={d}")
    lines.append("")
    lines.append("unrecognized by category:")
    for cat, n in report.unrecognized_by_category:
        lines.append(f"  {cat:<12} {n}")
    if show_disagreements:
        lines.append("")
        lines.append(
            f"DISAGREEMENTS ({report.disagree}) - authored answers a formal proof contradicts:"
        )
        if not report.disagreements:
            lines.append("  (none)")
        for v in report.disagreements:
            lines.append(f"  {v.uid}  [{v.category}/{v.rec_type}]  {v.frame}")
            lines.append(f"    Q: {v.question}")
            lines.append(
                f"    authored: {v.correct_answer!r} (polarity={v.answer_polarity})   "
                f"formal: valid={v.formal_valid} via {v.method}/{v.checker}"
            )
            lines.append(f"    {v.detail}")
    return "\n".join(lines) + "\n"


__all__ = ["render_json", "render_text", "report_to_dict"]
