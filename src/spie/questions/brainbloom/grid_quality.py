"""Inspectable constraint-propagation traces; no uncalibrated quality rating."""

from __future__ import annotations

import math
from itertools import permutations, product


def _possibilities(values):
    return ", ".join(map(str, sorted(values)))


def propagate(model: dict, rules: list[dict], initial=None):
    """Local rule support and all-different matching, explained per reduction."""
    from .logic_grid import holds

    size = model["size"]
    domains = ([set(range(1, size + 1)) for _ in model["names"]] if initial is None
               else [set(values) for values in initial])
    steps = []
    while all(domains):
        changed = False
        constraints = []
        for number, rule in enumerate(rules, 1):
            indices = sorted({rule[key] for key in ("a", "b", "c") if key in rule})
            allowed = []
            for values in product(*(sorted(domains[i]) for i in indices)):
                row = [0] * len(domains)
                for i, value in zip(indices, values, strict=True):
                    row[i] = value
                distinct = all(row[a] != row[b] for a in indices for b in indices
                               if a < b and model["owners"][a] == model["owners"][b])
                if distinct and holds(rule, row):
                    allowed.append(values)
            constraints.append((indices, allowed, f"Clue {number} ({rule['text']})", [number]))
        for group in model["groups"]:
            indices = group["indices"]
            allowed = [values for values in permutations(range(1, size + 1))
                       if all(value in domains[i]
                              for i, value in zip(indices, values, strict=True))]
            constraints.append((indices, allowed,
                                f"Each {group['name']} value occupies a different position", []))
        for indices, allowed, reason, clues in constraints:
            allowed = [values for values in allowed
                       if all(value in domains[i]
                              for i, value in zip(indices, values, strict=True))]
            if not allowed:
                return domains, steps, reason
            for offset, i in enumerate(indices):
                supported = {values[offset] for values in allowed}
                before = set(domains[i])
                after = before & supported
                if after == before:
                    continue
                domains[i] = after
                changed = True
                conclusion = (f"{model['names'][i]} must be in position {next(iter(after))}."
                              if len(after) == 1 else
                              f"{model['names'][i]} can only occupy positions "
                              f"{_possibilities(after)}.")
                text = (f"{reason}. With the positions still available, "
                        f"positions {_possibilities(before - after)} cannot satisfy it. "
                        + conclusion)
                steps.append({"kind": "constraint", "variable": i, "before": sorted(before),
                              "after": sorted(after), "clues": clues, "text": text})
        if not changed:
            break
    return domains, steps, None


def assess(model: dict, rules: list[dict], solution) -> dict:
    from .logic_grid import holds, worlds

    domains, steps, conflict = propagate(model, rules)
    if conflict:
        raise RuntimeError("Propagation contradicted a verified grid")
    case_count = 0
    while any(len(values) > 1 for values in domains):
        elimination = None
        for i in sorted(range(len(domains)), key=lambda i: (len(domains[i]), i)):
            if len(domains[i]) <= 1:
                continue
            for value in sorted(domains[i]):
                attempt = [set(values) for values in domains]
                attempt[i] = {value}
                _, branch_steps, reason = propagate(model, rules, attempt)
                if reason:
                    elimination = i, value, reason, branch_steps
                    break
            if elimination:
                break
        if not elimination:
            break
        i, value, reason, branch_steps = elimination
        before = sorted(domains[i])
        domains[i].remove(value)
        case_count += 1
        consequence = " ".join(s["text"] for s in branch_steps)
        text = (f"Suppose {model['names'][i]} were in position {value}. " + consequence
                + f" This leaves no possible assignment satisfying: {reason}. "
                f"So {model['names'][i]} cannot be in position {value}.")
        steps.append({"kind": "contradiction", "variable": i, "before": before,
                      "after": sorted(domains[i]), "text": text})
        domains, more, conflict = propagate(model, rules, domains)
        if conflict:
            raise RuntimeError("A contradiction deduction removed the verified solution")
        steps.extend(more)
    if any(position not in values for position, values in zip(solution, domains, strict=True)):
        raise RuntimeError("Teaching deductions disagree with the verified solution")
    complete = all(len(values) == 1 for values in domains)
    current = list(worlds(model["size"], len(model["groups"])))
    initial_count = len(current)
    trace = []
    for number, rule in enumerate(rules, 1):
        before = len(current)
        current = [row for row in current if holds(rule, row)]
        trace.append({"clue": number, "before": before, "after": len(current),
                      "useful": len(current) < before})
    useful = sum(row["useful"] for row in trace)
    direct = sum(r["kind"] in ("at", "not-at") for r in rules)
    explanations = [step["text"] for step in steps]
    warnings = []
    if not complete:
        warnings.append("Local propagation and one-level contradiction checks do not complete "
                        "this grid; exhaustive checking establishes the complete solution.")
    if useful < len(rules):
        warnings.append("Some clues do not reduce possibilities in the displayed order.")
    if direct == len(rules):
        warnings.append("Every clue gives or excludes a position directly.")
    return {"analysis_version": "grid-analysis-v2",
            "scope": "constraint propagation and explicit case checks; no player-calibrated rating",
            "candidate_count": initial_count, "reasoning_steps": len(steps),
            "useful_clues": useful, "redundant_clues": len(rules) - useful,
            "direct_clues": direct, "relational_clues": len(rules) - direct,
            "clue_kinds": len({r["kind"] for r in rules}),
            "information_gain": round(math.log2(initial_count), 4),
            "propagation_complete": complete, "case_checks": case_count,
            "remaining_domains": [sorted(values) for values in domains],
            "deductions": steps, "explanation_steps": explanations,
            "hints": explanations[:3] or ["Apply each clue to the possible positions."],
            "trace": trace, "ordered_clues": [r["text"] for r in rules], "warnings": warnings}
