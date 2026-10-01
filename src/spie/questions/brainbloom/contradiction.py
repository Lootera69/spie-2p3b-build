"""Automatically invented contradiction questions with independent SMT option checks."""

from __future__ import annotations

from dataclasses import asdict
from itertools import combinations

import z3

from ...forge.corpus import digest
from .. import prover
from . import deduction


def propose(names: list[str], level: int, rng) -> dict:
    order = rng.sample(range(len(names)), len(names))
    base = [deduction.Clue("before", a, b)
            for a, b in zip(order[:-1], order[1:], strict=True)]
    rng.shuffle(base)
    pairs = [(i, j) for i, j in combinations(range(len(names)), 2) if j - i >= 2]
    long_pairs = [(i, j) for i, j in pairs if j - i >= level + 1]
    i, j = rng.choice(long_pairs)
    false = deduction.Clue("before", order[j], order[i])
    options = rng.sample(base, 3) + [false]
    rng.shuffle(options)
    solution = [0] * len(names)
    for position, name_index in enumerate(order):
        solution[name_index] = position
    return {"names": names, "clues": [asdict(c) for c in base],
            "solution": solution,
            "options": [asdict(c) for c in options], "answer_index": options.index(false),
            "required_chain_length": j - i}


def check(model: dict) -> dict:
    n = len(model["names"])
    base = [deduction.Clue(**c) for c in model["clues"]]
    options = [deduction.Clue(**c) for c in model["options"]]
    rows = deduction.survivors(deduction.worlds(n), base)
    if len(rows) != 1:
        raise RuntimeError("Contradiction base must have one solution")
    p = [z3.Int(f"impossible_{i}") for i in range(n)]
    formula = z3.And(z3.Distinct(*p), *[z3.And(x >= 0, x < n) for x in p],
                     *[p[c.a] < p[c.b] for c in base])
    sat, _ = prover.satisfiable(formula)
    unique, _ = prover.decide(z3.Implies(formula, z3.And(*[
        x == v for x, v in zip(p, rows[0], strict=True)])))
    if not sat or not unique:
        raise RuntimeError("Contradiction base SMT/enumeration disagreement")
    checks = []
    for clue in options:
        count = len(deduction.survivors(rows, [clue]))
        possible, _ = prover.satisfiable(z3.And(formula, p[clue.a] < p[clue.b]))
        if possible != bool(count):
            raise RuntimeError("Contradiction option SMT/enumeration disagreement")
        checks.append(count)
    if [i for i, count in enumerate(checks) if count == 0] != [model["answer_index"]]:
        raise RuntimeError("Exactly one statement must be impossible")
    wrong = options[model["answer_index"]]
    chain = rows[0][wrong.a] - rows[0][wrong.b]
    if chain != model["required_chain_length"] or chain < 2:
        raise RuntimeError("Contradiction chain length disagreement")
    ordered = sorted(range(n), key=lambda i: rows[0][i])
    return {"method": "z3-and-exhaustive-option-consistency", "agree": True,
            "z3_version": prover.z3_version(), "option_model_counts": checks,
            "solution": list(rows[0]), "scope": "only the stated fictional ordering clues",
            "steps": ["The base clues force the order " +
                      ", ".join(model["names"][i] for i in ordered) + ".",
                      f"The impossible statement reverses a chain of {chain} before-relations.",
                      "Every other statement agrees with that order."],
            "structural_key": digest(["contradiction", n,
                [(rows[0][c.a], rows[0][c.b]) for c in options]])}


def render(model: dict, *, concise: bool = False):
    names = model["names"]
    base = [deduction.Clue(**c) for c in model["clues"]]
    options = [deduction.Clue(**c) for c in model["options"]]
    labels = [f"Statement {chr(65 + i)}" for i in range(4)]
    stem = (f"Arrange these cards once each from left to right: {', '.join(names)}.\n"
            "Base clues:\n" + "\n".join(deduction.text(c, names, concise=concise) for c in base)
            + "\nTest these statements:\n"
            + "\n".join(f"{label}: {deduction.text(c, names, concise=concise)}"
                        for label, c in zip(labels, options, strict=True))
            + "\nWhich statement is impossible together with the base clues? Answer A, B, C or D.")
    answer = labels[model["answer_index"]]
    return stem, answer, labels, (f"{answer} contradicts the order forced by the base clues. "
                                 "The other three statements are compatible."), [
        "Connect the before-relations into a chain.",
        "A statement that reverses two cards in that chain is impossible."]
