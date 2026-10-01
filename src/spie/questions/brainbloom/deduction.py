"""Invent finite constraint puzzles, then check them using a separate SMT encoding."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import combinations, permutations

import z3

from ...forge.corpus import digest
from .. import prover


@dataclass(frozen=True)
class Clue:
    kind: str
    a: int
    b: int
    k: int = 0


def holds(clue: Clue, positions: tuple[int, ...]) -> bool:
    a, b = positions[clue.a], positions[clue.b]
    if clue.kind == "before":
        return a < b
    if clue.kind == "adjacent":
        return abs(a - b) == 1
    if clue.kind == "distance":
        return abs(a - b) == clue.k
    if clue.kind == "not-at":
        return a != clue.k
    if clue.kind == "between":
        c = positions[clue.k]
        return b < a < c or c < a < b
    raise ValueError("Unknown clue kind")


@lru_cache(maxsize=3)
def worlds(size: int) -> tuple[tuple[int, ...], ...]:
    if not 4 <= size <= 6:
        raise ValueError("Deduction puzzles require 4-6 cards")
    return tuple(permutations(range(size)))


def mask_for(clue: Clue, rows: tuple[tuple[int, ...], ...]) -> int:
    return sum(1 << i for i, row in enumerate(rows) if holds(clue, row))


def survivors(rows, clues) -> list[tuple[int, ...]]:
    return [row for row in rows if all(holds(clue, row) for clue in clues)]


def text(clue: Clue, names: list[str], *, concise: bool = False) -> str:
    a, b = names[clue.a], names[clue.b]
    if concise:
        if clue.kind == "before":
            return f"{a} is left of {b}."
        if clue.kind == "adjacent":
            return f"{a} is next to {b}."
        if clue.kind == "distance":
            return f"{a} and {b} differ by {clue.k} positions."
        if clue.kind == "not-at":
            return f"{a} is not at position {clue.k + 1}."
        return f"{a} lies between {b} and {names[clue.k]}; gaps allowed."
    if clue.kind == "before":
        return f"{a} is somewhere to the left of {b}."
    if clue.kind == "adjacent":
        return f"{a} and {b} are next to each other."
    if clue.kind == "distance":
        return f"The positions of {a} and {b} differ by exactly {clue.k}."
    if clue.kind == "not-at":
        return f"{a} is not in position {clue.k + 1}."
    return f"{a} is somewhere between {b} and {names[clue.k]}, not necessarily adjacent."


def _pool(solution: tuple[int, ...], level: int) -> list[Clue]:
    n = len(solution)
    pool = []
    for a in range(n):
        for k in range(n):
            if solution[a] != k:
                pool.append(Clue("not-at", a, a, k))
        for b in range(n):
            if solution[a] < solution[b]:
                pool.append(Clue("before", a, b))
            if a < b:
                distance = abs(solution[a] - solution[b])
                if distance == 1:
                    pool.append(Clue("adjacent", a, b))
                elif level >= 2 and distance < n - 1:
                    pool.append(Clue("distance", a, b, distance))
        if level == 3:
            for b, c in combinations([i for i in range(n) if i != a], 2):
                clue = Clue("between", a, b, c)
                if holds(clue, solution):
                    pool.append(clue)
    return pool


def _intersect(masks: list[int], universe: int) -> int:
    for mask in masks:
        universe &= mask
    return universe


def minimum_support(rows, clues: list[Clue], answer: int, position: int) -> tuple[int, list[int]]:
    """Exact smallest clue subset establishing the answer, not an estimated depth."""
    universe = (1 << len(rows)) - 1
    target = sum(1 << i for i, row in enumerate(rows) if row[answer] == position)
    masks = [mask_for(c, rows) for c in clues]
    for size in range(len(clues) + 1):
        for indices in combinations(range(len(clues)), size):
            remaining = _intersect([masks[i] for i in indices], universe)
            if remaining and not remaining & ~target:
                return size, list(indices)
    raise ValueError("No clue subset determines the answer")


def propose(names: list[str], level: int, rng) -> dict | None:
    n = len(names)
    rows = worlds(n)
    solution = rng.choice(rows)
    pool = _pool(solution, level)
    rng.shuffle(pool)
    masks = {c: mask_for(c, rows) for c in pool}
    remaining = (1 << len(rows)) - 1
    clues = []
    while remaining.bit_count() > 1 and len(clues) < 10:
        useful = [c for c in pool if 0 < (remaining & masks[c]).bit_count()
                  < remaining.bit_count()]
        if not useful:
            return None
        # Search different information-reducing paths, rather than always emitting
        # the same most-restrictive clue. All choices preserve the planted world.
        useful.sort(key=lambda c: (remaining & masks[c]).bit_count())
        clue = rng.choice(useful[:min(5, len(useful))])
        clues.append(clue)
        remaining &= masks[clue]
    if remaining.bit_count() != 1:
        return None
    # Remove every clue not needed for a unique full arrangement.
    for clue in list(clues):
        rest = [c for c in clues if c != clue]
        if _intersect([masks[c] for c in rest], (1 << len(rows)) - 1).bit_count() == 1:
            clues.remove(clue)
    if len(clues) > 8 or len({c.kind for c in clues}) < 2:
        return None
    rng.shuffle(clues)
    targets = []
    for answer in range(n):
        support, indices = minimum_support(rows, clues, answer, solution[answer])
        if level + 1 <= support <= level + 2:
            targets.append((support, answer, indices))
    if not targets:
        return None
    support, answer, indices = max(targets, key=lambda entry: entry[0])
    diversity = len({c.kind for c in clues})
    score = 20 * support + 5 * diversity - len(clues)
    return {
        "names": names, "clues": [asdict(c) for c in clues], "solution": list(solution),
        "answer_index": answer, "position": solution[answer],
        "minimum_support": support, "support_indices": indices, "score": score,
        "quality": {"minimum_supporting_clues": support, "clue_kinds": diversity,
                    "clue_count": len(clues), "possible_worlds": len(rows),
                    "all_clues_necessary_for_full_solution": True},
    }


def check(model: dict) -> dict:
    names = model["names"]
    n = len(names)
    clues = [Clue(**c) for c in model["clues"]]
    rows = worlds(n)
    surviving = survivors(rows, clues)
    if len(surviving) != 1 or list(surviving[0]) != model["solution"]:
        raise RuntimeError("Deduction model is not uniquely solved")
    positions = [z3.Int(f"card_{i}") for i in range(n)]
    encoded = [z3.Distinct(*positions), *[z3.And(p >= 0, p < n) for p in positions]]
    for clue in clues:
        a, b = positions[clue.a], positions[clue.b]
        if clue.kind == "before":
            expression = a < b
        elif clue.kind == "adjacent":
            expression = z3.Or(a == b + 1, b == a + 1)
        elif clue.kind == "distance":
            expression = z3.Or(a - b == clue.k, b - a == clue.k)
        elif clue.kind == "not-at":
            expression = a != clue.k
        else:
            c = positions[clue.k]
            expression = z3.Or(z3.And(b < a, a < c), z3.And(c < a, a < b))
        encoded.append(expression)
    formula = z3.And(*encoded)
    sat, _ = prover.satisfiable(formula)
    unique, _ = prover.decide(z3.Implies(
        formula, z3.And(*[p == v for p, v in zip(positions, surviving[0], strict=True)])
    ))
    if not sat or not unique:
        raise RuntimeError("Z3/exhaustive deduction disagreement")
    minimum, indices = minimum_support(rows, clues, model["answer_index"], model["position"])
    deletion_counts = [len(survivors(rows, clues[:i] + clues[i + 1:]))
                       for i in range(len(clues))]
    if minimum != model["minimum_support"] or any(c < 2 for c in deletion_counts):
        raise RuntimeError("Deduction difficulty or irredundancy check failed")
    trace, steps, current = [], [], list(rows)
    for index, clue in enumerate(clues):
        current = [row for row in current if holds(clue, row)]
        domains = {name: sorted({row[i] + 1 for row in current})
                   for i, name in enumerate(names)}
        trace.append({"clue": index + 1, "remaining": len(current), "positions": domains})
        fixed = "; ".join(f"{name} must be at {values[0]}"
                          for name, values in domains.items() if len(values) == 1)
        steps.append(f"After clue {index + 1}: {len(current)} arrangements remain. " + fixed)
    ordered = sorted(range(n), key=lambda i: surviving[0][i])
    steps.append("The only complete order is " + ", ".join(names[i] for i in ordered) + ".")
    steps.append(f"At least {minimum} of the displayed clues are needed to force the answer; "
                 f"one smallest set is {', '.join(str(i + 1) for i in indices)}.")
    # Rename each entity by its solved position: mere word substitutions have the
    # same structural key and are rejected within a batch.
    shape = sorted((c.kind, surviving[0][c.a], surviving[0][c.b],
                    surviving[0][c.k] if c.kind == "between" else c.k) for c in clues)
    return {
        "method": "z3-and-exhaustive-constraint-search", "z3_version": prover.z3_version(),
        "model_count": 1, "agree": True, "minimum_supporting_clues": minimum,
        "clue_deletion_model_counts": deletion_counts, "trace": trace, "steps": steps,
        "structural_key": digest(["deduction", n, shape, model["position"]]),
        "scope": "the stated fictional card arrangement; no real-world relations are inferred",
    }
