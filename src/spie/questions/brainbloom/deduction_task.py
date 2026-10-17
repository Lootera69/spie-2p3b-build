"""Certify the deduction task after choosing the player's answer domain or claim."""

from __future__ import annotations

from itertools import combinations

import z3

from .. import prover
from . import deduction


def _subset_targets(model: dict) -> list[tuple[tuple[int, ...], frozenset[int]]]:
    rows = deduction.worlds(len(model["names"]))
    clues = [deduction.Clue(**clue) for clue in model["clues"]]
    masks = [deduction.mask_for(clue, rows) for clue in clues]
    universe = (1 << len(rows)) - 1
    position = model["position"]
    target_masks = [sum(1 << i for i, row in enumerate(rows) if row[card] == position)
                    for card in range(len(model["names"]))]
    results = []
    for size in range(len(clues) + 1):
        for indices in combinations(range(len(clues)), size):
            remaining = universe
            for index in indices:
                remaining &= masks[index]
            if not remaining:
                raise RuntimeError("A deduction clue subset unexpectedly has no model")
            possible = frozenset(card for card, mask in enumerate(target_masks)
                                 if remaining & mask)
            results.append((indices, possible))
    return results


def candidates(model: dict, qtype: str, minimum: int) -> list[dict]:
    """Return presentations meeting the level's gate, without spending random draws."""
    answer = model["answer_index"]
    names = model["names"]
    targets = _subset_targets(model)
    options = []
    if qtype == "multiple-choice":
        wrongs = [card for card in range(len(names)) if card != answer]
        for alternatives in combinations(wrongs, 3):
            domain = frozenset((answer, *alternatives))
            indices = next(indices for indices, possible in targets
                           if possible & domain == {answer})
            if len(indices) >= minimum:
                options.append({"domain": sorted(domain), "support": list(indices)})
        if options:
            best = max(len(option["support"]) for option in options)
            options = [option for option in options if len(option["support"]) == best]
    elif qtype == "true-false":
        for card in range(len(names)):
            truth = card == answer
            indices = next(indices for indices, possible in targets
                           if (possible == {card} if truth else card not in possible))
            if len(indices) >= minimum:
                options.append({"claim": card, "truth": truth, "support": list(indices)})
        # Both verdicts must be possible so qualification cannot leak the answer.
        if {option["truth"] for option in options} != {False, True}:
            return []
    else:
        indices = next(indices for indices, possible in targets if possible == {answer})
        if len(indices) >= minimum:
            options = [{"domain": list(range(len(names))), "support": list(indices)}]
    return options


def certify(model: dict, qtype: str, presentation: dict, minimum: int) -> dict:
    """Independently encode the selected sufficient subset for an SMT cross-check."""
    names = model["names"]
    positions = [z3.Int(f"player_card_{i}") for i in range(len(names))]
    clauses = [z3.Distinct(*positions),
               *[z3.And(p >= 0, p < len(names)) for p in positions]]
    for index in presentation["support"]:
        clue = model["clues"][index]
        a, b = positions[clue["a"]], positions[clue["b"]]
        kind, k = clue["kind"], clue["k"]
        if kind == "before":
            expression = a < b
        elif kind == "adjacent":
            expression = z3.Or(a == b + 1, b == a + 1)
        elif kind == "distance":
            expression = z3.Or(a == b + k, b == a + k)
        elif kind == "not-at":
            expression = a != k
        elif kind == "between":
            c = positions[k]
            expression = z3.Or(z3.And(b < a, a < c), z3.And(c < a, a < b))
        else:
            raise RuntimeError("Unknown displayed deduction clue")
        clauses.append(expression)
    if qtype == "multiple-choice":
        clauses.append(z3.Or(*[positions[card] == model["position"]
                               for card in presentation["domain"]]))
    target = positions[presentation.get("claim", model["answer_index"])] == model["position"]
    if presentation.get("truth") is False:
        target = z3.Not(target)
    formula = z3.And(*clauses)
    sat, _ = prover.satisfiable(formula)
    entailed, _ = prover.decide(z3.Implies(formula, target))
    support = len(presentation["support"])
    if not sat or not entailed or support < minimum:
        raise RuntimeError("Displayed deduction task failed its independent support check")
    result = {
        "version": 1, "format": qtype,
        "method": "exhaustive-clue-subsets-and-independent-smt-entailment",
        "scope": ("the displayed claim" if qtype == "true-false" else
                  "the answer within the displayed candidate domain"),
        "minimum_supporting_clues": support,
        "required_supporting_clues": minimum,
        "supporting_clues": [index + 1 for index in presentation["support"]],
        "open_answer_supporting_clues": model["minimum_support"],
        "agree": True,
    }
    if qtype == "true-false":
        result.update(claim=names[presentation["claim"]], claim_holds=presentation["truth"])
    else:
        result["answer_domain"] = [names[card] for card in presentation["domain"]]
    return result
