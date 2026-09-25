"""Report shape and scoring — the presentation layer over :mod:`spie.validate`.

Mirrors the BrainBloom Forge report we took as a template: a numeric quality score plus a
histogram of findings by rule ("reason"). The score starts at 100 and loses 8 points per
finding, floored at 0 — a blunt but stable signal that ranks clean puzzles above sloppy
ones. This module is pure data massaging; it neither validates nor solves.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .validate import Finding

PENALTY_PER_FINDING = 8
MAX_SCORE = 100


@dataclass
class Report:
    """A scored summary of a puzzle's static validation."""

    puzzle_id: str
    score: int
    findings: list[Finding]
    histogram: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.findings


def score_findings(findings: list[Finding]) -> int:
    """100 minus a flat penalty per finding, floored at zero."""
    return max(0, MAX_SCORE - PENALTY_PER_FINDING * len(findings))


def build_report(puzzle_id: str, findings: list[Finding]) -> Report:
    """Assemble a :class:`Report` from validation findings."""
    histogram = dict(sorted(Counter(f.rule for f in findings).items()))
    return Report(
        puzzle_id=puzzle_id,
        score=score_findings(findings),
        findings=list(findings),
        histogram=histogram,
    )


__all__ = ["Report", "build_report", "score_findings", "PENALTY_PER_FINDING", "MAX_SCORE"]
