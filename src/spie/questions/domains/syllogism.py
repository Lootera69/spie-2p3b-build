"""``syllogism`` — categorical-syllogism validity under the modern (Boolean) reading.

Three monadic terms partition any domain into 2³ = 8 regions (in/out of each of S, M, P). A model
is fixed, for validity purposes, by *which* of those 8 regions are non-empty — 2⁸ = 256 occupancy
patterns in all. Each categorical statement is a condition on that occupancy:

* **A** "All X are Y"   — no region that is in-X and out-Y is occupied.
* **E** "No X is Y"     — no region in-X and in-Y is occupied.
* **I** "Some X is Y"   — at least one in-X, in-Y region is occupied.
* **O** "Some X is not Y" — at least one in-X, out-Y region is occupied.

A syllogism is **valid** iff *every* occupancy pattern satisfying both premises also satisfies the
conclusion. Checking all 256 patterns is a complete, exhaustive, fully deterministic decision
procedure — no solver, so no ``unknown`` — and when a form is invalid the first violating pattern
is a concrete counter-model (a partition making the premises true and the conclusion false). This
is the modern reading: universals carry no existential import, so ``Barbara``'s ``AAA`` is valid
while the traditional-only forms (e.g. ``AAI``) come out invalid, which the explanation states.
"""

from __future__ import annotations

import random
from itertools import product

from ..types import Option, Question, QuestionType
from . import Domain

# Region index bit layout: bit 0 = in S, bit 1 = in M, bit 2 = in P.
_S, _M, _P = 1, 2, 4
_REGIONS = tuple(range(8))


def _in(region: int, term: int) -> bool:
    return bool(region & term)


def _stmt_holds(occ: tuple[bool, ...], form: str, x: int, y: int) -> bool:
    """Does statement ``form`` about (X, Y) hold under occupancy ``occ`` (occ[r] = region r on)?"""
    if form == "A":  # all X are Y: no occupied region in X but not Y
        return not any(occ[r] and _in(r, x) and not _in(r, y) for r in _REGIONS)
    if form == "E":  # no X is Y
        return not any(occ[r] and _in(r, x) and _in(r, y) for r in _REGIONS)
    if form == "I":  # some X is Y
        return any(occ[r] and _in(r, x) and _in(r, y) for r in _REGIONS)
    if form == "O":  # some X is not Y
        return any(occ[r] and _in(r, x) and not _in(r, y) for r in _REGIONS)
    raise ValueError(f"unknown categorical form {form!r}")


def _validity(prem1: tuple, prem2: tuple, concl: tuple) -> tuple[bool, tuple[bool, ...] | None]:
    """Exhaustive check over all 256 occupancy patterns. Returns ``(valid, counter_pattern)``."""
    for bits in product((False, True), repeat=8):
        occ = bits
        if _stmt_holds(occ, *prem1) and _stmt_holds(occ, *prem2) and not _stmt_holds(occ, *concl):
            return False, occ
    return True, None


def _phrase(form: str, x_name: str, y_name: str) -> str:
    return {
        "A": f"All {x_name} are {y_name}",
        "E": f"No {x_name} are {y_name}",
        "I": f"Some {x_name} are {y_name}",
        "O": f"Some {x_name} are not {y_name}",
    }[form]


# A pool of classic syllogisms with their (premise1, premise2, conclusion) over terms S, M, P.
# Terms: S=subject of conclusion, P=predicate of conclusion, M=middle term.
# Each statement is (form, x, y) with x,y in {_S,_M,_P}.
_FIGURES: tuple[tuple[str, tuple, tuple, tuple], ...] = (
    ("Barbara", ("A", _M, _P), ("A", _S, _M), ("A", _S, _P)),   # valid
    ("Celarent", ("E", _M, _P), ("A", _S, _M), ("E", _S, _P)),  # valid
    ("Darii", ("A", _M, _P), ("I", _S, _M), ("I", _S, _P)),     # valid
    ("Ferio", ("E", _M, _P), ("I", _S, _M), ("O", _S, _P)),     # valid
    ("Cesare", ("E", _P, _M), ("A", _S, _M), ("E", _S, _P)),    # valid
    ("Camestres", ("A", _P, _M), ("E", _S, _M), ("E", _S, _P)), # valid
    ("AAI-invalid", ("A", _M, _P), ("A", _S, _M), ("I", _S, _P)),   # invalid (no exist. import)
    ("fallacy-undistributed", ("A", _P, _M), ("A", _S, _M), ("A", _S, _P)),  # invalid
    ("illicit-major", ("A", _M, _P), ("E", _S, _M), ("E", _S, _P)),  # invalid
    ("EAA-invalid", ("E", _M, _P), ("A", _S, _M), ("A", _S, _P)),    # invalid
)

_TERMS = ("dogs", "mammals", "animals")  # (S, P, M) filler nouns — S, P, then M


def _counter_text(occ: tuple[bool, ...], names: dict[int, str]) -> str:
    """Describe a counter-model: a non-empty region making premises true, conclusion false."""
    parts = []
    for r in _REGIONS:
        if occ[r]:
            memb = [names[t] for t in (_S, _M, _P) if _in(r, t)] or ["neither category"]
            parts.append("something that is " + " and ".join(memb))
    return "; ".join(parts) if parts else "the empty domain"


class SyllogismDomain(Domain):
    name = "syllogism"
    supported = frozenset({QuestionType.TRUE_FALSE, QuestionType.MCQ})

    def _named(self, rng: random.Random, words: tuple[str, ...]) -> dict[int, str]:
        """Term nouns for S, M, P — seed words when three are given, else defaults."""
        usable = [w for w in words if w.isalpha()]
        if len(usable) >= 3:
            s, p, m = usable[0], usable[1], usable[2]
        else:
            s, p, m = _TERMS[0], _TERMS[1], _TERMS[2]
        return {_S: s, _P: p, _M: m}

    def _render(self, stmt: tuple, names: dict[int, str]) -> str:
        form, x, y = stmt
        return _phrase(form, names[x], names[y])

    def build(
        self, qtype: QuestionType, qid: str, seed: int, rng: random.Random, words: tuple[str, ...],
        style: str = "plain",
    ) -> Question:
        names = self._named(rng, words)
        if qtype is QuestionType.TRUE_FALSE:
            label, p1, p2, concl = _FIGURES[rng.randrange(len(_FIGURES))]
            valid, counter = _validity(p1, p2, concl)
            arg = (
                f"Premise 1: {self._render(p1, names)}. "
                f"Premise 2: {self._render(p2, names)}. "
                f"Conclusion: {self._render(concl, names)}."
            )
            if valid:
                explanation = (
                    f"This syllogism ({label}) is valid under the modern reading: across all 256 "
                    f"ways of populating the regions of S, M, and P, every model of the premises "
                    f"also models the conclusion."
                )
            else:
                explanation = (
                    f"This syllogism ({label}) is invalid: consider a domain containing "
                    f"{_counter_text(counter, names)}. The premises hold there but the conclusion "
                    f"fails, so it is not valid (universals carry no existential import)."
                )
            return Question(
                id=qid,
                category=self.name,
                qtype=qtype.value,
                prompt=f"True or False: the following argument is valid. {arg}",
                answer="True" if valid else "False",
                explanation=explanation,
                proof=self.py_proof(
                    "syllogism-exhaustive",
                    f"{label}: valid={valid} by exhaustive 256-pattern occupancy check",
                ),
                seed=seed,
                options=self.tf_options(
                    valid,
                    why_true="every model of the premises models the conclusion",
                    why_false="a populated-region model satisfies the premises but not the "
                    "conclusion" if not valid else "it is valid",
                ),
                concepts=("syllogism", label),
            )

        # MCQ: which of these arguments is valid?
        valids = [f for f in _FIGURES if _validity(f[1], f[2], f[3])[0]]
        invalids = [f for f in _FIGURES if not _validity(f[1], f[2], f[3])[0]]
        good = valids[rng.randrange(len(valids))]
        rng.shuffle(invalids)
        chosen = invalids[:3]

        def _arg(fig: tuple) -> str:
            _, p1, p2, concl = fig
            return (
                f"{self._render(p1, names)}; {self._render(p2, names)}; "
                f"therefore {self._render(concl, names)}"
            )

        correct = Option(_arg(good), True, f"'{good[0]}' is valid (all 256 patterns checked)")
        distractors = [Option(_arg(f), False, f"'{f[0]}' has a counter-model") for f in chosen]
        options = self.shuffled_options(correct, distractors, rng)
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype.value,
            prompt="Which of these categorical arguments is valid?",
            answer=_arg(good),
            explanation=(
                f"Only '{good[0]}' is valid - checked exhaustively over all region-occupancy "
                f"patterns. Each other option has a concrete counter-model."
            ),
            proof=self.py_proof(
                "syllogism-exhaustive-mcq",
                f"unique valid form '{good[0]}'; others refuted by occupancy patterns",
            ),
            seed=seed,
            options=options,
            concepts=("syllogism", good[0]),
        )


__all__ = ["SyllogismDomain"]
