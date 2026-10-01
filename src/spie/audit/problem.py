"""The abstract formal problem a recognizer extracts from a bank record, and the *single* place it
is decided. Parsing (:mod:`spie.audit.recognize`) is kept separate from deciding so the correctness
path is a thin, auditable dispatch onto the existing solvers: categorical logic goes through the
exhaustive occupancy engine, propositional logic through the Z3 validity bridge. No heuristics, no
learned model — a :class:`Problem` is decided the same way whether it came from the bank or a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import z3

from ..questions.prover import decide
from .categorical import CatStmt, decide_categorical


@dataclass(frozen=True)
class Problem:
    """A recognized entailment question: *do the premises formally entail the conclusion?*

    Exactly one family is populated. ``answer_polarity`` is how the record's *authored* answer was
    classified — ``True`` if the author says the entailment holds (Yes/True), ``False`` if not
    (No/False) — so the auditor's comparison is simply ``formal_valid == answer_polarity``.
    ``frame`` names the surface pattern matched, for the report."""

    family: str  # "categorical" | "propositional"
    answer_polarity: bool
    frame: str
    # categorical payload
    terms: tuple[str, ...] = ()
    cat_premises: tuple[CatStmt, ...] = ()
    cat_conclusion: CatStmt | None = None
    # propositional payload: atoms are canonical clause keys; z3.Bool(key) per distinct atom
    conditionals: tuple[tuple[str, str], ...] = ()  # (antecedent_atom -> consequent_atom)
    facts: tuple[tuple[str, bool], ...] = ()  # (atom, asserted truth)
    prop_conclusion: tuple[str, bool] | None = None  # (atom, asserted truth)
    atoms: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Decision:
    valid: bool
    method: str  # "categorical-occupancy" | "z3"
    checker: str  # "python" | "z3"
    detail: str


def _decide_propositional(p: Problem) -> Decision:
    bools = {a: z3.Bool(a) for a in p.atoms}
    premises: list[z3.BoolRef] = [z3.Implies(bools[a], bools[b]) for a, b in p.conditionals]
    premises += [bools[a] if truth else z3.Not(bools[a]) for a, truth in p.facts]
    assert p.prop_conclusion is not None
    ca, ctruth = p.prop_conclusion
    concl = bools[ca] if ctruth else z3.Not(bools[ca])
    claim = z3.Implies(z3.And(*premises), concl) if premises else concl
    valid, model = decide(claim)
    if valid:
        return Decision(True, "z3", "z3", "premises entail the conclusion (negation UNSAT)")
    row = ", ".join(
        f"{a}={'T' if model and z3.is_true(model.eval(bools[a], model_completion=True)) else 'F'}"
        for a in p.atoms
    )
    return Decision(False, "z3", "z3", f"counter-model: {row}")


def decide_problem(p: Problem) -> Decision:
    """Decide ``p`` with the appropriate formal solver. This is the audit's correctness path."""
    if p.family == "categorical":
        assert p.cat_conclusion is not None
        verdict = decide_categorical(p.terms, p.cat_premises, p.cat_conclusion)
        detail = "every model of the premises models the conclusion" if verdict.valid else (
            f"counter-model: {verdict.counter}"
        )
        return Decision(verdict.valid, "categorical-occupancy", "python", detail)
    if p.family == "propositional":
        return _decide_propositional(p)
    raise ValueError(f"unknown problem family {p.family!r}")


__all__ = ["Decision", "Problem", "decide_problem"]
