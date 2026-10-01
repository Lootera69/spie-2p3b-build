"""Render a :class:`~spie.questions.types.Question` as plain text.

Mirrors :func:`spie.presentation.render`: returns a list of lines (no trailing newlines) that the
CLI joins, so a question presents as a small human-readable document — prompt, options with the
answer marked, the proven answer, the proof-derived explanation, and the proof stamp naming the
decision procedure that established it. ASCII-only, like the rest of the presentation layer.
"""

from __future__ import annotations

from .types import Question, QuestionType


def render(question: Question) -> list[str]:
    qt = QuestionType.parse(question.qtype)
    lines: list[str] = []
    lines.append(f"[{question.category} / {qt.value}]  {question.id}")
    lines.append("=" * 72)
    lines.append("")
    lines.append(question.prompt)
    lines.append("")

    if question.options:
        letters = "ABCDEFGH"
        for i, opt in enumerate(question.options):
            mark = " (correct)" if opt.correct else ""
            lines.append(f"  {letters[i]}. {opt.text}{mark}")
        lines.append("")

    lines.append(f"Answer: {question.answer}")
    lines.append("")
    lines.append("Explanation:")
    for chunk in _wrap(question.explanation, 70):
        lines.append(f"  {chunk}")
    lines.append("")
    lines.append(
        f"Proof: {question.proof.method} via {question.proof.checker} "
        f"{question.proof.checker_version}"
    )
    lines.append(f"  {question.proof.detail}")
    if question.concepts:
        lines.append(f"Concepts: {', '.join(question.concepts)}")
    return lines


def _wrap(text: str, width: int) -> list[str]:
    """A tiny greedy word-wrap (kept local so rendering has no third-party dependency)."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines or [""]


__all__ = ["render"]
