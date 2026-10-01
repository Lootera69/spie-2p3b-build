"""``arithmetic`` — bounded number theory whose answers are computed, not guessed.

Primality, divisibility, and gcd over bounded integers are *decidable by exact computation*: a
finite, total procedure returns the right answer with no oracle and no approximation. That makes
this the cleanest proven-answer category — the "proof" is the computation itself, re-runnable by
anyone. Every fact here is also independently re-derivable in the tests by a second method (trial
division vs. a sieve, Euclid vs. brute-force gcd), so the answer never rests on one code path.

Supports all three question shapes:

* ``TRUE_FALSE`` — "Is 91 prime?" (answer: False, because 91 = 7 × 13 — the witness factor is
  reported, so a False is a disproof).
* ``MCQ``        — "Which of these is prime?" with exactly one prime and factored distractors.
* ``FILL_BLANK`` — "gcd(48, 36) = ?" / "the smallest prime greater than 50 is ?" — a unique value.
"""

from __future__ import annotations

import math
import random

from ..types import Option, Question, QuestionType
from . import Domain


def _is_prime(n: int) -> bool:
    """Deterministic trial division — a complete primality decision for the bounded range used."""
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return n > 1


def _smallest_factor(n: int) -> int:
    """The least prime factor of a composite ``n`` (the witness that it is not prime)."""
    if n % 2 == 0:
        return 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return i
        i += 2
    return n


class ArithmeticDomain(Domain):
    name = "arithmetic"
    supported = frozenset({QuestionType.TRUE_FALSE, QuestionType.MCQ, QuestionType.FILL_BLANK})

    def build(
        self, qtype: QuestionType, qid: str, seed: int, rng: random.Random, words: tuple[str, ...],
        style: str = "plain",
    ) -> Question:
        if qtype is QuestionType.TRUE_FALSE:
            return self._true_false(qid, seed, rng)
        if qtype is QuestionType.MCQ:
            return self._mcq(qid, seed, rng)
        return self._fill_blank(qid, seed, rng)

    def _true_false(self, qid: str, seed: int, rng: random.Random) -> Question:
        n = rng.randint(20, 120)
        prime = _is_prime(n)
        if prime:
            why_true = f"{n} has no divisor other than 1 and itself"
            explanation = (
                f"{n} is prime: trial division by every integer up to isqrt({n}) = "
                f"{math.isqrt(n)} finds no factor, so its only divisors are 1 and {n}."
            )
        else:
            f = _smallest_factor(n)
            why_true = ""
            explanation = (
                f"{n} is not prime: {n} = {f} x {n // f}, so it has a divisor ({f}) other than 1 "
                f"and itself. (The factor is found by trial division and verifies exactly.)"
            )
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype_value(QuestionType.TRUE_FALSE),
            prompt=f"True or False: {n} is a prime number.",
            answer="True" if prime else "False",
            explanation=explanation,
            proof=self.py_proof(
                "primality-trial-division",
                f"is_prime({n}) = {prime} by complete trial division to isqrt({n})",
            ),
            seed=seed,
            options=self.tf_options(
                prime,
                why_true=why_true or f"{n} is prime",
                why_false=f"{n} = {_smallest_factor(n)} x {n // _smallest_factor(n)}"
                if not prime
                else f"{n} would need a proper factor",
            ),
            concepts=("prime", str(n)),
        )

    def _mcq(self, qid: str, seed: int, rng: random.Random) -> Question:
        primes = [n for n in range(20, 100) if _is_prime(n)]
        composites = [n for n in range(20, 100) if not _is_prime(n)]
        p = rng.choice(primes)
        rng.shuffle(composites)
        chosen = composites[:3]
        correct = Option(
            str(p), True, f"{p} is prime - trial division to isqrt({p}) finds no factor"
        )
        distractors = [
            Option(str(c), False, f"{c} = {_smallest_factor(c)} x {c // _smallest_factor(c)}, "
                                  f"so it is composite")
            for c in chosen
        ]
        options = self.shuffled_options(correct, distractors, rng)
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype_value(QuestionType.MCQ),
            prompt="Which of these numbers is prime?",
            answer=str(p),
            explanation=(
                f"Only {p} is prime; each other option is shown composite by an explicit "
                f"factorization. Primality is decided by complete trial division, so exactly one "
                f"option is correct."
            ),
            proof=self.py_proof(
                "primality-trial-division",
                f"is_prime = True for {p}; explicit factor for each of {sorted(chosen)}",
            ),
            seed=seed,
            options=options,
            concepts=("prime", str(p)),
        )

    def _fill_blank(self, qid: str, seed: int, rng: random.Random) -> Question:
        kind = rng.choice(("gcd", "next_prime"))
        if kind == "gcd":
            a, b = rng.randint(12, 90), rng.randint(12, 90)
            g = math.gcd(a, b)
            return Question(
                id=qid,
                category=self.name,
                qtype=qtype_value(QuestionType.FILL_BLANK),
                prompt=f"Fill in the blank: gcd({a}, {b}) = ____.",
                answer=str(g),
                explanation=(
                    f"The greatest common divisor of {a} and {b} is {g}, computed by the "
                    f"Euclidean algorithm; it is unique by definition (the largest integer "
                    f"dividing both)."
                ),
                proof=self.py_proof(
                    "euclid-gcd", f"gcd({a}, {b}) = {g} by the Euclidean algorithm (unique)"
                ),
                seed=seed,
                concepts=("gcd", str(a), str(b)),
            )
        base = rng.randint(30, 90)
        nxt = base + 1
        while not _is_prime(nxt):
            nxt += 1
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype_value(QuestionType.FILL_BLANK),
            prompt=f"Fill in the blank: the smallest prime greater than {base} is ____.",
            answer=str(nxt),
            explanation=(
                f"Testing {base + 1}, {base + 2}, ... in order, the first prime is {nxt}. Every "
                f"smaller candidate above {base} has an explicit factor, so {nxt} is the unique "
                f"answer."
            ),
            proof=self.py_proof(
                "next-prime-scan",
                f"first prime > {base} is {nxt} by upward primality scan (unique smallest)",
            ),
            seed=seed,
            concepts=("prime", str(nxt)),
        )


def qtype_value(q: QuestionType) -> str:
    """The serialized tag for ``q`` (kept as a tiny helper so call sites read clearly)."""
    return q.value


__all__ = ["ArithmeticDomain"]
