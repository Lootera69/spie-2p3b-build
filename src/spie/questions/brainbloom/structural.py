"""Grid equivalence under relabeling, group permutation and left/right reflection."""

from __future__ import annotations

from itertools import permutations

from ...forge.corpus import compact, digest


def grid_key(model: dict, rules: list[dict], solution, target: int, answer_group: int) -> str:
    """Include question and clues, excluding names and input ordering of values."""
    count, size = len(model["groups"]), model["size"]
    owners = model["owners"]
    encodings = []
    for order in permutations(range(count)):
        for reflected in (False, True):
            def position(p, reflected=reflected):
                return size + 1 - p if reflected else p

            def label(i, order=order, position=position):
                return (order[owners[i]], position(solution[i]))

            encoded = []
            for rule in rules:
                kind = rule["kind"]
                a = label(rule["a"])
                b = label(rule["b"]) if "b" in rule else None
                if kind == "after":
                    kind, a, b = "before", b, a
                if kind == "distance" and rule["n"] == 1:
                    kind = "next"
                if kind in ("before", "immediate") and reflected:
                    a, b = b, a
                if kind in ("next", "not-next", "paired", "not-paired", "distance"):
                    a, b = sorted((a, b))
                row = [kind, a]
                if kind == "between":
                    row.extend(sorted((b, label(rule["c"]))))
                elif b is not None:
                    row.append(b)
                if "n" in rule and kind != "next":
                    row.append(position(rule["n"]) if kind in ("at", "not-at") else rule["n"])
                encoded.append(row)
            query = [label(target), -1 if answer_group == -1 else order[answer_group]]
            encodings.append(compact([size, count, sorted(encoded, key=compact), query]))
    return digest(["grid-structure-v2", min(encodings)])
