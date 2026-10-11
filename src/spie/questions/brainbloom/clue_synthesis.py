"""Bounded, target-aware clue repair over a fixed, planted grid solution.

A rival arrangement tells search which clues can separate it from the solution.
A short answer proof forbids retaining that entire shortcut in the next design.
Search uses bitsets; the caller independently checks its selected grid and claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

MAX_TARGETS = 8
MAX_CANDIDATES = 48
MAX_SEARCH_NODES = 2_000
MAX_SUPPORT_SUBSETS = 100_000


class _BudgetExhausted(Exception):
    pass


@dataclass(frozen=True)
class _Design:
    score: tuple
    selected: int
    target: tuple
    wrong: int
    support: int | None
    core: int
    baseline_support: int | None


def _mask(rows, predicate):
    bits = bytearray((len(rows) + 7) // 8)
    for i, row in enumerate(rows):
        if predicate(row):
            bits[i // 8] |= 1 << (i % 8)
    return int.from_bytes(bits, "little")


def _targets(model, solution, queries, rng, qtype):
    queries = list(queries)
    first = rng.choice(queries)
    # Fix truth before searching, so optimizing support cannot bias every item true.
    truth = bool(rng.randrange(2)) if qtype == "true-false" else True

    def claims_for(target, group):
        if group == -1:
            correct = solution[target]
            return [correct] if truth else [p for p in range(1, model["size"] + 1)
                                            if p != correct]
        else:
            indices = model["groups"][group]["indices"]
            correct = next(i for i in indices if solution[i] == solution[target])
            return [correct] if truth else [i for i in indices if i != correct]

    # Always evaluate the legacy question/claim first. Bounded query exploration
    # can then improve it without accidentally omitting the existing baseline.
    first_claims = claims_for(*first)
    first_claim = first_claims[0] if truth else rng.choice(first_claims)
    first_claims.remove(first_claim)
    rng.shuffle(first_claims)
    queries.remove(first)
    rng.shuffle(queries)
    targets = []
    for target, group in [first, *queries]:
        if (target, group) == first:
            claims = [first_claim, *first_claims]
        else:
            claims = claims_for(target, group)
            rng.shuffle(claims)
        for claim in claims:
            targets.append((target, group, claim, truth))
    return targets[:MAX_TARGETS]


class _Search:
    def __init__(self, model, solution, pool, added):
        from .logic_grid import holds, worlds

        self.model, self.solution = model, solution
        self.rows = worlds(model["size"], len(model["groups"]))
        self.all_rows = (1 << len(self.rows)) - 1
        self.solution_bit = 1 << self.rows.index(tuple(solution))
        self.authored = model["rules"]
        self.mask_evaluations = 0

        def excluded(rule):
            self.mask_evaluations += len(self.rows)
            return _mask(self.rows, lambda row: not holds(rule, row))

        self.authored_masks = [excluded(rule) for rule in self.authored]
        self.pool, self.masks, seen = [], [], set(self.authored_masks)
        self.baseline = 0
        for rule in pool:
            mask = excluded(rule)
            if mask in seen or not mask:
                continue
            seen.add(mask)
            index = len(self.pool)
            self.pool.append(rule)
            self.masks.append(mask)
            if rule in added:
                self.baseline |= 1 << index
        # Equivalent suggestions may have different text; preserve the baseline's
        # semantics even when the pool keeps the other representative.
        for rule in added:
            mask = excluded(rule)
            if mask not in self.authored_masks:
                self.baseline |= 1 << self.masks.index(mask)
        self.initial = self.all_rows
        for mask in self.authored_masks:
            self.initial &= ~mask
        self.nodes = self.evaluations = self.subsets = self.shortcuts = 0

    def indices(self, selected):
        return [i for i in range(len(self.pool)) if selected & (1 << i)]

    def rules(self, selected):
        return [self.pool[i] for i in self.indices(selected)]

    def prune(self, selected):
        for i in self.indices(selected):
            other = selected & ~(1 << i)
            remaining = self.initial
            for j in self.indices(other):
                remaining &= ~self.masks[j]
            if remaining == self.solution_bit:
                selected = other
        return selected

    def wrong(self, target):
        a, group, claim, truth = target
        self.mask_evaluations += len(self.rows)
        return _mask(self.rows, lambda row: (
            row[a] == claim if group == -1 else row[a] == row[claim]) != truth)

    def support(self, selected, wrong):
        if self.evaluations >= MAX_CANDIDATES:
            raise _BudgetExhausted
        self.evaluations += 1
        masks, origins, seen = [], [], set()
        candidates = [(mask, 0) for mask in self.authored_masks]
        candidates.extend((self.masks[i], 1 << i) for i in self.indices(selected))
        for mask, origin in candidates:
            mask &= wrong
            if mask and mask not in seen:
                masks.append(mask)
                origins.append(origin)
                seen.add(mask)
        for size in range(len(masks) + 1):
            for subset in combinations(range(len(masks)), size):
                if self.subsets >= MAX_SUPPORT_SUBSETS:
                    raise _BudgetExhausted
                self.subsets += 1
                covered, automatic = 0, 0
                for i in subset:
                    covered |= masks[i]
                    automatic |= origins[i]
                if covered == wrong:
                    return size, automatic
        raise RuntimeError("Clue synthesis lost the planted answer")

    def propose(self, forbidden, maximum, node_limit):
        """Find a unique clue set, branching only on separators of a rival world.

        Earlier branches are excluded in later siblings so permutations of a
        clue set do not consume search repeatedly. All limits count logical
        work rather than elapsed time, preserving deterministic replay.
        """
        available = (1 << len(self.pool)) - 1

        def visit(selected, remaining, available, limit):
            if self.nodes >= node_limit:
                raise _BudgetExhausted
            self.nodes += 1
            if remaining == self.solution_bit:
                return selected
            if selected.bit_count() >= limit:
                return None
            rival = remaining & ~self.solution_bit
            witness = rival & -rival
            choices = []
            for i in self.indices(available):
                bit = 1 << i
                proposed = selected | bit
                if self.masks[i] & witness and not any(
                        proposed & core == core for core in forbidden):
                    reduced = remaining & ~self.masks[i]
                    choices.append((self.pool[i]["kind"] == "at", reduced.bit_count(), i,
                                    reduced))
            for _, _, i, reduced in sorted(choices):
                bit = 1 << i
                available &= ~bit
                result = visit(selected | bit, reduced, available, limit)
                if result is not None:
                    return result
            return None

        # Repair at the current clue bound first. Proving that a much smaller
        # set is impossible can consume the entire budget before any repair.
        result = visit(0, self.initial, available, maximum)
        return None if result is None else self.prune(result)


def synthesize(model, solution, pool, added, queries, rng, request):
    """Return added rules, query, optional displayed claim, and bounded telemetry."""
    from .grid_quality import propagate

    search = _Search(model, solution, pool, added)
    baseline = search.prune(search.baseline)
    targets = _targets(model, solution, queries, rng, request.qtype)
    requested = request.min_supporting_clues
    preferred = ({"easy": 2, "medium": 3, "hard": 4}[request.difficulty]
                 if requested == "auto" else requested)
    deduction_only = request.reasoning_mode == "deduction-only"

    def propagation_ok(selected):
        if not deduction_only:
            return True
        domains, _, conflict = propagate(model, [*model["rules"], *search.rules(selected)])
        return conflict is None and domains == [{p} for p in solution]

    def rank(selected, support, deduction):
        qualifies = deduction and (requested == "auto" or support >= requested)
        return (qualifies, support, -selected.bit_count(),
                len({rule["kind"] for rule in search.rules(selected)}))

    best, designs = None, []
    exhausted = False
    probes = 0
    baseline_deduction = propagation_ok(baseline)
    try:
        for target in targets:
            wrong = search.wrong(target)
            support, core = search.support(baseline, wrong)
            probes += 1
            entry = _Design(rank(baseline, support, baseline_deduction), baseline,
                            target, wrong, support, core, support)
            designs.append(entry)
            if best is None or entry.score > best.score:
                best = entry
    except _BudgetExhausted:
        exhausted = True
    # Even if the proposal budget is exhausted, final independent certification
    # must still succeed. Do not fabricate a measured minimum for an untested query.
    if best is None:
        target = targets[0]
        best = _Design((False, -1, -baseline.bit_count(), 0), baseline, target, 0, None, 0, None)

    # A strong baseline query can be unrepairable because its entire short proof
    # is authored. Give the other eligible questions a share of the same budget.
    designs = sorted((d for d in designs if d.core or d.support >= preferred),
                     key=lambda d: d.score, reverse=True)
    repairs = repaired_targets = 0
    for offset, design in enumerate(designs):
        if search.initial == search.solution_bit:
            break
        if (search.subsets >= MAX_SUPPORT_SUBSETS or search.evaluations >= MAX_CANDIDATES
                or search.nodes >= MAX_SEARCH_NODES):
            exhausted = True
            break
        targets_left = len(designs) - offset
        node_limit = search.nodes + max(1, (MAX_SEARCH_NODES - search.nodes) // targets_left)
        candidate_limit = search.evaluations + max(
            1, (MAX_CANDIDATES - search.evaluations) // targets_left)
        selected, support, core = design.selected, design.support, design.core
        goal = max(preferred, support)
        # A requested minimum may need more clues than the greedy baseline.
        # Automatic preferences alone do not enlarge the original clue bound.
        maximum = max(baseline.bit_count(),
                      0 if requested == "auto" else requested - len(model["rules"]))
        forbidden = []
        started = False
        try:
            while True:
                if support < goal:
                    # Mandatory clues alone already prove this answer too easily.
                    if not core:
                        break
                    forbidden.append(core)
                    search.shortcuts += 1
                elif not propagation_ok(selected):
                    forbidden.append(selected)
                else:
                    # Keep established support while trying a smaller clue set.
                    maximum = selected.bit_count() - 1
                if maximum < max(0, goal - len(model["rules"])):
                    break
                if search.evaluations >= candidate_limit:
                    raise _BudgetExhausted
                if not started:
                    repaired_targets += 1
                    started = True
                proposed = search.propose(forbidden, maximum, node_limit)
                if proposed is None:
                    break
                repairs += 1
                support, core = search.support(proposed, design.wrong)
                selected = proposed
                score = rank(selected, support, propagation_ok(selected))
                if score > best.score:
                    best = _Design(score, selected, design.target, design.wrong,
                                   support, core, design.baseline_support)
        except _BudgetExhausted:
            exhausted = True

    selected, target, support = best.selected, best.target, best.support
    goal = max(preferred, best.baseline_support or 0)
    a, group, claim, truth = target
    claim_info = ({"claim": str(claim) if group == -1 else model["names"][claim],
                   "claim_holds": truth} if request.qtype == "true-false" else {})
    report = {
        "version": "target-clue-synthesis-v1", "scope": "best evaluated design; no global optimum",
        "target_budget": MAX_TARGETS, "targets_evaluated": probes,
        "candidate_budget": MAX_CANDIDATES, "candidate_evaluations": search.evaluations,
        "node_budget": MAX_SEARCH_NODES, "search_nodes": search.nodes,
        "support_subset_budget": MAX_SUPPORT_SUBSETS, "support_subsets_checked": search.subsets,
        "mask_evaluations": search.mask_evaluations, "repairs": repairs,
        "targets_repaired": repaired_targets,
        "shortcuts_excluded": search.shortcuts, "budget_exhausted": exhausted,
        "baseline_support": best.baseline_support, "selected_support": support,
        "baseline_added_clues": baseline.bit_count(), "selected_added_clues": selected.bit_count(),
        "preferred_support": goal, "preferred_support_met": support is not None and support >= goal,
    }
    return search.rules(selected), (a, group), claim_info, report
