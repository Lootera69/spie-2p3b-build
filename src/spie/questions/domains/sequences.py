"""``sequence`` — the next term of an *explicitly stated* generating rule.

"What comes next: 2, 4, 6, 8, ?" is ill-posed in general (infinitely many rules fit any finite
prefix). This domain sidesteps that the only sound way: it *states the rule* in the prompt, so the
answer is the deterministic value of that rule at the next index — a computation, not a guess about
the author's intent. Each rule is a closed function ``term(n)``, so the answer is unique and
re-derivable.

Supports ``FILL_BLANK`` (the next term) and ``MCQ`` (next term vs. off-by-rule distractors that are
each wrong *for the stated rule*, with the reason given).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from ..types import Option, Question, QuestionType
from . import Domain


@dataclass(frozen=True)
class _Rule:
    name: str
    describe: Callable[[int, int], str]  # (a, d) -> stated rule text
    term: Callable[[int, int, int], int]  # (a, d, n) -> nth term (0-based)


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "arithmetic",
        lambda a, d: f"start at {a} and add {d} each time",
        lambda a, d, n: a + d * n,
    ),
    _Rule(
        "geometric",
        lambda a, d: f"start at {a} and multiply by {d} each time",
        lambda a, d, n: a * (d**n),
    ),
    _Rule(
        "square-plus",
        lambda a, d: f"the n-th term is n*n + {a} (counting from 1)",
        lambda a, d, n: (n + 1) ** 2 + a,
    ),
)


class SequenceDomain(Domain):
    name = "sequence"
    supported = frozenset({QuestionType.MCQ, QuestionType.FILL_BLANK})

    def _params(self, rule: _Rule, rng: random.Random) -> tuple[int, int, int]:
        """Deterministic (a, d, shown) — the start, step, and how many terms to reveal."""
        if rule.name == "geometric":
            return rng.randint(2, 4), rng.randint(2, 3), 4
        if rule.name == "square-plus":
            return rng.randint(0, 5), 0, 4
        return rng.randint(1, 9), rng.randint(2, 7), 4

    def _prefix(self, rule: _Rule, a: int, d: int, shown: int) -> list[int]:
        return [rule.term(a, d, n) for n in range(shown)]

    def build(
        self, qtype: QuestionType, qid: str, seed: int, rng: random.Random, words: tuple[str, ...],
        style: str = "plain",
    ) -> Question:
        rule = _RULES[rng.randrange(len(_RULES))]
        a, d, shown = self._params(rule, rng)
        prefix = self._prefix(rule, a, d, shown)
        nxt = rule.term(a, d, shown)
        shown_str = ", ".join(str(x) for x in prefix)
        rule_text = rule.describe(a, d)

        if qtype is QuestionType.FILL_BLANK:
            return Question(
                id=qid,
                category=self.name,
                qtype=qtype.value,
                prompt=(
                    f"The rule is: {rule_text}. The sequence begins {shown_str}, ... "
                    f"Fill in the blank: the next term is ____."
                ),
                answer=str(nxt),
                explanation=(
                    f"Applying the stated rule ({rule_text}) at the next position gives {nxt}. "
                    f"Because the rule is given explicitly, the next term is uniquely determined."
                ),
                proof=self.py_proof(
                    "closed-form-term",
                    f"term[{shown}] = {nxt} under stated rule '{rule.name}' (a={a}, d={d})",
                ),
                seed=seed,
                concepts=("sequence", rule.name),
            )

        # MCQ: correct next term vs. distractors that are wrong *for the stated rule*.
        wrongs = {nxt + d if d else nxt + 1, prefix[-1] + prefix[-2], nxt + 1, nxt - 1}
        wrongs.discard(nxt)
        picks = sorted(wrongs)[:3]
        correct = Option(str(nxt), True, f"the stated rule yields {nxt} at the next position")
        distractors = [
            Option(str(w), False, f"{w} does not equal the stated rule's next value {nxt}")
            for w in picks
        ]
        options = self.shuffled_options(correct, distractors, rng)
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype.value,
            prompt=(
                f"The rule is: {rule_text}. The sequence begins {shown_str}, ... "
                f"What is the next term?"
            ),
            answer=str(nxt),
            explanation=(
                f"The stated rule ({rule_text}) determines the next term as {nxt}; the other "
                f"options disagree with that rule and are therefore wrong."
            ),
            proof=self.py_proof(
                "closed-form-term",
                f"unique next term {nxt} under stated rule '{rule.name}'",
            ),
            seed=seed,
            options=options,
            concepts=("sequence", rule.name),
        )


__all__ = ["SequenceDomain"]
