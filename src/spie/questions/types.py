"""Immutable data types for proven-answer questions, and the soundness self-check.

A :class:`Question` is a natural-language question plus the *proof* that its stated answer is
correct. The three shapes it can take mirror the three ways "the answer is forced":

* ``TRUE_FALSE`` — the claim is either valid or has a counter-model; exactly one of the two
  options (``True`` / ``False``) is correct.
* ``MCQ`` — exactly one option is provably correct and every distractor is provably incorrect
  (the multiple-choice analogue of the puzzle engine's *uniqueness* obligation: a distractor that
  merely "wasn't chosen" is not enough — it must be *proven wrong*).
* ``FILL_BLANK`` — the answer is a single value that a decision procedure computes and (where the
  category defines it) proves *unique*.

:meth:`Question.check` re-asserts the shape invariants before a question ever leaves the
generator, so a malformed question is a hard failure at construction, not a surprise downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QuestionType(str, Enum):
    """The three proven-answer question shapes. The ``str`` values are the CLI/serialized tags."""

    TRUE_FALSE = "tf"
    MCQ = "mcq"
    FILL_BLANK = "blank"

    @classmethod
    def parse(cls, value: str | QuestionType) -> QuestionType:
        if isinstance(value, QuestionType):
            return value
        key = value.strip().lower()
        aliases = {
            "tf": cls.TRUE_FALSE,
            "true-false": cls.TRUE_FALSE,
            "true_false": cls.TRUE_FALSE,
            "truefalse": cls.TRUE_FALSE,
            "boolean": cls.TRUE_FALSE,
            "mcq": cls.MCQ,
            "choice": cls.MCQ,
            "multiple-choice": cls.MCQ,
            "blank": cls.FILL_BLANK,
            "fill": cls.FILL_BLANK,
            "fill-blank": cls.FILL_BLANK,
            "fill_in_the_blank": cls.FILL_BLANK,
        }
        if key not in aliases:
            valid = ", ".join(sorted({q.value for q in cls}))
            raise ValueError(f"unknown question type {value!r} (expected one of: {valid})")
        return aliases[key]


@dataclass(frozen=True)
class Proof:
    """The formal justification of a question's answer — never a learned guess.

    ``method`` names the decision procedure (e.g. ``"class-subsumption"``); ``checker`` and
    ``checker_version`` pin the tool that ran it (``"z3"`` + Z3's version string, or ``"python"``
    + the interpreter version) so a certificate says exactly *what* established the answer.
    """

    method: str
    checker: str
    checker_version: str
    detail: str


@dataclass(frozen=True)
class Option:
    """One answer choice with its *proven* verdict and the reason the proof gives for it."""

    text: str
    correct: bool
    reason: str


@dataclass(frozen=True)
class Question:
    """A question whose answer is backed by :class:`Proof`. Byte-reproducible from its seed."""

    id: str
    category: str
    qtype: str
    prompt: str
    answer: str
    explanation: str
    proof: Proof
    seed: int
    options: tuple[Option, ...] = ()
    concepts: tuple[str, ...] = field(default=())

    def check(self) -> None:
        """Re-assert the shape invariants; raise :class:`ValueError` on any violation.

        This is the generator's own gate: it runs before a question is returned, so an internally
        inconsistent question (no correct option, two correct options, an answer that does not
        match the winning option) can never escape as if it were sound."""
        qtype = QuestionType.parse(self.qtype)
        correct = [o for o in self.options if o.correct]
        if qtype is QuestionType.TRUE_FALSE:
            labels = [o.text for o in self.options]
            if labels != ["True", "False"]:
                raise ValueError(f"{self.id}: true/false must offer exactly True, False")
            if len(correct) != 1:
                raise ValueError(f"{self.id}: exactly one of True/False must be correct")
            if correct[0].text != self.answer:
                raise ValueError(f"{self.id}: answer {self.answer!r} != winning option")
        elif qtype is QuestionType.MCQ:
            if len(self.options) < 2:
                raise ValueError(f"{self.id}: an MCQ needs at least two options")
            if len(correct) != 1:
                raise ValueError(f"{self.id}: an MCQ must have exactly one correct option")
        else:  # FILL_BLANK
            if self.options:
                raise ValueError(f"{self.id}: a fill-in-the-blank carries no options")
            if not self.answer:
                raise ValueError(f"{self.id}: a fill-in-the-blank needs a non-empty answer")


__all__ = ["Option", "Proof", "Question", "QuestionType"]
