"""Infer a rule from examples within an explicitly stated finite hypothesis set."""

from __future__ import annotations

import random
from itertools import combinations

import z3

from ...forge.corpus import digest
from .. import prover


def value(rule: tuple[int, int, int], x: int) -> int:
    a, b, c = rule
    return a * x * x + b * x + c


def describe(rule) -> str:
    a, b, c = rule
    terms = []
    if a:
        terms.append(f"{a} × input²")
    if b:
        terms.append(f"{b} × input")
    if c:
        terms.append(str(c))
    return " + ".join(terms) or "0"


def propose(names: list[str], level: int, rng: random.Random) -> dict:
    pool = ([(0, 1, c) for c in range(1, 16)]
            + [(0, b, 0) for b in range(2, 10)] if level == 1 else
            [(a, b, c) for a in (range(1, 4) if level == 3 else [0])
             for b in range(1, 7) for c in range(1, 12)])
    rules = rng.sample(pool, 4)
    winner = rng.randrange(4)
    inputs = sorted(rng.sample(range(1, 13), level + 3))
    examples = [[x, value(rules[winner], x)] for x in inputs]
    matching = [i for i, rule in enumerate(rules)
                if all(value(rule, x) == y for x, y in examples)]
    if matching != [winner]:
        raise RuntimeError("Pattern proposals must identify exactly one candidate rule")
    query = next(x for x in range(13, 40)
                 if len({value(rule, x) for rule in rules}) == 4)
    return {"names": names, "rules": [list(r) for r in rules], "examples": examples,
            "answer_index": winner, "query": query, "answer": value(rules[winner], query)}


def check(model: dict) -> dict:
    rules, examples = model["rules"], model["examples"]
    winner = model["answer_index"]
    matches = [i for i, rule in enumerate(rules)
               if all(value(rule, x) == y for x, y in examples)]
    choice = z3.Int("pattern_rule")
    x = z3.Int("pattern_input")
    formulas = [a * x**2 + b * x + c for a, b, c in rules]
    formula = z3.Or(*[z3.And(choice == i, *[
        z3.substitute(expr, (x, z3.IntVal(inp))) == out for inp, out in examples
    ]) for i, expr in enumerate(formulas)])
    sat, _ = prover.satisfiable(formula)
    unique, _ = prover.decide(z3.Implies(formula, choice == winner))
    answer_ok, _ = prover.decide(
        z3.substitute(formulas[winner], (x, z3.IntVal(model["query"]))) == model["answer"]
    )
    if matches != [winner] or not (sat and unique and answer_ok):
        raise RuntimeError("Pattern enumeration/SMT disagreement")
    support = next(list(subset) for count in range(1, len(examples) + 1)
                   for subset in combinations(range(len(examples)), count)
                   if [i for i, rule in enumerate(rules)
                       if all(value(rule, examples[j][0]) == examples[j][1]
                              for j in subset)] == [winner])
    steps = []
    for i, rule in enumerate(rules):
        mismatch = next(((a, b) for a, b in examples if value(rule, a) != b), None)
        if mismatch:
            inp, out = mismatch
            steps.append(f"Rule {chr(65 + i)} predicts {value(rule, inp)} for input {inp}, "
                         f"but the example gives {out}, so reject it.")
        else:
            steps.append(f"Rule {chr(65 + i)} matches every example: {describe(rule)}.")
    steps.append(f"Apply the surviving rule to {model['query']}: {model['answer']}.")
    return {"method": "finite-rule-enumeration-and-z3", "agree": True,
            "z3_version": prover.z3_version(), "model": model,
            "scope": "the four displayed candidate rules; unrestricted sequences are not unique",
            "steps": steps, "quality": {"candidate_rules": 4,
                "examples": len(examples), "minimum_supporting_examples": len(support)},
            "structural_key": digest(["finite-pattern-v1", sorted(rules), examples,
                                       rules[winner], model["query"]])}


def render(model: dict) -> dict:
    rules = model["rules"]
    possibilities = "\n".join(f"Rule {chr(65 + i)}: {describe(rule)}"
                              for i, rule in enumerate(rules))
    observations = "\n".join(f"{name}: input {x} → output {y}"
                              for name, (x, y) in zip(model["names"], model["examples"],
                                                      strict=True))
    stem = ("An invented machine uses exactly one of these four rules for every input. "
            "The labels name observation cards.\n" + possibilities + "\nExamples:\n"
            + observations + f"\nInfer which rule fits every example. "
            f"What output will it give for input {model['query']}?")
    proof = check(model)
    return {"stem": stem, "answer": str(model["answer"]),
            "distractors": [str(value(rule, model["query"])) for i, rule in enumerate(rules)
                            if i != model["answer_index"]],
            "explanation": (f"Only Rule {chr(65 + model['answer_index'])} matches every example. "
                            f"Applying it to {model['query']} gives {model['answer']}."),
            "proof": proof,
            "hints": ["Test each candidate rule on the first example.",
                      "Reject any rule that gives a different output for a shown input."]}
