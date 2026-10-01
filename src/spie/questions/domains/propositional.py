"""``logic`` — propositional tautology / argument validity, decided by Z3.

A propositional claim is *valid* iff its negation is unsatisfiable — the same UNSAT-of-the-negation
proof the puzzle spine uses. When a claim is not valid, Z3 returns a satisfying assignment of the
negation: a concrete truth-value row on which the claim fails, which is reported as the
counter-example. So "True" is a validity proof and "False" is a disproof exhibiting the failing row
— neither is asserted.

Templates are drawn from named propositional laws (some valid, some deliberately invalid, e.g.
affirming the consequent) so True/False seeds are balanced and every explanation can name the law.
Supports ``TRUE_FALSE`` (is this schema valid?) and ``MCQ`` (which schema is valid?).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

import z3

from ..types import Option, Question, QuestionType
from . import Domain
from .scenarios import SKINS, decide_claim, pick_scenario


@dataclass(frozen=True)
class _Schema:
    key: str
    text: str  # natural-language statement of the schema over p, q, r
    claim: Callable[..., z3.BoolRef]  # builds the propositional claim from Z3 Bools
    arity: int


_SCHEMAS: tuple[_Schema, ...] = (
    _Schema(
        "modus-ponens",
        "If (p implies q) and p are both true, then q is true.",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), p), q),
        2,
    ),
    _Schema(
        "modus-tollens",
        "If (p implies q) and (not q), then (not p).",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), z3.Not(q)), z3.Not(p)),
        2,
    ),
    _Schema(
        "hypothetical-syllogism",
        "If (p implies q) and (q implies r), then (p implies r).",
        lambda p, q, r: z3.Implies(
            z3.And(z3.Implies(p, q), z3.Implies(q, r)), z3.Implies(p, r)
        ),
        3,
    ),
    _Schema(
        "de-morgan",
        "not (p and q) is equivalent to (not p) or (not q).",
        lambda p, q: z3.Not(z3.And(p, q)) == z3.Or(z3.Not(p), z3.Not(q)),
        2,
    ),
    _Schema(
        "excluded-middle",
        "p or (not p) is always true.",
        lambda p: z3.Or(p, z3.Not(p)),
        1,
    ),
    # --- deliberately INVALID schemas (classic fallacies) ---
    _Schema(
        "affirming-consequent",
        "If (p implies q) and q are both true, then p is true.",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), q), p),
        2,
    ),
    _Schema(
        "denying-antecedent",
        "If (p implies q) and (not p), then (not q).",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), z3.Not(p)), z3.Not(q)),
        2,
    ),
    _Schema(
        "converse-error",
        "(p implies q) is equivalent to (q implies p).",
        lambda p, q: z3.Implies(p, q) == z3.Implies(q, p),
        2,
    ),
)


def _decide_schema(schema: _Schema) -> tuple[bool, str]:
    """``(valid, counter_row)`` for a schema, via the shared claim decider (single source of truth
    with the realistic path). ``counter_row`` names the falsifying assignment when invalid."""
    return decide_claim(schema.claim, schema.arity)


class LogicDomain(Domain):
    name = "logic"
    supported = frozenset({QuestionType.TRUE_FALSE, QuestionType.MCQ})
    realistic = frozenset({QuestionType.TRUE_FALSE, QuestionType.MCQ})

    def build(
        self, qtype: QuestionType, qid: str, seed: int, rng: random.Random, words: tuple[str, ...],
        style: str = "plain",
    ) -> Question:
        if style == "realistic":
            return self._build_realistic(qtype, qid, seed, rng)
        if qtype is QuestionType.TRUE_FALSE:
            schema = _SCHEMAS[rng.randrange(len(_SCHEMAS))]
            valid, row = _decide_schema(schema)
            if valid:
                explanation = (
                    f"The schema '{schema.key}' ({schema.text}) is valid: its negation is "
                    f"unsatisfiable, so it holds under every truth assignment (Z3 UNSAT proof)."
                )
            else:
                explanation = (
                    f"The schema '{schema.key}' ({schema.text}) is invalid: it fails when {row}. "
                    f"That row satisfies the premises but not the conclusion (Z3 counter-model)."
                )
            return Question(
                id=qid,
                category=self.name,
                qtype=qtype.value,
                prompt=f"True or False: this argument is logically valid - {schema.text}",
                answer="True" if valid else "False",
                explanation=explanation,
                proof=self.z3_proof(
                    "propositional-validity",
                    f"{schema.key}: valid={valid} by UNSAT-of-negation"
                    + (f"; counter-model {row}" if not valid else ""),
                ),
                seed=seed,
                options=self.tf_options(
                    valid,
                    why_true="the negation is unsatisfiable, so the schema is a tautology",
                    why_false=f"there is a falsifying row ({row})" if not valid else "it is valid",
                ),
                concepts=("logic", schema.key),
            )

        # MCQ: exactly one valid schema among fallacies.
        valids = [s for s in _SCHEMAS if _decide_schema(s)[0]]
        invalids = [s for s in _SCHEMAS if not _decide_schema(s)[0]]
        good = valids[rng.randrange(len(valids))]
        rng.shuffle(invalids)
        chosen = invalids[:3]
        correct = Option(good.text, True, f"'{good.key}' is valid (negation unsatisfiable)")
        distractors = []
        for s in chosen:
            _, row = _decide_schema(s)
            distractors.append(Option(s.text, False, f"'{s.key}' fails when {row}"))
        options = self.shuffled_options(correct, distractors, rng)
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype.value,
            prompt="Which of these argument forms is logically valid?",
            answer=good.text,
            explanation=(
                f"Only '{good.key}' is valid - its negation is unsatisfiable. Each other option "
                f"is a known fallacy with a concrete falsifying row (Z3 counter-model)."
            ),
            proof=self.z3_proof(
                "propositional-validity-mcq",
                f"unique valid schema '{good.key}'; others have counter-models",
            ),
            seed=seed,
            options=options,
            concepts=("logic", good.key),
        )

    def _build_realistic(
        self, qtype: QuestionType, qid: str, seed: int, rng: random.Random
    ) -> Question:
        """The same proven answer, worded as an everyday argument. Validity is decided by Z3 on the
        abstract claim (:func:`decide_claim`); the scenario only labels the atoms, so the answer is
        identical to the abstract form's -- it cannot be moved by the wording."""
        if qtype is QuestionType.TRUE_FALSE:
            skin = SKINS[rng.randrange(len(SKINS))]
            scenario = pick_scenario(skin.arity, rng)
            valid, row = decide_claim(skin.claim, skin.arity)
            argument = skin.render(scenario)
            if valid:
                explanation = (
                    f"This is {skin.law} ('{skin.key}'), a valid form: its negation is "
                    f"unsatisfiable, so the conclusion holds on every truth assignment (Z3 UNSAT "
                    f"proof). The everyday wording only labels the atoms; the proof is over "
                    f"the form."
                )
            else:
                explanation = (
                    f"This is {skin.law} ('{skin.key}'), a known fallacy: the form fails when "
                    f"{row} -- a case making the premises true and the conclusion false (Z3 "
                    f"counter-model). No wording can rescue an invalid form."
                )
            return Question(
                id=qid,
                category=self.name,
                qtype=qtype.value,
                prompt=f"True or False: this argument is logically valid - {argument}",
                answer="True" if valid else "False",
                explanation=explanation,
                proof=self.z3_proof(
                    "propositional-validity",
                    f"{skin.key}: valid={valid} by UNSAT-of-negation"
                    + (f"; counter-model {row}" if not valid else ""),
                ),
                seed=seed,
                options=self.tf_options(
                    valid,
                    why_true="the negation is unsatisfiable, so the form is a tautology",
                    why_false=f"there is a falsifying row ({row})" if not valid else "it is valid",
                ),
                concepts=("logic", skin.key, *scenario.concepts),
            )

        # MCQ: one valid everyday argument among fallacies; validity turns on form, not content.
        valids = [s for s in SKINS if decide_claim(s.claim, s.arity)[0]]
        invalids = [s for s in SKINS if not decide_claim(s.claim, s.arity)[0]]
        good = valids[rng.randrange(len(valids))]
        good_sc = pick_scenario(good.arity, rng)
        good_text = good.render(good_sc)
        correct = Option(
            good_text,
            True,
            f"a valid instance of {good.law} ('{good.key}'); its negation is unsatisfiable",
        )
        rng.shuffle(invalids)
        distractors = []
        for s in invalids:
            sc = pick_scenario(s.arity, rng)
            _, row = decide_claim(s.claim, s.arity)
            distractors.append(
                Option(s.render(sc), False, f"{s.law} ('{s.key}') is invalid; it fails when {row}")
            )
        options = self.shuffled_options(correct, distractors, rng)
        return Question(
            id=qid,
            category=self.name,
            qtype=qtype.value,
            prompt="Which of these everyday arguments is logically valid?",
            answer=good_text,
            explanation=(
                f"Only the {good.law} argument is valid - its negation is unsatisfiable (Z3). Each "
                f"other option instantiates a named fallacy with a concrete falsifying row. "
                f"Validity depends on the argument's form, not on its subject matter."
            ),
            proof=self.z3_proof(
                "propositional-validity-mcq",
                f"unique valid form '{good.key}'; distractors have counter-models",
            ),
            seed=seed,
            options=options,
            concepts=("logic", good.key, *good_sc.concepts),
        )


__all__ = ["LogicDomain"]
