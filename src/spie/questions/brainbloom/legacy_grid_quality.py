"""Deterministic human-style quality analysis for finite logic grids.

The verifier still proves the complete model with exhaustive enumeration and Z3.
This module evaluates the presentation as a player would: start with all possible
arrangements, apply useful clues, and record what each clue eliminates or fixes.
"""

from __future__ import annotations

import math


def _fixed(model: dict, rows: list[tuple[int, ...]]) -> set[tuple[int, int]]:
    if not rows:
        return set()
    return {
        (index, next(iter(values)))
        for index in range(len(model["names"]))
        if len(values := {row[index] for row in rows}) == 1
    }


def _label(model: dict, index: int, position: int) -> str:
    return f"{model['names'][index]} must be in position {position}"


def assess(model: dict, rules: list[dict], solution: tuple[int, ...]) -> dict:
    """Rank clues and return inspectable human-solving metrics.

    `rules` is intentionally passed in by the caller so authored and generated
    clues can be analysed together while their provenance remains separate.
    """
    from .logic_grid import holds, worlds

    current = list(worlds(model["size"], len(model["groups"])))
    remaining = list(rules)
    ordered: list[dict] = []
    trace: list[dict] = []
    fixed_before = _fixed(model, current)
    total_gain = 0.0
    while remaining:
        proposals = []
        for index, rule in enumerate(remaining):
            reduced = [row for row in current if holds(rule, row)]
            eliminated = len(current) - len(reduced)
            fixed_after = _fixed(model, reduced)
            newly_fixed = len(fixed_after - fixed_before)
            # Relational clues usually read as deductions more naturally than
            # direct answers, so use them as a stable tie-breaker.
            direct = rule["kind"] in ("at", "not-at")
            proposals.append((eliminated, newly_fixed, not direct, -index, index, rule, reduced))
        eliminated, newly_fixed, _, _, chosen_index, chosen, reduced = max(
            proposals, key=lambda item: item[:4]
        )
        before = len(current)
        after = len(reduced)
        gain = math.log2(before / after) if after else float("inf")
        total_gain += gain if math.isfinite(gain) else 0.0
        global_index = next(index for index, rule in enumerate(rules) if rule is chosen)
        ordered.append(chosen)
        trace.append({
            "clue": global_index + 1,
            "text": chosen["text"],
            "before": before,
            "after": after,
            "eliminated": eliminated,
            "newly_fixed": newly_fixed,
            "information_gain": round(gain, 4) if math.isfinite(gain) else None,
            "useful": eliminated > 0,
        })
        current = reduced
        fixed_before = _fixed(model, current)
        remaining.pop(chosen_index)

    useful = [step for step in trace if step["useful"]]
    redundant = [step for step in trace if not step["useful"]]
    forced = [
        _label(model, index, position)
        for index, position in sorted(_fixed(model, [solution]))
    ]
    direct_count = sum(rule["kind"] in ("at", "not-at") for rule in rules)
    relational_count = len(rules) - direct_count
    clue_count = len(rules)
    first_gain = useful[0]["information_gain"] if useful else 0.0
    world_count = len(worlds(model["size"], len(model["groups"])))
    score_raw = (
        35.0 * min(1.0, len(useful) / max(1, clue_count))
        + 25.0 * min(1.0, total_gain / max(1.0, math.log2(max(2, world_count))))
        + 20.0 * min(1.0, relational_count / max(1, clue_count))
        + 20.0 * min(1.0, len(forced) / max(1, len(model["names"])))
        - 12.0 * min(1.0, len(redundant) / max(1, clue_count))
    )
    score = round(max(0.0, min(100.0, score_raw)), 1)
    if score >= 75:
        level = "strong"
    elif score >= 50:
        level = "developing"
    else:
        level = "weak"
    warnings = []
    if redundant:
        warnings.append(
            f"{len(redundant)} clue(s) do not reduce the live possibilities in the best solve order"
        )
    if direct_count == clue_count and clue_count:
        warnings.append(
            "Every clue states a position directly; add a relational clue for deeper reasoning"
        )
    if not useful:
        warnings.append("No clue narrows the candidate arrangements")
    hints = []
    for step in useful[:3]:
        if step["before"] == len(worlds(model["size"], len(model["groups"]))):
            hints.append(f"Start with this clue: {step['text']}.")
        else:
            hints.append(
                f"Try clue {step['clue']}: it cuts the live possibilities from "
                f"{step['before']} to {step['after']}."
            )
    if not hints:
        hints.append("List the possible positions for each value, then apply every clue.")
    return {
        "score": score,
        "level": level,
        "fair": not redundant and bool(useful),
        "candidate_count": world_count,
        "reasoning_steps": len(useful),
        "useful_clues": len(useful),
        "redundant_clues": len(redundant),
        "direct_clues": direct_count,
        "relational_clues": relational_count,
        "information_gain": round(total_gain, 4),
        "first_clue_gain": first_gain,
        "forced_facts": forced,
        "hints": hints,
        "trace": trace,
        "ordered_clues": [rule["text"] for rule in ordered],
        "warnings": warnings,
    }
