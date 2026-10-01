"""``sets`` — class subsumption over stipulated property sets (the square/rectangle category).

The micro-theory: each class is *defined* by a set of atomic, logically-independent properties, and
"every A is a B" holds exactly when ``props(B) ⊆ props(A)`` (a more specific class carries more
defining properties). This is proved two independent ways that must agree:

1. **exact** — set inclusion on the property sets;
2. **Z3** — validity of ``(⋀ props(A)) → (⋀ props(B))`` with each property a *free, independent*
   Boolean. Because the atoms are stipulated independent, Z3's semantics coincide with set
   inclusion, and when a subsumption is *false* Z3 returns a satisfying assignment of the negation —
   a concrete object with all of B-nothing… all of A's… i.e. all of the subclass-candidate's target
   properties but missing one, which is the witness (e.g. a non-square rectangle).

If the two methods ever disagreed the domain raises: a proven answer is never reported from a
single unchecked method. The independence of the atoms is the theory's stipulation and is stated in
every explanation, so no claim reaches beyond the stated definitions.
"""

from __future__ import annotations

import random

import z3

from ..prover import decide
from ..types import Option, Question, QuestionType
from . import Domain

# Atomic, mutually independent defining properties for quadrilaterals. Independence is the point:
# for a four-sided polygon each of these can be present or absent without forcing another, so a Z3
# counter-model over free Booleans is a real inhabitant (e.g. parallel + right angles + unequal
# sides = a genuine non-square rectangle).
_ATOMS = ("polygon", "four_sides", "both_pairs_parallel", "all_right_angles", "all_sides_equal")

# Each class as the set of atoms its definition requires. Ordered dict-like tuple of pairs so the
# vocabulary and its serialization are deterministic.
_CLASSES: dict[str, frozenset[str]] = {
    "quadrilateral": frozenset({"polygon", "four_sides"}),
    "parallelogram": frozenset({"polygon", "four_sides", "both_pairs_parallel"}),
    "rectangle": frozenset({"polygon", "four_sides", "both_pairs_parallel", "all_right_angles"}),
    "rhombus": frozenset({"polygon", "four_sides", "both_pairs_parallel", "all_sides_equal"}),
    "square": frozenset(
        {"polygon", "four_sides", "both_pairs_parallel", "all_right_angles", "all_sides_equal"}
    ),
}

# Human phrasing for each atom, used to build proof-derived explanations.
_ATOM_PHRASE = {
    "polygon": "is a closed straight-sided figure",
    "four_sides": "has four sides",
    "both_pairs_parallel": "has both pairs of opposite sides parallel",
    "all_right_angles": "has four right angles",
    "all_sides_equal": "has all sides equal in length",
}


def _subsumes_exact(sub: str, sup: str) -> bool:
    """Method 1: every ``sub`` is a ``sup`` iff ``sup``'s required properties ⊆ ``sub``'s."""
    return _CLASSES[sup] <= _CLASSES[sub]


def _subsumes_z3(sub: str, sup: str) -> tuple[bool, str]:
    """Method 2: Z3 validity of ``(⋀ sub-props) → (⋀ sup-props)`` over free Booleans.

    Returns ``(valid, witness)`` where ``witness`` describes the counter-model when invalid — a
    concrete property assignment that is a ``sub``-satisfying… that satisfies every ``sup``
    property the object needs yet fails one, i.e. an inhabitant of ``sup`` that is not a ``sub``."""
    p = {atom: z3.Bool(atom) for atom in _ATOMS}
    ante = z3.And(*[p[a] for a in sorted(_CLASSES[sub])]) if _CLASSES[sub] else z3.BoolVal(True)
    cons = z3.And(*[p[a] for a in sorted(_CLASSES[sup])]) if _CLASSES[sup] else z3.BoolVal(True)
    valid, model = decide(z3.Implies(ante, cons))
    if valid:
        return True, ""
    present = sorted(
        a for a in _ATOMS if model and z3.is_true(model.eval(p[a], model_completion=True))
    )
    return False, "an object that " + ", ".join(_ATOM_PHRASE[a] for a in present)


def _subsumes(sub: str, sup: str) -> tuple[bool, str]:
    """Both methods; raise on disagreement (a hard failure), else return the agreed verdict."""
    exact = _subsumes_exact(sub, sup)
    z3_valid, witness = _subsumes_z3(sub, sup)
    if exact != z3_valid:
        raise RuntimeError(
            f"sets: method disagreement on {sub}<={sup}: exact={exact} z3={z3_valid}"
        )
    return exact, witness


def _why(sub: str, sup: str, holds: bool, witness: str) -> str:
    """A proof-derived explanation naming the exact properties that decide the subsumption."""
    extra = sorted(_CLASSES[sub] - _CLASSES[sup])
    missing = sorted(_CLASSES[sup] - _CLASSES[sub])
    sup_props = ", ".join(_ATOM_PHRASE[a] for a in sorted(_CLASSES[sup]))
    if holds:
        note = (
            f" (a {sub} additionally {'; '.join(_ATOM_PHRASE[a] for a in extra)})"
            if extra
            else ""
        )
        return (
            f"By definition a {sup} {sup_props}. Every {sub} meets each of those requirements"
            f"{note}, so every {sub} is a {sup}. (The properties are stipulated independent, and "
            f"set inclusion of the definitions is confirmed by a Z3 validity proof.)"
        )
    lacked = "; ".join(_ATOM_PHRASE[a] for a in missing)
    return (
        f"A {sup} must satisfy: {sup_props}. A {sub} does not require that it {lacked}, so a "
        f"{sub} need not be a {sup} - for example {witness}, which is a {sub} but not a {sup}. "
        f"(The counter-example is a Z3 model of the negated inclusion.)"
    )


class SetsDomain(Domain):
    name = "sets"
    supported = frozenset({QuestionType.TRUE_FALSE, QuestionType.MCQ})

    # Pairs whose subsumption is TRUE and pairs whose subsumption is FALSE, for balanced TF seeds.
    _true_pairs = (("square", "rectangle"), ("square", "rhombus"), ("rectangle", "parallelogram"),
                   ("rhombus", "parallelogram"), ("square", "quadrilateral"))
    _false_pairs = (("rectangle", "square"), ("rhombus", "rectangle"),
                    ("parallelogram", "rectangle"), ("quadrilateral", "square"))

    def _pick_pair(self, rng: random.Random, words: tuple[str, ...]) -> tuple[str, str]:
        """Honor seed words when they name two known classes; otherwise pick a deterministic pair.

        Seed-word selection is what makes ``--words square,rectangle`` reproduce the flagship
        question exactly: the first two recognized class words become (sub, sup) in that order."""
        named = [w for w in words if w in _CLASSES]
        if len(named) >= 2:
            return named[0], named[1]
        if len(named) == 1:
            other = rng.choice([c for c in sorted(_CLASSES) if c != named[0]])
            return named[0], other
        pool = list(self._true_pairs + self._false_pairs)
        return pool[rng.randrange(len(pool))]

    def build(
        self, qtype: QuestionType, qid: str, seed: int, rng: random.Random, words: tuple[str, ...],
        style: str = "plain",
    ) -> Question:
        if qtype is QuestionType.TRUE_FALSE:
            sub, sup = self._pick_pair(rng, words)
            holds, witness = _subsumes(sub, sup)
            explanation = _why(sub, sup, holds, witness)
            proof = self.z3_proof(
                "class-subsumption",
                f"props({sup}) {'<=' if holds else 'not-subset-of'} props({sub}); "
                f"exact set-inclusion and Z3 validity agree",
            )
            return Question(
                id=qid,
                category=self.name,
                qtype=qtype.value,
                prompt=f"True or False: every {sub} is a {sup}.",
                answer="True" if holds else "False",
                explanation=explanation,
                proof=proof,
                seed=seed,
                options=self.tf_options(
                    holds,
                    why_true=f"every {sub} satisfies the definition of a {sup}",
                    why_false=f"some {sup} is not a {sub}",
                ),
                concepts=(sub, sup),
            )
        # MCQ: "Which of these is always a <target>?" — exactly one option provably subsumes.
        target = self._mcq_target(rng, words)
        correct_sub = rng.choice([c for c in sorted(_CLASSES) if _subsumes_exact(c, target)
                                  and c != target])
        wrong = [c for c in sorted(_CLASSES) if not _subsumes_exact(c, target) and c != target]
        rng.shuffle(wrong)
        distractors = []
        for c in wrong[:3]:
            holds, witness = _subsumes(c, target)  # proven FALSE, with witness
            distractors.append(Option(c, False, _why(c, target, holds, witness)))
        holds, _ = _subsumes(correct_sub, target)  # proven TRUE
        correct = Option(correct_sub, True, _why(correct_sub, target, holds, ""))
        options = self.shuffled_options(correct, distractors, rng)
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype.value,
            prompt=f"Which of these shapes is ALWAYS a {target}?",
            answer=correct_sub,
            explanation=(
                f"A shape is always a {target} exactly when its definition includes every "
                f"property a {target} requires. Only {correct_sub} does; each other option has a "
                f"proven counter-example (a member of that class that is not a {target})."
            ),
            proof=self.z3_proof(
                "class-subsumption-mcq",
                f"exactly one option subsumes {target}; all others have Z3 counter-models",
            ),
            seed=seed,
            options=options,
            concepts=(target, correct_sub),
        )

    def _mcq_target(self, rng: random.Random, words: tuple[str, ...]) -> str:
        """A class that has at least one proper subclass and at least one non-subclass, so the MCQ
        has both a unique correct answer and real distractors."""
        named = [w for w in words if w in _CLASSES]
        candidates = [
            c for c in sorted(_CLASSES)
            if any(_subsumes_exact(s, c) for s in _CLASSES if s != c)
            and any(not _subsumes_exact(s, c) for s in _CLASSES if s != c)
        ]
        for w in named:
            if w in candidates:
                return w
        return candidates[rng.randrange(len(candidates))]


__all__ = ["SetsDomain"]
