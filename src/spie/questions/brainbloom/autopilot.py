"""Bounded autonomous topic-to-grid design; no creator-authored rules required."""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations

from ...forge.corpus import digest
from . import logic_grid
from .catalog import DIFFICULTIES
from .topics import sample_words

BUDGET = 6
GROUPS = ("Cards", "Badges", "Tokens")


def supporting_clues(model: dict, rules: list[dict], solution, query: dict) -> list[int]:
    """Smallest sufficient subset for the question, independent of clue order."""
    target, group = query["target"], query["answer_group"]
    partner = (None if group == -1 else next(
        i for i in model["groups"][group]["indices"] if solution[i] == solution[target]
    ))
    alternatives = [row for row in logic_grid.worlds(model["size"], len(model["groups"]))
                    if (row[target] != solution[target] if partner is None
                        else row[target] != row[partner])]
    # A subset forces the answer iff it excludes every wrong-answer world.
    masks = [sum(1 << i for i, row in enumerate(alternatives)
                 if not logic_grid.holds(rule, row)) for rule in rules]
    required = (1 << len(alternatives)) - 1
    for size in range(len(rules) + 1):
        for subset in combinations(range(len(rules)), size):
            covered = 0
            for index in subset:
                covered |= masks[index]
            if covered == required:
                return [i + 1 for i in subset]
    raise RuntimeError("The verified grid does not force its question answer")


def candidate(request, rng, context: dict) -> tuple[dict, dict]:
    level = DIFFICULTIES[request.difficulty]
    candidates = []
    for attempt in range(BUDGET):
        names = sample_words(context, level * 3, rng)
        spec = {
            "groups": "\n".join(f"{GROUPS[g]}: " + ", ".join(names[g * 3:g * 3 + 3])
                                 for g in range(level)),
            "rules": "", "complete": True,
            "target": rng.choice(names[:3]),
            "answer_group": "Position" if level == 1 else GROUPS[level - 1],
        }
        inner = replace(request, topic="logic-grid", topic_mode="single", subject="",
                        meanings={}, instructions="", grid=spec, count=1)
        item, proof = logic_grid.candidate(inner, rng)
        support = supporting_clues(proof["model"], proof["added_rules"],
                                   proof["solution_positions"], proof["query"])
        # A question copied from one clue is not an autonomous reasoning challenge.
        if len(support) < 2:
            continue
        diversity = len({r["kind"] for r in proof["added_rules"]})
        score = (len(support), diversity, -len(proof["added_rules"]))
        candidates.append((score, attempt, item, proof, support, spec))
    if not candidates:
        raise ValueError("No multi-clue design met the checks in this search. "
                         "Try another variation number or another level.")
    score, attempt, item, proof, support, spec = max(candidates, key=lambda row: row[0])
    item["title"] = f"{context['label'].title()} · clue challenge"
    item["question"] = (f"Topics: {context['label']}. These words label fictional cards and "
                        "objects; their pairings do not describe real-world facts.\n"
                        + item["question"])
    proof["autopilot"] = {
        "version": "autopilot-design-v1", "spec": spec,
        "decisions": [
            f"Selected {level * 3} labels covering every chosen topic.",
            f"Created {level} groups across three positions.",
            "Invented a hidden arrangement, then generated and pruned its clues.",
            f"Selected a question requiring at least {len(support)} clues together.",
            "Checked the unique complete solution using enumeration and Z3.",
        ],
        "minimum_supporting_clues": len(support), "supporting_clues": support,
    }
    proof["search"] = {
        "budget": BUDGET, "qualified": len(candidates),
        "rejected": BUDGET - len(candidates), "selected_attempt": attempt,
        "selected_score": list(score), "first_qualified_score": list(candidates[0][0]),
        "objective": "More supporting clues, then clue variety, then fewer total clues; "
                     "structural heuristic, not player-calibrated difficulty",
    }
    proof["dictionary_sha256"] = digest(context)
    return item, proof
