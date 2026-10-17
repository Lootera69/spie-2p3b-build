"""Infer a rule from examples within an explicitly stated finite hypothesis set."""

from __future__ import annotations

import random
from itertools import combinations
from math import prod

import z3

from ...forge.corpus import digest
from .. import prover
from .activity_policy import PATTERN_TRUE_FALSE_UNAVAILABLE

VERSION = "finite-pattern-v2"
MAX_OUTPUT = 120


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


def _prediction_tables(rules, level):
    """Find supported observations for every possible winner before choosing one."""
    tables = [[] for _ in rules]
    predictions = {x: [value(rule, x) for rule in rules] for x in range(6)}
    inputs = [x for x in range(5) if max(predictions[x]) <= MAX_OUTPUT]
    queries = [x for x in range(6) if max(predictions[x]) <= MAX_OUTPUT
               and len(set(predictions[x])) == 4]
    for selected in combinations(inputs, level):
        possible_queries = [x for x in queries if x not in selected]
        if not possible_queries:
            continue
        for winner in range(4):
            matching = [{i for i, output in enumerate(predictions[x])
                         if output == predictions[x][winner]} for x in selected]
            if set.intersection(*matching) != {winner}:
                continue
            if level > 1 and any(len(survivors) < 2 for survivors in matching):
                continue
            if any(len(set.intersection(set(range(4)), *[matching[i] for i in subset])) < 2
                   for subset in combinations(range(level), level - 1)):
                continue
            examples = [[x, predictions[x][winner]] for x in selected]
            tables[winner].append((examples, possible_queries))
    return tables


def _propose_v2(names, level, rng):
    if level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("Pattern puzzles require level+3 labels")
    for _ in range(80):
        slope, constant = rng.randint(1, 3), rng.randint(2, 7)
        if level == 1:
            rules = [(0, slope, constant + offset) for offset in rng.sample(range(-4, 5), 4)]
        elif level == 2:
            # Lines i*x-i² and j*x-j² meet at x=i+j. Every line can
            # therefore be isolated by combining two integer observations.
            direction = rng.choice((-1, 1))
            rules = [(0, slope + direction * i, constant - direction * i * i)
                     for i in range(4)]
        else:
            # Subtract each three-root cubic from the same cubic. The cubic
            # terms cancel, leaving four quadratics. At each node, three agree;
            # any rule can win on the three nodes it includes.
            nodes = sorted(rng.sample(range(5), 4))
            direction = rng.choice((-1, 1))
            rules = []
            for omitted in nodes:
                roots = [x for x in nodes if x != omitted]
                rules.append((direction * sum(roots),
                              slope - direction * sum(a * b for a, b in combinations(roots, 2)),
                              constant + direction * prod(roots)))
        # Shift all rules equally so observations and nearby queries stay small
        # and nonnegative without changing any agreement/disagreement relation.
        shift = max(0, -min(value(rule, x) for rule in rules for x in range(6)))
        rules = [(a, b, c + shift) for a, b, c in rules]
        rng.shuffle(rules)
        tables = _prediction_tables(rules, level)
        if not all(tables):
            continue
        winner = rng.randrange(4)
        examples, queries = rng.choice(tables[winner])
        query = rng.choice(queries)
        return {"design_version": VERSION, "level": level,
                "mode": "prediction", "names": list(names),
                "rules": [list(rule) for rule in rules],
                "examples": examples, "answer_index": winner,
                "query": query, "answer": value(rules[winner], query), "consistent": True}
    raise ValueError("No small pattern met the observation-support gates; try another seed")


def propose(names: list[str], level: int, rng: random.Random, *, engine_revision: int = 8,
            qtype: str = "multiple-choice") -> dict:
    if engine_revision >= 9:
        if qtype == "true-false":
            raise ValueError(PATTERN_TRUE_FALSE_UNAVAILABLE)
        return _propose_v2(names, level, rng)
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
    if model.get("design_version") == VERSION:
        return _check_v2(model)
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


def _matching(rules, examples, indices):
    return [i for i, rule in enumerate(rules)
            if all(value(rule, examples[j][0]) == examples[j][1] for j in indices)]


def _check_v2(model):
    rules, examples = model["rules"], model["examples"]
    level, mode = model["level"], model["mode"]
    if (level not in (1, 2, 3) or len(examples) != level or len(rules) != 4
            or len({tuple(rule) for rule in rules}) != 4
            or any(len(rule) != 3 or any(type(v) is not int for v in rule) for rule in rules)
            or any(len(example) != 2 or any(type(v) is not int for v in example)
                   for example in examples)
            or len({x for x, _ in examples}) != len(examples)
            or mode != "prediction" or model["consistent"] is not True):
        raise RuntimeError("Invalid finite-pattern-v2 model")
    matches = _matching(rules, examples, range(len(examples)))
    if matches != [model["answer_index"]]:
        raise RuntimeError("Pattern candidate agreement is incorrect")
    selector = z3.Int("pattern_rule")
    formula = z3.Or(*[z3.And(selector == i, *[
        z3.IntVal(a) * x * x + b * x + c == y for x, y in examples])
        for i, (a, b, c) in enumerate(rules)])
    sat, _ = prover.satisfiable(formula)
    if not sat:
        raise RuntimeError("Pattern consistency enumeration/SMT disagreement")
    unique, _ = prover.decide(z3.Implies(formula, selector == matches[0]))
    if not unique:
        raise RuntimeError("Pattern uniqueness enumeration/SMT disagreement")
    support = next(list(indices) for count in range(len(examples) + 1)
                   for indices in combinations(range(len(examples)), count)
                   if _matching(rules, examples, indices) == matches)
    individual = [len(_matching(rules, examples, [i])) for i in range(len(examples))]
    if len(support) != level or (level > 1 and min(individual) < 2):
        raise RuntimeError("Pattern requires fewer observations than its displayed level")
    outputs = [value(rule, model["query"]) for rule in rules]
    if (type(model["query"]) is not int or not 0 <= model["query"] <= 5
            or model["query"] in {x for x, _ in examples}
            or len(set(outputs)) != 4
            or any(not 0 <= value(rule, x) <= MAX_OUTPUT for rule in rules
                   for x in [model["query"], *[x for x, _ in examples]])
            or any(not 0 <= x <= 4 or not 0 <= y <= MAX_OUTPUT for x, y in examples)
            or model["answer"] != outputs[matches[0]]):
        raise RuntimeError("Pattern query or arithmetic bound is invalid")
    if not all(_prediction_tables(rules, level)):
        raise RuntimeError("Every listed rule must be eligible to win at the stated support level")
    steps = []
    for i, rule in enumerate(rules):
        mismatch = next(((x, y) for x, y in examples if value(rule, x) != y), None)
        if mismatch is None:
            steps.append(f"Rule {chr(65 + i)} matches all {len(examples)} observations.")
        else:
            x, y = mismatch
            steps.append(f"Rule {chr(65 + i)} gives {value(rule, x)} at input {x}, "
                         f"but that observation gives {y}; reject it.")
    steps.append(f"Rule {chr(65 + matches[0])} gives {model['answer']} "
                 f"at input {model['query']}.")
    quality = {"analysis_version": VERSION, "candidate_rules": 4, "examples": len(examples),
               "eligible_rule_indices": list(range(4)),
               "minimum_supporting_examples": len(support),
               "supporting_examples": [i + 1 for i in support],
               "single_example_candidate_counts": individual,
               "matching_rules": matches,
               "maximum_displayed_output": max(outputs + [y for _, y in examples]),
               "support_scope": "isolate the matching rule",
               "scope": "exact support in the four stated rules; all observations checked"}
    return {"method": "finite-rule-enumeration-and-z3",
            "agree": True, "z3_version": prover.z3_version(), "model": model,
            "scope": "the four displayed candidate rules; unrestricted sequences are not unique",
            "steps": steps, "quality": quality,
            "structural_key": digest([VERSION, mode, sorted(rules), examples, model["query"]])}


def _describe_v2(rule):
    terms = []
    for coefficient, term in zip(rule, ("input²", "input", ""), strict=True):
        if coefficient:
            magnitude = str(abs(coefficient)) + (f" × {term}" if term else "")
            if not terms:
                terms.append(("−" if coefficient < 0 else "") + magnitude)
            else:
                terms.append(("− " if coefficient < 0 else "+ ") + magnitude)
    return " ".join(terms) or "0"


def render(model: dict) -> dict:
    if model.get("design_version") == VERSION:
        return _render_v2(model)
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


def _render_v2(model):
    proof = check(model)
    rules, names = model["rules"], model["names"]
    candidates = "\n".join(f"Rule {chr(65 + i)} ({names[i]}): {_describe_v2(rule)}"
                             for i, rule in enumerate(rules))
    observations = "\n".join(
        f"{names[4 + i] if 4 + i < len(names) else 'Test ' + str(i + 1)}: input {x} → output {y}"
        for i, (x, y) in enumerate(model["examples"]))
    stem = ("An invented machine uses exactly one of these four rules for every input. "
            "The names are fictional labels.\n" + candidates + "\nObservations:\n"
            + observations + "\nFind the rule that fits every observation. "
            + f"What output does it give for input {model['query']}?")
    return {"stem": stem, "answer": str(model["answer"]),
            "distractors": [str(value(rule, model["query"])) for i, rule in enumerate(rules)
                            if i != model["answer_index"]],
            "explanation": " ".join(proof["steps"]), "proof": proof,
            "hints": ["Keep every rule that matches the first observation; "
                      "more than one may remain.",
                      "Intersect the rules that survive each observation. "
                      "A rule must fit every row."]}
