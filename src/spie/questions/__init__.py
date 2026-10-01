"""Proven-answer question generator — the formal-category layer on top of the proof engine.

Where the puzzle pipeline (:mod:`spie.invent`) invents *action/state puzzles* and proves them
solvable+unique, this package invents *questions* — True/False, multiple-choice, and
fill-in-the-blank — whose **answer is proven, never guessed**. The correctness of every answer
comes from a formal decision procedure (exact computation, exhaustive finite-model checking, or
a Z3 validity proof), so no learned model is ever in the answer path. That is the same iron rule
the rest of SPIE lives by, applied to questions instead of puzzles.

The scope is deliberately the categories where "correct" is *decidable from a formal definition*:

* ``sets``       — class/subsumption over stipulated property sets (e.g. "is every square a
                   rectangle?"); proof = property-set inclusion, cross-checked by Z3.
* ``arithmetic`` — primality, divisibility, gcd, ordering over bounded integers; proof = exact
                   computation (a complete decision procedure for these predicates).
* ``sequence``   — the next term of an *explicitly stated* generating rule; proof = the rule.
* ``logic``      — propositional tautology / argument validity; proof = Z3 (UNSAT of the
                   negation), with a concrete counter-model when the claim is false.
* ``syllogism``  — categorical-syllogism validity under the modern Boolean reading; proof =
                   exhaustive check over every inhabitant-type configuration.

Open-world categories (arbitrary "science facts", riddles) are intentionally *out of scope*:
their answers would need world knowledge, which only an unproven oracle could supply.
"""

from __future__ import annotations

from .generate import CATEGORIES, generate_question, generate_series
from .render import render
from .serialize import question_from_json, question_to_json
from .types import Option, Proof, Question, QuestionType

__all__ = [
    "CATEGORIES",
    "Option",
    "Proof",
    "Question",
    "QuestionType",
    "generate_question",
    "generate_series",
    "question_from_json",
    "question_to_json",
    "render",
]
