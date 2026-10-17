"""Automatically invented contradiction questions with independent SMT option checks."""

from __future__ import annotations

from dataclasses import asdict
from itertools import combinations

import z3

from ...forge.corpus import digest
from .. import prover
from . import deduction

VERSION = "contradiction-options-v2"
PROPOSAL_BUDGET = 120


def _support(masks, universe, target):
    """Smallest clue subset that forces the predicate in the supplied worlds."""
    for count in range(len(masks) + 1):
        for subset in combinations(range(len(masks)), count):
            remaining = universe
            for index in subset:
                remaining &= masks[index]
            if remaining and not remaining & ~target:
                return list(subset)
    raise RuntimeError("The complete clues do not establish the claimed statement")


def _option_quality(names, base, options, solution, level):
    rows = deduction.worlds(len(names))
    universe = (1 << len(rows)) - 1
    masks = [deduction.mask_for(clue, rows) for clue in base]
    truths = [deduction.holds(option, solution) for option in options]
    if truths.count(False) != 1:
        return None
    option_masks = [deduction.mask_for(option, rows) for option in options]
    support = [_support(masks, universe, mask if truth else universe ^ mask)
               for mask, truth in zip(option_masks, truths, strict=True)]
    # The stem promises exactly one impossible option. Treat that promise as
    # information available to the player, not just the underlying full puzzle.
    answer_masks = []
    for wrong in range(4):
        possible = universe
        for index, mask in enumerate(option_masks):
            possible &= universe ^ mask if index == wrong else mask
        answer_masks.append(possible)
    if any(mask == 0 for mask in answer_masks):
        return None  # An option is ruled out by the other options alone.
    task_worlds = 0
    for mask in answer_masks:
        task_worlds |= mask
    answer = truths.index(False)
    task_support = _support(masks, task_worlds, answer_masks[answer])
    required = level + 1
    if (min(map(len, support)) < required or len(task_support) < required
            or max(map(len, support)) - min(map(len, support)) > 1):
        return None
    return {"analysis_version": VERSION, "minimum_required_support": required,
            "minimum_supporting_clues": len(task_support),
            "supporting_clues": [index + 1 for index in task_support],
            "option_supporting_clues": [[index + 1 for index in subset] for subset in support],
            "option_minimum_support": list(map(len, support)),
            "option_count": 4, "exactly_one_impossible": True,
            "copied_options": 0, "options_possible_without_base": 4,
            "scope": "minimum clue support including the displayed exactly-one-impossible promise"}


def _propose_v2(names, level, rng):
    if level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("Contradiction puzzles require level+3 card labels")
    for _ in range(PROPOSAL_BUDGET):
        seed = deduction.propose(names, level, rng)
        if seed is None:
            continue
        base = [deduction.Clue(**clue) for clue in seed["clues"]]
        solution = tuple(seed["solution"])
        rows = deduction.worlds(len(names))
        universe = (1 << len(rows)) - 1
        masks = [deduction.mask_for(clue, rows) for clue in base]
        derived = []
        for a, b in combinations(range(len(names)), 2):
            if solution[a] > solution[b]:
                a, b = b, a
            clue = deduction.Clue("before", a, b)
            count = len(_support(masks, universe, deduction.mask_for(clue, rows)))
            if level + 1 <= count <= level + 2:
                derived.append(clue)
        if len(derived) < 4:
            continue
        for _ in range(24):
            selected = rng.sample(derived, 4)
            false = selected[-1]
            options = [*selected[:-1], deduction.Clue("before", false.b, false.a)]
            rng.shuffle(options)
            quality = _option_quality(names, base, options, solution, level)
            if quality is not None:
                return {"design_version": VERSION, "level": level, "names": list(names),
                        "clues": [asdict(clue) for clue in base], "solution": list(solution),
                        "options": [asdict(clue) for clue in options],
                        "answer_index": next(i for i, clue in enumerate(options)
                                             if not deduction.holds(clue, solution))}
    raise ValueError("No contradiction met the displayed-option support gates; try another seed")


def propose(names: list[str], level: int, rng, *, engine_revision: int = 8) -> dict:
    if engine_revision >= 9:
        return _propose_v2(names, level, rng)
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
    if model.get("design_version") == VERSION:
        return _check_v2(model)
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


def _encoded(clue, positions):
    a, b = positions[clue.a], positions[clue.b]
    if clue.kind == "before":
        return a < b
    if clue.kind == "adjacent":
        return z3.Or(a == b + 1, b == a + 1)
    if clue.kind == "distance":
        return z3.Or(a - b == clue.k, b - a == clue.k)
    if clue.kind == "not-at":
        return a != clue.k
    if clue.kind == "between":
        c = positions[clue.k]
        return z3.Or(z3.And(b < a, a < c), z3.And(c < a, a < b))
    raise ValueError("Unknown contradiction clue kind")


def _check_v2(model):
    names, level = model["names"], model["level"]
    if level not in (1, 2, 3) or len(names) != level + 3:
        raise RuntimeError("Invalid contradiction level or card count")
    base = [deduction.Clue(**clue) for clue in model["clues"]]
    options = [deduction.Clue(**clue) for clue in model["options"]]
    if (len(options) != 4 or any(clue.kind != "before" or clue in base for clue in options)
            or len({frozenset((clue.a, clue.b)) for clue in options}) != 4):
        raise RuntimeError("Contradiction options must use four novel, distinct card pairs")
    rows = deduction.survivors(deduction.worlds(len(names)), base)
    if len(rows) != 1 or list(rows[0]) != model["solution"]:
        raise RuntimeError("Contradiction base must have its claimed unique solution")
    positions = [z3.Int(f"impossible_{i}") for i in range(len(names))]
    formula = z3.And(z3.Distinct(*positions),
                     *[z3.And(value >= 0, value < len(names)) for value in positions],
                     *[_encoded(clue, positions) for clue in base])
    sat, _ = prover.satisfiable(formula)
    unique, _ = prover.decide(z3.Implies(formula, z3.And(*[
        value == position for value, position in zip(positions, rows[0], strict=True)])))
    checks = []
    for option in options:
        possible, _ = prover.satisfiable(z3.And(formula, _encoded(option, positions)))
        count = int(deduction.holds(option, rows[0]))
        if possible != bool(count):
            raise RuntimeError("Contradiction option SMT/enumeration disagreement")
        checks.append(count)
    if (not sat or not unique
            or [i for i, count in enumerate(checks) if not count] != [model["answer_index"]]):
        raise RuntimeError("Contradiction base or answer SMT/enumeration disagreement")
    quality = _option_quality(names, base, options, rows[0], level)
    if quality is None:
        raise RuntimeError("Contradiction displayed-option support gate failed")
    steps = []
    for index, (option, support) in enumerate(
            zip(options, quality["option_supporting_clues"], strict=True)):
        a, b = (option.a, option.b) if checks[index] else (option.b, option.a)
        verdict = "agrees" if checks[index] else "reverses that relation"
        steps.append("Clues " + ", ".join(map(str, support))
                     + f" force {names[a]} before {names[b]}. "
                     + f"Statement {chr(65 + index)} {verdict}.")
    shape = sorted((clue.kind, rows[0][clue.a], rows[0][clue.b],
                    rows[0][clue.k] if clue.kind == "between" else clue.k) for clue in base)
    option_shape = sorted((rows[0][clue.a], rows[0][clue.b]) for clue in options)
    return {"method": "z3-and-exhaustive-option-consistency", "agree": True,
            "z3_version": prover.z3_version(), "option_model_counts": checks,
            "solution": list(rows[0]), "scope": "only the stated fictional ordering clues",
            "steps": steps, "quality": quality,
            "structural_key": digest([VERSION, len(names), shape, option_shape])}


def render(model: dict, *, concise: bool = False):
    names = model["names"]
    base = [deduction.Clue(**c) for c in model["clues"]]
    options = [deduction.Clue(**c) for c in model["options"]]
    labels = [f"Statement {chr(65 + i)}" for i in range(4)]
    clue_text = [deduction.text(clue, names, concise=concise) for clue in base]
    if model.get("design_version") == VERSION:
        clue_text = [f"{index}. {text}" for index, text in enumerate(clue_text, 1)]
    stem = (f"Arrange these cards once each from left to right: {', '.join(names)}.\n"
            "Base clues:\n" + "\n".join(clue_text)
            + "\nTest these statements:\n"
            + "\n".join(f"{label}: {deduction.text(c, names, concise=concise)}"
                        for label, c in zip(labels, options, strict=True))
            + "\nWhich statement is impossible together with the base clues? Answer A, B, C or D.")
    answer = labels[model["answer_index"]]
    if model.get("design_version") == VERSION:
        stem = stem.replace("once each from left to right:",
                            f"once each in positions 1–{len(names)}, left to right:")
        stem = stem.replace(
            "Which statement is impossible together with the base clues? Answer A, B, C or D.",
            "Which statement (A, B, C or D) is impossible together with the base clues?")
        proof = check(model)
        return stem, answer, labels, proof["steps"][model["answer_index"]], [
            "Track possible positions and combine clues that mention the same card.",
            "Check the direction of each statement against the combined clues."]
    return stem, answer, labels, (f"{answer} contradicts the order forced by the base clues. "
                                 "The other three statements are compatible."), [
        "Connect the before-relations into a chain.",
        "A statement that reverses two cards in that chain is impossible."]


def render_claim(model: dict, index: int, *, concise: bool = False) -> str:
    """A single tested statement avoids leaking information from unasked options."""
    names = model["names"]
    base = [deduction.Clue(**clue) for clue in model["clues"]]
    option = deduction.Clue(**model["options"][index])
    return (f"Arrange these cards once each in positions 1–{len(names)}, left to right: "
            + ", ".join(names) + ".\nBase clues:\n"
            + "\n".join(f"{index}. {deduction.text(clue, names, concise=concise)}"
                        for index, clue in enumerate(base, 1))
            + f"\nTest Statement {chr(65 + index)}: "
            + deduction.text(option, names, concise=concise)
            + "\nTrue or False: this statement is impossible together with the base clues.")
