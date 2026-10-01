"""Domain plug-ins: each turns a formal micro-theory into proven-answer questions.

A *domain* owns one category (``sets``, ``arithmetic``, ...). It knows which
:class:`~spie.questions.types.QuestionType` shapes it can pose with a *proven* answer
(:attr:`Domain.supported`) and builds one concrete question from a seed
(:meth:`Domain.build`). The decision procedure lives in the domain, so the proof is produced
where the theory is — never by a shared oracle that could drift from it.

Determinism is a hard requirement: :func:`derive_rng` maps ``(category, qtype, seed)`` to a
``random.Random`` through SHA-256, so a given seed always yields the byte-identical question,
independent of the Python build (unlike the salted built-in :func:`hash`).
"""

from __future__ import annotations

import hashlib
import random

from ..prover import PYTHON, Z3, python_version, z3_version
from ..types import Option, Proof, Question, QuestionType


def derive_rng(category: str, qtype: QuestionType, seed: int) -> random.Random:
    """A deterministic ``random.Random`` keyed by category, question type and seed.

    Built from a SHA-256 digest rather than ``hash((...))`` so the stream is stable across
    interpreter runs and machines — the same reproducibility guarantee the puzzle engine keeps."""
    material = f"{category}|{qtype.value}|{seed}".encode()
    key = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return random.Random(key)


class Domain:
    """Base class for a category's question builder.

    Subclasses set :attr:`name` / :attr:`supported` and implement :meth:`build`. The helpers here
    just stamp a :class:`Proof` with the right checker identity, so a domain never has to remember
    whether it proved by Z3 or by exact computation."""

    name: str = ""
    supported: frozenset[QuestionType] = frozenset()
    # Question types this domain can also render as a real-world "skin" over the same proof
    # (``style="realistic"``). Empty means the domain only poses the abstract form.
    realistic: frozenset[QuestionType] = frozenset()

    def build(
        self,
        qtype: QuestionType,
        qid: str,
        seed: int,
        rng: random.Random,
        words: tuple[str, ...],
        style: str = "plain",
    ) -> Question:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- proof stamps ---------------------------------------------------------

    @staticmethod
    def z3_proof(method: str, detail: str) -> Proof:
        return Proof(method=method, checker=Z3, checker_version=z3_version(), detail=detail)

    @staticmethod
    def py_proof(method: str, detail: str) -> Proof:
        return Proof(method=method, checker=PYTHON, checker_version=python_version(), detail=detail)

    # -- option helpers -------------------------------------------------------

    @staticmethod
    def tf_options(answer: bool, why_true: str, why_false: str) -> tuple[Option, ...]:
        """The canonical True/False option pair: ``True`` first, ``False`` second, exactly the one
        matching ``answer`` marked correct. Fixed order keeps rendering and checking trivial."""
        return (
            Option("True", answer is True, why_true if answer else why_false),
            Option("False", answer is False, why_false if not answer else why_true),
        )

    @staticmethod
    def shuffled_options(
        correct: Option, distractors: list[Option], rng: random.Random
    ) -> tuple[Option, ...]:
        """One correct option plus distractors, order fixed by ``rng`` (so it is reproducible)."""
        pool = [correct, *distractors]
        rng.shuffle(pool)
        return tuple(pool)


__all__ = ["Domain", "derive_rng"]
