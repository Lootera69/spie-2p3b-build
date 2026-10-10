"""Bounded certificates for creator-selected grid reasoning requirements."""

from __future__ import annotations

from itertools import combinations

MODES = {"auto": "Automatic", "deduction-only": "Deduction only (checked propagation)"}
MINIMUMS = ("auto", 2, 3, 4)
MAX_SUPPORT_SUBSETS = 100_000
SCOPE = ("Checked constraint propagation and exact minimum clue support; "
         "these controls do not measure human difficulty.")


class ConstraintRejected(ValueError):
    """A candidate failed a requested gate; generation may try another proposal."""


def validate(mode: object, minimum: object) -> None:
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Reasoning mode must be auto or deduction-only")
    if not (minimum == "auto" if isinstance(minimum, str) else
            type(minimum) is int and minimum in (2, 3, 4)):
        raise ValueError("Minimum supporting clues must be auto, 2, 3 or 4")


def active(request) -> bool:
    return request.reasoning_mode != "auto" or request.min_supporting_clues != "auto"


def settings(request) -> dict:
    return {"reasoning_mode": request.reasoning_mode,
            "min_supporting_clues": request.min_supporting_clues, "scope": SCOPE}


class SupportVerifier:
    """Exact cardinality search over wrong-answer worlds with a fixed work cap.

    Every rule is true in the certified solution, so its subsets are consistent.
    Excluding all wrong-answer worlds is therefore a sufficient, non-vacuous
    answer certificate. Search in increasing cardinality proves minimality.
    """

    def __init__(self, model: dict, rules: list[dict], solution):
        from .logic_grid import holds, worlds

        self.model = model
        self.solution = solution
        self.worlds = worlds(model["size"], len(model["groups"]))
        if not all(holds(rule, solution) for rule in rules):
            raise RuntimeError("Supporting-clue analysis requires a consistent solution")
        self.masks = [sum(1 << i for i, row in enumerate(self.worlds) if not holds(rule, row))
                      for rule in rules]
        self.subsets_checked = 0
        self.answers = {}

    def minimum(self, query: dict, *, claim: str | None = None,
                claim_holds: bool = True) -> list[int]:
        target, group = query["target"], query["answer_group"]
        key = target, group, claim, claim_holds
        if key in self.answers:
            return list(self.answers[key])
        if group == -1:
            position = self.solution[target] if claim is None else int(claim)

            def wrong(row):
                return (row[target] == position) != claim_holds
        else:
            partner = (next(i for i in self.model["groups"][group]["indices"]
                            if self.solution[i] == self.solution[target]) if claim is None
                       else self.model["names"].index(claim))

            def wrong(row):
                return (row[target] == row[partner]) != claim_holds

        required = sum(1 << i for i, row in enumerate(self.worlds) if wrong(row))
        # Repeated or irrelevant rules cannot improve the minimum cardinality.
        masks, indices, seen = [], [], set()
        for index, mask in enumerate(self.masks):
            mask &= required
            if mask and mask not in seen:
                masks.append(mask)
                indices.append(index + 1)
                seen.add(mask)
        for size in range(len(masks) + 1):
            for subset in combinations(range(len(masks)), size):
                self.subsets_checked += 1
                if self.subsets_checked > MAX_SUPPORT_SUBSETS:
                    raise ConstraintRejected(
                        "Exact minimum-support verification exceeded its bounded search budget"
                    )
                covered = 0
                for index in subset:
                    covered |= masks[index]
                if covered == required:
                    self.answers[key] = [indices[index] for index in subset]
                    return list(self.answers[key])
        raise RuntimeError("The verified grid does not force the displayed answer")


def certify(request, proof: dict, *, cache: dict | None = None) -> dict:
    """Check the actual displayed answer, including false true/false claims."""
    quality = proof["quality"]
    deduction_only = quality["propagation_complete"] and quality["case_checks"] == 0
    if request.reasoning_mode == "deduction-only" and not deduction_only:
        raise ConstraintRejected(
            "Deduction-only requires a complete checked propagation trace, "
            "without case assumptions or an exhaustive-solution fallback"
        )
    from ...forge.corpus import digest

    rules = [*proof["authored_rules"], *proof["added_rules"]]
    cache = {} if cache is None else cache
    key = digest([proof["model"], rules, proof["solution_positions"]])
    if key not in cache:
        cache[key] = SupportVerifier(proof["model"], rules, proof["solution_positions"])
    verifier = cache[key]
    support = verifier.minimum(proof["query"], claim=proof.get("claim"),
                               claim_holds=proof.get("claim_holds", True))
    minimum = request.min_supporting_clues
    if minimum != "auto" and len(support) < minimum:
        raise ConstraintRejected(
            f"The displayed answer needs only {len(support)} supporting clues; "
            f"at least {minimum} were requested"
        )
    return {"version": "reasoning-constraints-v1", "scope": SCOPE,
            "reasoning_mode": request.reasoning_mode,
            "minimum_supporting_clues_requested": minimum,
            "minimum_supporting_clues": len(support), "supporting_clues": support,
            "support_scope": "displayed true-false claim" if "claim" in proof else "grid question",
            "support_verification": "every smaller clue subset leaves a wrong-answer world",
            "support_subsets_checked": verifier.subsets_checked,
            "support_subset_budget": MAX_SUPPORT_SUBSETS,
            "deduction_only": deduction_only, "case_checks": quality["case_checks"],
            "exhaustive_fallback": not quality["propagation_complete"], "passed": True}
