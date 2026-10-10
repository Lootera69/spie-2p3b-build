"""Small, answer-specific explanations from an already verified item/proof pair.

The caller must verify the full bundle before calling ``feedback_for`` or
``grid_feedback``. This module does not authenticate a proof, regenerate a puzzle,
or change the saved content.
``supported`` means the message includes coaching derived from a supported proof
model; correctness can still be checked when specific coaching is unavailable.
"""

from __future__ import annotations

import unicodedata
from fractions import Fraction
from itertools import combinations

from . import deduction, logic_grid, patterns


def _normalized(value: str) -> str:
    # Keep signs, decimal points and other meaningful punctuation in typed answers.
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _index(values, answer: str) -> int | None:
    matches = [i for i, value in enumerate(values)
               if _normalized(str(value)) == _normalized(answer)]
    return matches[0] if len(matches) == 1 else None


def _route(model: dict, answer: str) -> tuple[bool, str] | None:
    options, names = model["options"], model["names"]
    index = _index([names[o["next"]] for o in options], answer)
    if index is None:
        return None
    option = options[index]
    best = min(o["cost"] for o in options)
    if sum(o["cost"] == best for o in options) != 1:
        return None
    name, cost = names[option["next"]], option["cost"]
    if cost == best:
        return True, (f"Starting with {name}, the cheapest complete trip costs {cost}. "
                      "Every other first stop has a higher best total cost.")
    return False, (f"Starting with {name}, even the cheapest complete trip costs {cost}. "
                   f"The best available total is {best}, so this first stop costs "
                   f"{cost - best} extra. Compare the whole trip, including later legs.")


def _pattern(model: dict, answer: str) -> tuple[bool, str] | None:
    rules, examples, query = model["rules"], model["examples"], model["query"]
    outputs = [patterns.value(rule, query) for rule in rules]
    index = _index(outputs, answer)
    if index is None:
        return None
    rule = rules[index]
    mismatch = next(((x, y) for x, y in examples if patterns.value(rule, x) != y), None)
    label = f"Rule {chr(65 + index)}"
    if mismatch is None:
        return True, (f"{label} matches every displayed example and gives {outputs[index]} "
                      f"for input {query}.")
    x, y = mismatch
    return False, (f"{answer.strip()} is the output of {label} for input {query}. "
                   f"But that rule gives {patterns.value(rule, x)} for input {x}, "
                   f"while the displayed example gives {y}. A valid rule must fit every example.")


def _bayesian(model: dict, answer: str) -> tuple[bool, str] | None:
    index = _index(model["names"], answer)
    if index is None:
        return None
    values = [Fraction(p) for p in model["posterior"]]
    best = max(values)
    if values.count(best) != 1:
        return None
    name, probability = model["names"][index], values[index]
    if probability == best:
        return True, (f"After combining the prior weights with the observed readouts, "
                      f"{name} has the largest probability, {probability}. Most likely "
                      "does not mean certain.")
    return False, (f"After combining the prior weights with the observed readouts, "
                   f"{name} has probability {probability}. Another card has probability "
                   f"{best}, which is higher. Use both the prior and every observed readout.")


def _planning(model: dict, answer: str) -> tuple[bool, str] | None:
    labels = [f"Question {chr(65 + i)}" for i in range(len(model["tests"]))]
    index = _index(labels, answer)
    if index is None:
        return None
    values = [Fraction(p) for p in model["expected_questions"]]
    best = min(values)
    if values.count(best) != 1:
        return None
    cost = values[index]
    if cost == best:
        return True, (f"{labels[index]} gives the lowest expected total, {cost} questions, "
                      "including the first question and optimal follow-ups on both branches.")
    return False, (f"Starting with {labels[index]} requires an expected total of {cost} "
                   f"questions, even with optimal follow-ups. The best first question "
                   f"has expected total {best}; this choice costs {cost - best} extra on "
                   "average. Account for both yes and no branches.")


def _placement(rows, clues, holds, assumption, description: str, clue_text
               ) -> tuple[bool, str] | None:
    valid = [row for row in rows if all(holds(clue, row) for clue in clues)]
    if not valid:
        return None
    if all(assumption(row) for row in valid):
        return True, (f"The clues force {description}. Excluding that placement leaves "
                      "no arrangement satisfying every clue.")
    if any(assumption(row) for row in valid):
        # A possible but unforced placement is not an impossible placement.
        return None
    remaining = [row for row in rows if assumption(row)]
    if not remaining:
        return None
    for index, clue in enumerate(clues):
        remaining = [row for row in remaining if holds(clue, row)]
        if not remaining:
            prefix = f"Clues 1–{index + 1} together rule out" if index else "Clue 1 rules out"
            return False, (f"{prefix} {description}. Under that assumption, "
                           f"every arrangement left before clue {index + 1} conflicts "
                           f"with it: {clue_text(clue)}")
    return None


def _deduction(model: dict, answer: str) -> tuple[bool, str] | None:
    names = model["names"]
    index = _index(names, answer)
    if index is None:
        return None
    position = model["position"]
    return _placement(
        deduction.worlds(len(names)), [deduction.Clue(**c) for c in model["clues"]],
        deduction.holds, lambda row: row[index] == position,
        f"{names[index]} in position {position + 1}",
        lambda clue: deduction.text(clue, names, concise=True),
    )


def _grid(proof: dict, answer: str, choices: list[str]) -> tuple[bool, str] | None:
    model, query = proof["model"], proof["query"]
    target, group = query["target"], query["answer_group"]
    rules = [*proof["authored_rules"], *proof["added_rules"]]
    if _normalized(answer) == "none of these":
        allowed = ([str(p) for p in range(1, model["size"] + 1)] if group == -1 else
                   [model["names"][i] for i in model["groups"][group]["indices"]])
        if ({_normalized(choice) for choice in choices}
                != {_normalized(value) for value in [*allowed, "None of these"]}
                or not logic_grid.survivors(model, rules)):
            return None
        placement = (f"{model['names'][target]} in exactly one of positions "
                     + ", ".join(allowed) if group == -1 else
                     f"{model['names'][target]} with exactly one value from "
                     f"{model['groups'][group]['name']}: " + ", ".join(allowed))
        verb = "place" if group == -1 else "pair"
        return False, (f"The grid rules {verb} {placement}. All these answers are listed, "
                       "and an arrangement satisfies every clue, so None of these cannot "
                       "be right.")
    if group == -1:
        index = _index(range(1, model["size"] + 1), answer)
        if index is None:
            return None
        position = index + 1
        def assumption(row):
            return row[target] == position

        description = f"{model['names'][target]} in position {position}"
    else:
        indices = model["groups"][group]["indices"]
        index = _index([model["names"][i] for i in indices], answer)
        if index is None:
            return None
        selected = indices[index]
        def assumption(row):
            return row[target] == row[selected]

        description = f"{model['names'][target]} paired with {model['names'][selected]}"
    return _placement(
        logic_grid.worlds(model["size"], len(model["groups"])),
        rules, logic_grid.holds,
        assumption, description, lambda clue: clue["text"].rstrip(".") + ".",
    )


def _contradiction(model: dict, answer: str) -> tuple[bool, str] | None:
    labels = [f"Statement {chr(65 + i)}" for i in range(len(model["options"]))]
    index = _index(labels, answer)
    if index is None:
        index = _index([chr(65 + i) for i in range(len(labels))], answer)
    if index is None:
        return None
    names = model["names"]
    clues = [deduction.Clue(**c) for c in model["clues"]]
    option = deduction.Clue(**model["options"][index])
    rows = deduction.survivors(deduction.worlds(len(names)), clues)
    if not rows:
        return None
    possible = any(deduction.holds(option, row) for row in rows)
    if possible:
        return False, (f"{labels[index]} can hold together with every base clue: "
                       f"{deduction.text(option, names, concise=True)} "
                       "The question asks for a statement that cannot hold.")
    if option.kind == "before" and all(row[option.b] < row[option.a] for row in rows):
        return True, (f"{labels[index]} puts {names[option.a]} before {names[option.b]}, "
                      f"but the base clues force {names[option.b]} before {names[option.a]}. "
                      "Those two requirements cannot both hold.")
    return None


def _resource_plan(proof: dict, answer: str) -> tuple[bool, str] | None:
    options = proof["option_costs"]
    labels = list(options)
    index = _index(labels, answer)
    if index is None:
        index = _index([label[-1] for label in labels], answer)
    if index is None:
        return None
    label = labels[index]
    option = options[label]
    if not option["feasible"]:
        return False, (f"{label} cannot complete the deliveries under all the rules. "
                       + " ".join(option["reasons"]))
    if option["is_answer"]:
        return True, (f"{label} meets the fuel limit, every deadline and every prerequisite. "
                      f"Its complete trip takes {option['time']} minutes and "
                      f"{option['fuel']} fuel; no feasible order is faster.")
    return False, (f"{label} meets the constraints but takes {option['time']} minutes. "
                   "Another feasible order finishes sooner. Compare the complete trips.")


def _specific(proof: dict, answer: str, choices: list[str]) -> tuple[bool, str] | None:
    if proof.get("agree") is not True or not isinstance(proof.get("model"), dict):
        return None
    method = proof.get("method")
    if method == "custom-grid-z3-and-exhaustive-permutations":
        return _grid(proof, answer, choices)
    if method == "subset-dp-and-independent-complete-trip-replay":
        return _resource_plan(proof, answer)
    handlers = {
        "dijkstra-and-exhaustive-route-replay": _route,
        "finite-rule-enumeration-and-z3": _pattern,
        "exact-bayes-and-independent-finite-experiment": _bayesian,
        "bellman-planning-and-exhaustive-policy-check": _planning,
        "z3-and-exhaustive-constraint-search": _deduction,
        "z3-and-exhaustive-option-consistency": _contradiction,
    }
    handler = handlers.get(method)
    return handler(proof["model"], answer) if handler else None


def feedback_for(item: dict, proof: dict, answer: str) -> dict:
    """Grade text and return ``{correct: bool, message: str, supported: bool}``.

    Inputs must belong to one fully verified bundle. Matching uses Unicode NFKC,
    case folding and collapsed whitespace; meaningful punctuation is preserved.
    Typed questions accept the saved aliases. True/false questions only accept
    the canonical words True and False, and coaching concerns the proof's claim.
    The function never returns the full saved explanation or proof trace.
    """
    if not isinstance(answer, str):
        raise ValueError("Answer must be text")
    kind = item.get("type")
    if kind not in {"multiple-choice", "true-false", "type-answer", "riddle"}:
        return {"correct": False, "message": "This activity has no supported answer check.",
                "supported": False}
    response = _normalized(answer)
    if not response:
        return {"correct": False, "message": "Enter an answer to check.", "supported": False}
    if kind == "true-false" and response not in {"true", "false"}:
        return {"correct": False, "message": "Choose True or False to check this claim.",
                "supported": False}
    accepted = [item["correctAnswer"]]
    if kind in {"type-answer", "riddle"}:
        accepted.extend(item.get("acceptedAnswers", []))
    correct = response in {_normalized(value) for value in accepted}
    selected = item["correctAnswer"] if correct else answer
    expected = correct
    if kind == "true-false":
        selected = proof.get("claim")
        expected = proof.get("claim_holds")
    specific = (_specific(proof, selected, item.get("choices", []))
                if isinstance(selected, str) and type(expected) is bool else None)
    if specific is not None and specific[0] == expected:
        verdict = "Correct. " if correct else "Not quite. "
        claim = f"The claim is {str(expected).lower()}. " if kind == "true-false" else ""
        return {"correct": correct, "message": verdict + claim + specific[1], "supported": True}
    message = ("Correct. Your answer matches the verified answer." if correct else
               "That answer does not match the verified answer. Recheck the stated rules "
               "or use a hint.")
    return {"correct": correct, "message": message, "supported": False}


def _grid_world_mask(rows, predicate) -> int:
    """Represent the bounded enumeration as a bit set for cheap subset checks."""
    bits = bytearray((len(rows) + 7) // 8)
    for index, row in enumerate(rows):
        if predicate(row):
            bits[index // 8] |= 1 << (index % 8)
    return int.from_bytes(bits, "little")


def _minimal_grid_cells(possible: int, assignments: list[tuple[int, int]]) -> list[int]:
    # At most twelve submitted cells: check cardinality, then row-major order.
    # A conflict names a set that cannot hold together, not individually wrong cells.
    for size in range(1, len(assignments) + 1):
        for subset in combinations(assignments, size):
            remaining = possible
            for _, mask in subset:
                remaining &= mask
            if not remaining:
                return [cell for cell, _ in subset]
    raise RuntimeError("Could not isolate the grid entry conflict")


def grid_feedback(proof: dict, entries: object) -> dict:
    """Diagnose a row-major grid from an already verified complete bundle.

    ``entries`` is a list of text values in solution-table row/group order; empty
    or whitespace-only text leaves a cell blank. Values are matched only within
    the cell's group, using the same normalization as quiz answers. Invalid input
    raises ``ValueError``. The proof's saved solution values are never compared.

    ``complete`` means every cell is filled; ``correct`` requires a complete,
    consistent grid. Each conflict contains zero-based ``cells``, ``kind``,
    one-based ``clue_numbers``, and ``message``. A clue conflict's cells form a
    smallest conflicting subset under the cited clue(s), with row-major ties.
    """
    if (not isinstance(proof, dict) or proof.get("agree") is not True
            or proof.get("method") != "custom-grid-z3-and-exhaustive-permutations"):
        raise ValueError("Grid feedback requires an already verified logic-grid proof")
    model, table = proof["model"], proof["solution_table"]
    groups = model["groups"]
    count = len(table) * len(groups)
    if not isinstance(entries, list) or len(entries) != count or count > 12:
        raise ValueError(f"Grid entries must be an array of exactly {count} text values")
    if any(not isinstance(value, str) for value in entries):
        raise ValueError("Every grid entry must be text; use an empty string for a blank cell")

    selected = {}
    for cell, value in enumerate(entries):
        if not _normalized(value):
            continue
        group = groups[cell % len(groups)]
        label = _index([model["names"][i] for i in group["indices"]], value)
        if label is None:
            raise ValueError(f"Grid cell {cell + 1} must use a value from {group['name']}")
        selected[cell] = (group["indices"][label], table[cell // len(groups)]["Position"])
    complete = len(selected) == count

    def result(message, conflicts=()):
        return {"correct": complete and not conflicts, "complete": complete,
                "consistent": not conflicts, "message": message, "conflicts": list(conflicts)}

    duplicates = []
    for group in groups:
        for label in group["indices"]:
            cells = [cell for cell, (value, _) in selected.items() if value == label]
            if len(cells) > 1:
                positions = ", ".join(str(selected[cell][1]) for cell in cells)
                message = (f"{model['names'][label]} appears in positions {positions}. "
                           f"Each {group['name']} value must be used exactly once; "
                           "at least one of these entries must change.")
                duplicates.append({"cells": cells, "kind": "duplicate",
                                   "clue_numbers": [], "message": message})
    if duplicates:
        return result(" ".join(conflict["message"] for conflict in duplicates), duplicates)
    if not selected:
        return result("No entries yet. Continue by placing a value, then check again.")

    rows = logic_grid.worlds(model["size"], len(groups))
    assignments = [(cell, _grid_world_mask(rows, lambda row, v=v, p=p: row[v] == p))
                   for cell, (v, p) in selected.items()]
    prefix = (1 << len(rows)) - 1
    submitted = prefix
    for _, mask in assignments:
        submitted &= mask
    rules = [*proof["authored_rules"], *proof["added_rules"]]
    first_combined = None

    def conflict(possible, numbers, kind):
        cells = _minimal_grid_cells(possible, assignments)
        placements = "; ".join(f"{model['names'][selected[cell][0]]} "
                               f"at position {selected[cell][1]}" for cell in cells)
        last = numbers[-1]
        clue = rules[last - 1]["text"].rstrip(".")
        if kind == "clue":
            message = (f"Clue {last} rules out these entries together: {placements}. "
                       f"The clue says: {clue}.")
        else:
            message = (f"Clues 1–{last} together rule out these entries: {placements}. "
                       "Each clue separately allows these entries, but their combination "
                       f"leaves no complete grid. The final clue in this combination says: {clue}.")
        message += " Reconsider at least one highlighted entry."
        return result(message, [{"cells": cells, "kind": kind,
                                 "clue_numbers": numbers, "message": message}])

    for number, rule in enumerate(rules, start=1):
        mask = _grid_world_mask(rows, lambda row, rule=rule: logic_grid.holds(rule, row))
        # Prefer an actionable single-clue explanation, even if earlier clues
        # already rule out the entries cumulatively.
        if not submitted & mask:
            return conflict(mask, [number], "clue")
        prefix &= mask
        if not submitted & prefix and first_combined is None:
            first_combined = number, prefix
    if first_combined is not None:
        number, possible = first_combined
        return conflict(possible, list(range(1, number + 1)), "combined")
    if complete:
        return result("Correct. The complete grid uses every value once and satisfies every clue.")
    return result("These entries are consistent with every clue. "
                  f"Continue filling the {count - len(selected)} remaining cells.")
