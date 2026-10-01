"""Canonical JSON <-> :class:`~spie.questions.types.Question` serialization.

Mirrors :mod:`spie.serialize`: the same canonical :func:`~spie.serialize.dumps` (sorted keys, fixed
separators) is reused so a question re-serializes byte-identically. That determinism is what lets a
question set be pinned by hash, exactly as the puzzle corpus is.
"""

from __future__ import annotations

from typing import Any

from .types import Option, Proof, Question


def _proof_to_json(p: Proof) -> dict[str, Any]:
    return {
        "method": p.method,
        "checker": p.checker,
        "checker_version": p.checker_version,
        "detail": p.detail,
    }


def _proof_from_json(d: dict[str, Any]) -> Proof:
    return Proof(
        method=d["method"],
        checker=d["checker"],
        checker_version=d["checker_version"],
        detail=d["detail"],
    )


def _option_to_json(o: Option) -> dict[str, Any]:
    return {"text": o.text, "correct": o.correct, "reason": o.reason}


def _option_from_json(d: dict[str, Any]) -> Option:
    return Option(text=d["text"], correct=d["correct"], reason=d["reason"])


def question_to_json(q: Question) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": q.id,
        "category": q.category,
        "qtype": q.qtype,
        "prompt": q.prompt,
        "answer": q.answer,
        "explanation": q.explanation,
        "proof": _proof_to_json(q.proof),
        "seed": q.seed,
        "concepts": list(q.concepts),
    }
    if q.options:  # omit for fill-in-the-blank so its serialization stays minimal
        d["options"] = [_option_to_json(o) for o in q.options]
    return d


def question_from_json(d: dict[str, Any]) -> Question:
    return Question(
        id=d["id"],
        category=d["category"],
        qtype=d["qtype"],
        prompt=d["prompt"],
        answer=d["answer"],
        explanation=d["explanation"],
        proof=_proof_from_json(d["proof"]),
        seed=d["seed"],
        options=tuple(_option_from_json(o) for o in d.get("options", [])),
        concepts=tuple(d.get("concepts", [])),
    )


__all__ = ["question_from_json", "question_to_json"]
