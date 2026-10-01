"""Small finite logic problems; Z3 and exhaustive truth tables must agree.

No text parser or learned model decides truth. The same explicit literals are
used by the controlled-English renderer and the two independent evaluators.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations, product

import z3

from .. import prover


@dataclass(frozen=True)
class Literal:
    atom: int
    positive: bool = True

    def opposite(self) -> Literal:
        return Literal(self.atom, not self.positive)


@dataclass(frozen=True)
class Rule:
    before: Literal
    after: Literal


@dataclass(frozen=True)
class Problem:
    attributes: tuple[str, ...]
    rules: tuple[Rule, ...]
    facts: tuple[Literal, ...]

    def check(self) -> None:
        if not 2 <= len(self.attributes) <= 8:
            raise ValueError("A conditional problem needs 2-8 distinct attributes")
        if len(set(self.attributes)) != len(self.attributes):
            raise ValueError("Repeated attributes")
        if not self.rules or len(self.rules) > 5 or not self.facts:
            raise ValueError("Expected 1-5 rules and at least one fact")
        for lit in (*self.facts, *(x for r in self.rules for x in (r.before, r.after))):
            if type(lit.atom) is not int or not 0 <= lit.atom < len(self.attributes):
                raise ValueError("Invalid atom")
            if type(lit.positive) is not bool:
                raise ValueError("Literal polarity must be a bool")


def holds(lit: Literal, row: tuple[bool, ...]) -> bool:
    return row[lit.atom] == lit.positive


def worlds(problem: Problem, rules: tuple[Rule, ...] | None = None) -> list[tuple[bool, ...]]:
    """Independent Python evaluator: enumerate every interpretation, not Z3 models."""
    active = problem.rules if rules is None else rules
    return [
        row for row in product((False, True), repeat=len(problem.attributes))
        if all(holds(f, row) for f in problem.facts)
        and all(not holds(r.before, row) or holds(r.after, row) for r in active)
    ]


def _formula(problem: Problem) -> tuple[z3.BoolRef, list[z3.BoolRef]]:
    atoms = [z3.Bool(f"attribute_{i}") for i in range(len(problem.attributes))]

    def encode(lit: Literal) -> z3.BoolRef:
        return atoms[lit.atom] if lit.positive else z3.Not(atoms[lit.atom])

    formula = z3.And(
        *[encode(f) for f in problem.facts],
        *[z3.Implies(encode(r.before), encode(r.after)) for r in problem.rules],
    )
    return formula, atoms


def analyze(problem: Problem, candidates: tuple[Literal, ...]) -> dict:
    """Fail closed on contradiction, UNKNOWN, or any cross-check discrepancy."""
    problem.check()
    formula, atoms = _formula(problem)
    rows = worlds(problem)
    sat, _ = prover.satisfiable(formula)
    if sat != bool(rows):
        raise RuntimeError("Z3/truth-table satisfiability disagreement")
    if not sat:
        raise ValueError("Contradictory premises cannot certify a question")
    verdicts = []
    for lit in candidates:
        if type(lit.atom) is not int or not 0 <= lit.atom < len(atoms):
            raise ValueError("Invalid candidate atom")
        if type(lit.positive) is not bool:
            raise ValueError("Invalid candidate polarity")
        claim = atoms[lit.atom] if lit.positive else z3.Not(atoms[lit.atom])
        entailed, _ = prover.decide(z3.Implies(formula, claim))
        enum_entailed = all(holds(lit, row) for row in rows)
        if entailed != enum_entailed:
            raise RuntimeError("Z3/truth-table entailment disagreement")
        counterexample = next((list(row) for row in rows if not holds(lit, row)), None)
        verdicts.append({
            "literal": asdict(lit), "entailed": entailed,
            "truth_table_entailed": enum_entailed, "counterexample": counterexample,
        })
    return {
        "method": "finite-propositional-entailment", "z3_version": prover.z3_version(),
        "independent_checker": "exhaustive-python-truth-table-v1",
        "consistent": True, "agree": True, "model_count": len(rows),
        "problem": asdict(problem), "candidates": verdicts,
        "scope": "logical consequences of the stated assumptions, not real-world facts",
    }


def minimum_rules(problem: Problem, target: Literal) -> int:
    """Exact smallest rule subset sufficient for the target, keeping stated facts."""
    for size in range(len(problem.rules) + 1):
        for subset in combinations(problem.rules, size):
            rows = worlds(problem, subset)
            if rows and all(holds(target, row) for row in rows):
                return size
    raise ValueError("Target does not follow")


def phrase(problem: Problem, lit: Literal) -> str:
    return ("is " if lit.positive else "is not ") + problem.attributes[lit.atom]


def rule_text(problem: Problem, rule: Rule, noun: str) -> str:
    return f"If a {noun} {phrase(problem, rule.before)}, it {phrase(problem, rule.after)}."
