"""Creator-authored finite logic grids, exhaustive checking and independent SMT proof."""

from __future__ import annotations

import random
import re
from functools import lru_cache
from itertools import permutations, product

import z3

from ...forge.contract import XP
from ...forge.corpus import digest
from .. import prover

EXAMPLE = {
    "groups": "Animal: Tiger, Lion, Owl\nColour: Red, Blue, Green\nDrink: Tea, Coffee, Milk",
    "rules": ("Tiger is before Lion.\nOwl cannot be next to Tiger.\n"
              "Tiger is paired with Red.\nBlue is paired with Coffee.\nTea is in position 1."),
    "complete": True, "target": "Lion", "answer_group": "Drink",
}
LABEL = re.compile(r"[A-Za-z][A-Za-z0-9 -]{0,29}\Z")


def parse(spec: object) -> dict:
    if spec is None:
        spec = dict(EXAMPLE)
    if not isinstance(spec, dict) or set(spec) - {
        "groups", "rules", "complete", "target", "answer_group",
    }:
        raise ValueError("Supply groups, rules, completion mode and an optional question target")
    for key, limit in (("groups", 600), ("rules", 1600), ("target", 30), ("answer_group", 30)):
        if not isinstance(spec.get(key, ""), str) or len(spec.get(key, "")) > limit:
            raise ValueError(f"{key} must be text of at most {limit} characters")
    if type(spec.get("complete", True)) is not bool:
        raise ValueError("Completion mode must be true or false")
    groups, names, owners, seen = [], [], [], set()
    for line in spec.get("groups", "").splitlines():
        if not line.strip():
            continue
        label, separator, values = line.partition(":")
        label = " ".join(label.split())
        entries = [" ".join(v.split()) for v in values.split(",")]
        if (not separator or not LABEL.fullmatch(label)
                or label.casefold() == "position"
                or any(not LABEL.fullmatch(value) for value in entries)):
            raise ValueError("Use lines such as 'Animal: Tiger, Lion, Owl'; labels use letters, "
                             "numbers, spaces or hyphens. 'Position' is reserved.")
        if any(g["name"].casefold() == label.casefold() for g in groups):
            raise ValueError("Give each group a different name")
        for value in entries:
            if value.casefold() in seen or value.casefold() == "none of these":
                raise ValueError("Use a different label for every value across all groups")
            seen.add(value.casefold())
        indices = list(range(len(names), len(names) + len(entries)))
        owners.extend([len(groups)] * len(entries))
        names.extend(entries)
        groups.append({"name": label, "values": entries, "indices": indices})
    if not 1 <= len(groups) <= 3:
        raise ValueError("Define one to three groups")
    size = len(groups[0]["values"])
    if size not in (3, 4) or any(len(g["values"]) != size for g in groups):
        raise ValueError("Every group must contain the same number of values: three or four")
    lookup = {name.casefold(): i for i, name in enumerate(names)}
    atom = "(?:" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + ")"
    a, b, c = f"(?P<a>{atom})", f"(?P<b>{atom})", f"(?P<c>{atom})"
    patterns = [
        ("not-next", rf"{a} (?:cannot be|is not) next to {b}"),
        ("next", rf"{a} (?:is|must be) next to {b}"),
        ("immediate", rf"{a} (?:is|must be) immediately before {b}"),
        ("before", rf"{a} (?:(?:is|must (?:be|appear)) )?before {b}"),
        ("after", rf"{a} (?:(?:is|must (?:be|appear)) )?after {b}"),
        ("not-paired", rf"{a} (?:is not|cannot be) paired with {b}"),
        ("paired", rf"{a} (?:is|must be) paired with {b}"),
        ("not-at", rf"{a} (?:is not|cannot be) in position (?P<n>[1-4])"),
        ("at", rf"{a} (?:is|must be) in position (?P<n>[1-4])"),
        ("distance", rf"{a} is (?P<n>[1-3]) positions? away from {b}"),
        ("between", rf"{a} is between {b} and {c}"),
    ]
    rules = []
    for line in re.split(r"[.;\n]+", spec.get("rules", "")):
        line = " ".join(line.split())
        if not line:
            continue
        for kind, pattern in patterns:
            match = re.fullmatch(pattern, line, re.I)
            if match:
                fields = match.groupdict()
                rule = {"kind": kind, "a": lookup[fields["a"].casefold()], "text": line}
                for key in ("b", "c"):
                    if fields.get(key):
                        rule[key] = lookup[fields[key].casefold()]
                if fields.get("n"):
                    rule["n"] = int(fields["n"])
                    if kind in ("at", "not-at") and rule["n"] > size:
                        raise ValueError(f"Rule {len(rules) + 1}: positions run from 1 to {size}")
                rules.append(rule)
                break
        else:
            raise ValueError(f"Rule {len(rules) + 1} is not recognised: {line}. "
                             "Use exact labels and one of the displayed rule patterns.")
    if len(rules) > 20:
        raise ValueError("Use at most 20 rules")
    target = spec.get("target", "").strip()
    destination = spec.get("answer_group", "").strip()
    if target and target.casefold() not in lookup:
        raise ValueError("Choose a question target from your group values")
    group_lookup = {g["name"].casefold(): i for i, g in enumerate(groups)}
    if destination and destination.casefold() not in ("position", *group_lookup):
        raise ValueError("Choose Position or one of your groups for the answer")
    target_index = lookup.get(target.casefold())
    destination_index = group_lookup.get(destination.casefold(), -1 if destination else None)
    if (target_index is not None and destination_index is not None
            and destination_index == owners[target_index]):
        raise ValueError("Ask about another group or Position, not the target's own group")
    if len(groups) == 1 and destination_index == 0:
        raise ValueError("With one group, choose Position as the answer or leave it automatic")
    return {"groups": groups, "names": names, "owners": owners, "size": size, "rules": rules,
            "complete": spec.get("complete", True), "target": target_index,
            "answer_group": destination_index}


@lru_cache(maxsize=6)
def worlds(size: int, group_count: int) -> tuple[tuple[int, ...], ...]:
    if size not in (3, 4) or not 1 <= group_count <= 3:
        raise ValueError("Grid enumeration exceeds the supported bounds")
    return tuple(tuple(v for group in groups for v in group)
                 for groups in product(tuple(permutations(range(1, size + 1))), repeat=group_count))


def holds(rule: dict, row: tuple[int, ...]) -> bool:
    a, b = row[rule["a"]], row[rule.get("b", rule["a"])]
    kind = rule["kind"]
    if kind == "before":
        return a < b
    if kind == "after":
        return a > b
    if kind == "immediate":
        return a + 1 == b
    if kind == "next":
        return abs(a - b) == 1
    if kind == "not-next":
        return abs(a - b) != 1
    if kind == "paired":
        return a == b
    if kind == "not-paired":
        return a != b
    if kind == "at":
        return a == rule["n"]
    if kind == "not-at":
        return a != rule["n"]
    if kind == "distance":
        return abs(a - b) == rule["n"]
    if kind == "between":
        c = row[rule["c"]]
        return b < a < c or c < a < b
    raise ValueError("Unknown rule kind")


def survivors(model: dict, rules: list[dict]) -> list[tuple[int, ...]]:
    return [row for row in worlds(model["size"], len(model["groups"]))
            if all(holds(rule, row) for rule in rules)]


def _formula(model: dict, rules: list[dict]):
    positions = [z3.Int(f"grid_{i}") for i in range(len(model["names"]))]
    expressions = [z3.And(p >= 1, p <= model["size"]) for p in positions]
    expressions.extend(z3.Distinct(*[positions[i] for i in g["indices"]]) for g in model["groups"])
    for rule in rules:
        a, b = positions[rule["a"]], positions[rule.get("b", rule["a"])]
        kind = rule["kind"]
        if kind == "before":
            value = a < b
        elif kind == "after":
            value = a > b
        elif kind == "immediate":
            value = b - a == 1
        elif kind in ("next", "not-next", "distance"):
            gap = rule["n"] if kind == "distance" else 1
            value = z3.Or(a - b == gap, b - a == gap)
            if kind == "not-next":
                value = z3.Not(value)
        elif kind in ("paired", "not-paired"):
            value = a == b if kind == "paired" else a != b
        elif kind in ("at", "not-at"):
            value = a == rule["n"] if kind == "at" else a != rule["n"]
        else:
            c = positions[rule["c"]]
            value = z3.Or(z3.And(b < a, a < c), z3.And(c < a, a < b))
        expressions.append(value)
    return z3.And(*expressions), positions


def check(model: dict, rules: list[dict]) -> list[tuple[int, ...]]:
    rows = survivors(model, rules)
    formula, positions = _formula(model, rules)
    sat, _ = prover.satisfiable(formula)
    if sat != bool(rows):
        raise RuntimeError("Z3/enumeration consistency disagreement")
    if rows:
        unique, _ = prover.decide(z3.Implies(formula, z3.And(*[
            p == v for p, v in zip(positions, rows[0], strict=True)
        ])))
        if unique != (len(rows) == 1):
            raise RuntimeError("Z3/enumeration uniqueness disagreement")
        # Check the displayed witnesses independently in the SMT encoding.
        for row in rows[:2]:
            valid, _ = prover.satisfiable(z3.And(formula, *[
                p == v for p, v in zip(positions, row, strict=True)
            ]))
            if not valid:
                raise RuntimeError("Z3 rejected an enumerated witness")
    return rows


def table(model: dict, row: tuple[int, ...]) -> list[dict]:
    return [{"Position": p, **{g["name"]: next(model["names"][i] for i in g["indices"]
                                            if row[i] == p) for g in model["groups"]}}
            for p in range(1, model["size"] + 1)]


def analyze(spec: object) -> dict:
    model = parse(spec)
    rows = check(model, model["rules"])
    conflicts = []
    if not rows:
        indices = list(range(len(model["rules"])))
        for index in list(indices):
            rest = [i for i in indices if i != index]
            if not survivors(model, [model["rules"][i] for i in rest]):
                indices = rest
        conflicts = [{"number": i + 1, "text": model["rules"][i]["text"]} for i in indices]
    queries = _queries(model)
    return {"status": "contradictory" if not rows else "unique" if len(rows) == 1 else "ambiguous",
            "solution_count": len(rows), "conflicts": conflicts,
            "witnesses": [table(model, row) for row in rows[:2]] if len(rows) > 1 else [],
            "groups": model["groups"], "rule_count": len(model["rules"]),
            "max_count": min(20, len(queries) * len(rows)),
            "difficulty": ("easy", "medium", "hard")[len(model["groups"]) - 1]}


def _queries(model):
    return [(i, group) for i in range(len(model["names"]))
            for group in [-1, *range(len(model["groups"]))]
            if group != model["owners"][i]
            and (model["target"] is None or i == model["target"])
            and (model["answer_group"] is None or group == model["answer_group"])]


def _suggestions(model: dict, solution, rng) -> list[dict]:
    names, owners = model["names"], model["owners"]
    clues = []
    for a, name in enumerate(names):
        # Positional clues guarantee that completion can terminate.
        clues.append({"kind": "at", "a": a, "n": solution[a],
                      "text": f"{name} is in position {solution[a]}"})
        for b in range(a + 1, len(names)):
            other = names[b]
            if solution[a] == solution[b] and owners[a] != owners[b]:
                clues.append({"kind": "paired", "a": a, "b": b,
                              "text": f"{name} is paired with {other}"})
            elif solution[a] != solution[b]:
                left, right = (a, b) if solution[a] < solution[b] else (b, a)
                clues.append({"kind": "before", "a": left, "b": right,
                              "text": f"{names[left]} is before {names[right]}"})
                if abs(solution[a] - solution[b]) == 1:
                    clues.append({"kind": "next", "a": a, "b": b,
                                  "text": f"{name} is next to {other}"})
    rng.shuffle(clues)
    return clues


def candidate(request, rng: random.Random) -> tuple[dict, dict]:
    model = parse(request.grid)
    initial = check(model, model["rules"])
    if not initial:
        conflict = analyze(request.grid)["conflicts"]
        raise ValueError("Your rules conflict: " + "; ".join(
            f"{c['number']}. {c['text']}" for c in conflict))
    if len(initial) > 1 and not model["complete"]:
        raise ValueError(
            f"Your rules allow {len(initial)} arrangements. Add rules or enable completion."
        )
    capacity = min(20, len(_queries(model)) * len(initial))
    if request.count > capacity:
        raise ValueError(f"These settings allow at most {capacity} distinct grid/question pairs")
    solution = rng.choice(initial)
    added, remaining = [], initial
    pool = _suggestions(model, solution, rng) if len(initial) > 1 else []
    while len(remaining) > 1:
        proposals = []
        for clue in pool:
            reduced = [row for row in remaining if holds(clue, row)]
            if 0 < len(reduced) < len(remaining):
                # Prefer relational clues; direct positions remain a bounded fallback.
                proposals.append((clue["kind"] == "at", len(reduced), clue, reduced))
        if not proposals:
            raise RuntimeError("Could not complete a consistent grid")
        best = min(proposals, key=lambda p: p[:2])
        added.append(best[2])
        remaining = best[3]
    for clue in list(added):
        other = [c for c in added if c is not clue]
        if len(survivors(model, [*model["rules"], *other])) == 1:
            added.remove(clue)
    rules = [*model["rules"], *added]
    checked = check(model, rules)
    if checked != [solution]:
        raise RuntimeError("Completed grid does not match its unique solution")
    if request.engine_revision == 1:
        from .legacy_grid_quality import assess
    else:
        from .grid_quality import assess

    quality = assess(model, rules, solution)
    if request.engine_revision == 1 and quality["score"] < 40:
        raise RuntimeError(
            "Quality gate rejected this grid: the clues do not support a fair human-style solve"
        )
    target, group = rng.choice(_queries(model))
    if group == -1:
        answer = str(solution[target])
        options = [str(p) for p in range(1, model["size"] + 1)]
        question = f"Which position contains {model['names'][target]}?"
    else:
        indices = model["groups"][group]["indices"]
        answer = next(model["names"][i] for i in indices if solution[i] == solution[target])
        options = [model["names"][i] for i in indices]
        question = (f"Which value from {model['groups'][group]['name']} is paired with "
                    f"{model['names'][target]}?")
    stem = ("This is an invented logic grid. Each position contains exactly one value from each "
            f"group, and each value is used once. Positions run from 1 to {model['size']}, "
            "left to right. Values in the same position are paired.\n"
            + "\n".join(f"{g['name']}: {', '.join(g['values'])}." for g in model["groups"])
            + "\nClues:\n" + "\n".join(f"{i + 1}. {r['text']}." for i, r in enumerate(rules))
            + "\n" + question)
    trace, steps, current = [], [], list(worlds(model["size"], len(model["groups"])))
    previous_fixed = set()
    for index, rule in enumerate(rules):
        current = [row for row in current if holds(rule, row)]
        fixed = {(i, next(iter(values))) for i in range(len(model["names"]))
                 if len(values := {row[i] for row in current}) == 1}
        deductions = [f"{model['names'][i]} must be in position {p}"
                      for i, p in sorted(fixed - previous_fixed)]
        trace.append({"clue": index + 1, "remaining": len(current), "deductions": deductions})
        steps.append(f"After clue {index + 1}, {len(current)} arrangements remain. "
                     + "; ".join(deductions))
        previous_fixed = fixed
    solution_table = table(model, solution)
    if request.engine_revision != 1:
        steps = list(quality["explanation_steps"])
        if not quality["propagation_complete"]:
            steps.append("These deductions narrow the grid but do not finish it. "
                         "Exhaustive checking of all remaining arrangements gives the "
                         "single solution below.")
    steps.extend("Position " + str(row["Position"]) + ": "
                 + ", ".join(row[g["name"]] for g in model["groups"]) + "."
                 for row in solution_table)
    explanation = f"The unique complete arrangement gives {answer}. Every stated rule holds."
    item = {"type": request.qtype, "category": request.category, "difficulty": request.difficulty,
            "title": "Your custom logic grid", "question": stem, "choices": [],
            "correctAnswer": answer, "correctExplanation": explanation,
            "incorrectExplanation": "Check the clue combinations. " + explanation,
            "lessonGroup": {"logic": "Solve It", "riddles": "Brain Busters",
                            "science": "Science Mix", "puzzles": "Think Different",
                            "wonders": "Think Deeper"}[request.category],
            "xpReward": XP[request.difficulty],
            "lessonContent": "\n".join(("Place each group value exactly once.",
                "Translate each clue into positions or pairings.",
                "Combine clues across groups to eliminate impossible arrangements.",
                "Check all clues against the completed table.",
                "Share this: explain which combination of clues fixed the answer."))}
    if len(options) == 3:
        options.append("None of these")
    proof = {"method": "custom-grid-z3-and-exhaustive-permutations",
             "scope": ("the stated fictional groups and rules; complete-grid uniqueness "
                       + ("and human-solving quality" if request.engine_revision == 1 else
                          "and checked deductions; no human difficulty or enjoyment claim")),
             "z3_version": prover.z3_version(), "agree": True,
             "model": model, "authored_rules": model["rules"], "added_rules": added,
             "initial_solutions": len(initial), "solution_count": 1,
             "solution_table": solution_table, "solution_positions": list(solution),
             "quality": quality, "quality_gate": "passed",
             "query": {"target": target, "answer_group": group}, "trace": trace, "steps": steps,
             "structural_key": digest([model["groups"], solution, target, group])}
    if request.engine_revision != 1:
        from .structural import grid_key

        proof["structural_key"] = grid_key(model, rules, solution, target, group)
        proof["structural_key_version"] = "grid-structure-v2"
        proof["quality_gate"] = "structural-analysis-complete"
    if request.qtype == "multiple-choice":
        rng.shuffle(options)
        item["choices"] = options
    elif request.qtype == "true-false":
        truth = bool(rng.randrange(2))
        claim = answer if truth else rng.choice([v for v in options
                                                if v not in (answer, "None of these")])
        item.update(choices=["True", "False"], correctAnswer=str(truth),
                    question=stem + f"\nTrue or False: the answer is {claim}.",
                    correctExplanation=f"The claim is {str(truth).lower()}. " + explanation)
        proof.update(claim=claim, claim_holds=truth)
    else:
        item["acceptedAnswers"] = [answer, "the answer is " + answer, "answer: " + answer]
        if request.qtype == "riddle":
            item["hintText"] = "\n".join(quality["hints"])
    return item, proof
