"""Small fixed-seed synthesis comparison and an exhaustive three-clue oracle.

Run with the repository virtual environment. The comparison uses the same
requests/seeds and reports work and time separately: equal seeds are NOT an
equal-compute claim. It does not collect player data or rate human difficulty.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from contextlib import contextmanager
from itertools import combinations
from time import perf_counter
from unittest.mock import patch

from spie.forge.corpus import digest
from spie.questions.brainbloom import grid_quality, logic_grid
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.workshop import candidate

PERSON3 = "Person: Ada, Bo, Cy"
COLOUR3 = "Colour: Red, Blue, Green"
CASES = {
    "three-by-two": (PERSON3 + "\n" + COLOUR3, ""),
    "three-by-two-authored": (PERSON3 + "\n" + COLOUR3, "Bo is before Ada."),
    "three-by-three": (PERSON3 + "\n" + COLOUR3 + "\nDrink: Tea, Milk, Juice", ""),
    "four-by-two": (
        "Person: Ada, Bo, Cy, Dee\nColour: Red, Blue, Green, Pink", ""
    ),
    "three-by-two-query-choice": (PERSON3 + "\n" + COLOUR3,
                                   "Ada is before Bo.\nBo is before Cy."),
}


def spec_for(case):
    groups, rules = CASES[case]
    free_query = case == "three-by-two-query-choice"
    return {"groups": groups, "rules": rules, "complete": True,
            "target": "" if free_query else "Ada",
            "answer_group": "" if free_query else "Colour"}


def answer_for(model, world, query):
    target, group = query["target"], query["answer_group"]
    if group == -1:
        return str(world[target])
    return next(model["names"][i] for i in model["groups"][group]["indices"]
                if world[i] == world[target])


def exact_support(model, rules, solution, query, claim=None, claim_holds=True):
    """Independent exhaustive cardinality oracle for the displayed claim."""
    rows = logic_grid.worlds(model["size"], len(model["groups"]))
    expected = answer_for(model, solution, query) if claim is None else claim
    wrong = [w for w in rows if (answer_for(model, w, query) == expected) != claim_holds]
    masks = [sum(1 << i for i, w in enumerate(wrong) if not logic_grid.holds(rule, w))
             for rule in rules]
    all_wrong = (1 << len(wrong)) - 1
    checked = 0
    for size in range(len(rules) + 1):
        for subset in combinations(range(len(rules)), size):
            checked += 1
            if checked > 100_000:
                raise RuntimeError("Benchmark support oracle exceeded 100000 subsets")
            covered = 0
            for i in subset:
                covered |= masks[i]
            if covered == all_wrong:
                return size
    raise AssertionError("No subset establishes the displayed answer")


@contextmanager
def count_generation_work():
    """Diagnostic counters, not a complete account of bitset/SMT work."""
    counts = {"holds_calls": 0, "complete_grid_checks": 0}
    original_holds, original_check = logic_grid.holds, logic_grid.check

    def holds(*args, **kwargs):
        counts["holds_calls"] += 1
        return original_holds(*args, **kwargs)

    def check(*args, **kwargs):
        counts["complete_grid_checks"] += 1
        return original_check(*args, **kwargs)

    with patch.object(logic_grid, "holds", holds), patch.object(logic_grid, "check", check):
        yield counts


def validate_result(request, item, proof):
    """All benchmark validation stays outside its measured generation segments."""
    spec = request.grid
    assert candidate(request, request.seed) == (item, proof), "Non-deterministic replay"
    model, solution = proof["model"], tuple(proof["solution_positions"])
    assert proof["authored_rules"] == logic_grid.parse(spec)["rules"], "Authored rules changed"
    if model["target"] is not None:
        assert proof["query"]["target"] == model["target"], "Requested target changed"
    if model["answer_group"] is not None:
        assert proof["query"]["answer_group"] == model["answer_group"], "Requested group changed"
    rules = [*proof["authored_rules"], *proof["added_rules"]]
    assert logic_grid.check(model, rules) == [solution], "Solver disagreement or ambiguity"
    answer = answer_for(model, solution, proof["query"])
    if request.qtype == "true-false":
        assert proof["claim_holds"] == (proof["claim"] == answer)
        answer = str(proof["claim_holds"])
    assert item["correctAnswer"] == answer, "Displayed answer disagrees with solution"
    support = exact_support(model, rules, solution, proof["query"],
                            proof.get("claim"), proof.get("claim_holds", True))
    if request.min_supporting_clues != "auto":
        assert support >= request.min_supporting_clues, "Requested minimum support was relaxed"
    if "reasoning_constraints" in proof:
        assert proof["reasoning_constraints"]["minimum_supporting_clues"] == support
    domains, _, conflict = grid_quality.propagate(model, rules)
    pool = logic_grid._suggestions(model, solution, random.Random(0))
    planted_problem = digest([model["groups"], proof["authored_rules"], solution,
                              proof["query"], sorted(pool, key=lambda r: json.dumps(r))])
    return {"synthesis": proof.get("synthesis"),
            "constraint_search": proof.get("constraint_search"),
            "planted_problem": planted_problem, "structure": proof["structural_key"],
            "support": support, "total_clues": len(rules), "added_clues": len(proof["added_rules"]),
            "deduction_only": conflict is None and all(len(d) == 1 for d in domains)}


def measure(case, seed, revision, kind, minimum):
    request = Request("logic-grid", kind, "medium", grid=spec_for(case), seed=seed,
                      engine_revision=revision, min_supporting_clues=minimum)
    result = {"case": case, "seed": seed, "revision": revision, "format": kind}
    start = perf_counter()
    with count_generation_work() as work:
        try:
            item, proof = candidate(request, seed)
        except ValueError as exc:
            return {**result, "status": "rejected", "reason": str(exc),
                    "seconds": round(perf_counter() - start, 6), "observed_work": work}
    elapsed = perf_counter() - start
    return {**result, "status": "verified", "seconds": round(elapsed, 6),
            "observed_work": work, **validate_result(request, item, proof)}


def timed_comparison(args, revisions):
    """Practical equal-time allowances; one in-flight request may overrun."""
    if args.seconds_per_case is None:
        return None
    runs = []
    trials = [(case, seed, kind) for case in args.cases for seed in args.seeds
              for kind in args.formats]
    for trial, (case, start_seed, kind) in enumerate(trials):
        order = revisions if trial % 2 == 0 else list(reversed(revisions))
        # Both revisions get the same untimed warm-up; runtime differences then
        # exclude one-off imports and shared world-enumeration cache startup.
        for revision in order:
            warmup = Request("logic-grid", kind, "medium", grid=spec_for(case),
                             seed=start_seed, engine_revision=revision,
                             min_supporting_clues=args.minimum_support)
            try:
                candidate(warmup, start_seed)
            except ValueError:
                pass
        for revision in order:
            finished, rejected, attempts, overrun = [], 0, 0, None
            start = perf_counter()
            deadline = start + args.seconds_per_case
            while attempts < 64 and perf_counter() < deadline:
                seed = start_seed + attempts
                if seed >= 2**32:
                    break
                request = Request("logic-grid", kind, "medium", grid=spec_for(case),
                                  seed=seed, engine_revision=revision,
                                  min_supporting_clues=args.minimum_support)
                attempts += 1
                try:
                    generated = candidate(request, seed)
                except ValueError:
                    generated = None
                ended = perf_counter()
                if ended > deadline:
                    overrun = {"seconds": round(ended - deadline, 6),
                               "status": "generated" if generated else "rejected"}
                    break
                if generated is None:
                    rejected += 1
                else:
                    finished.append((request, *generated))
            elapsed = perf_counter() - start
            # Keep exact support calculation, independent checks, replay, and
            # best-result selection OUTSIDE the shared wall-clock allowance.
            checked = [{"seed": request.seed, **validate_result(request, item, proof)}
                       for request, item, proof in finished]
            best = max(checked, key=lambda r: (r["support"], -r["total_clues"]), default=None)
            runs.append({"case": case, "starting_seed": start_seed, "format": kind,
                         "revision": revision, "allowance_seconds": args.seconds_per_case,
                         "elapsed_seconds": round(elapsed, 6), "attempts_started": attempts,
                         "verified_before_deadline": len(checked),
                         "rejected_before_deadline": rejected,
                         "unique_structures": len({r["structure"] for r in checked}),
                         "attempt_cap_reached": attempts == 64, "overrun": overrun,
                         "best": ({k: best[k] for k in ("seed", "support", "total_clues",
                                                      "deduction_only")} if best else None)})
    return {"scope": "Same wall-clock allowance per case/starting seed, after warm-up. "
                     "Only generation completions before the deadline count. One in-flight "
                     "attempt can overrun and is excluded. At most 64 attempts per run. "
                     "Revisions alternate order; validation and selection are untimed. "
                     "Observed machine throughput, not normalized compute or deterministic timing.",
            "runs": runs}


def three_clue_oracle():
    """Enumerate the existing seed-6 relational pool; no new clue vocabulary."""
    _, proof = candidate(Request("logic-grid", grid=spec_for("three-by-two"),
                                 engine_revision=5), 6)
    model, solution = proof["model"], tuple(proof["solution_positions"])
    pool = [r for r in logic_grid._suggestions(model, solution, random.Random(0))
            if r["kind"] != "at"]
    rows = logic_grid.worlds(3, 2)
    masks = [sum(1 << i for i, w in enumerate(rows) if logic_grid.holds(r, w)) for r in pool]
    unique, checked, best = 0, 0, None
    for indices in combinations(range(len(pool)), 3):
        checked += 1
        remaining = (1 << len(rows)) - 1
        for i in indices:
            remaining &= masks[i]
        if remaining.bit_count() != 1:
            continue
        unique += 1
        clues = [pool[i] for i in indices]
        support = exact_support(model, clues, solution, proof["query"])
        if best is None or support > best[0]:
            best = support, clues
    assert best is not None and logic_grid.check(model, best[1]) == [solution]
    return {"scope": "all exactly-three-clue subsets of the seed-6 relational suggestion pool",
            "subsets_checked": checked, "unique_subsets": unique,
            "baseline_clues": [r["text"] for r in proof["added_rules"]],
            "baseline_support": exact_support(model, proof["added_rules"], solution,
                                              proof["query"]),
            "best_three_clue_support": best[0], "best_three_clues": [r["text"] for r in best[1]],
            "solution": logic_grid.table(model, solution)}


def run(args):
    revisions = [args.baseline_revision]
    if args.candidate_revision is not None:
        revisions.append(args.candidate_revision)
    results = [measure(case, seed, rev, kind, args.minimum_support)
               for case in args.cases for seed in args.seeds
               for kind in args.formats for rev in revisions]
    summary, by_revision = [], defaultdict(list)
    for row in results:
        by_revision[row["revision"]].append(row)
    for revision, rows in by_revision.items():
        valid = [r for r in rows if r["status"] == "verified"]
        times = sorted(r["seconds"] for r in rows)
        mean_support = statistics.mean(r["support"] for r in valid) if valid else None
        mean_clues = statistics.mean(r["total_clues"] for r in valid) if valid else None
        summary.append({"revision": revision, "requested": len(rows), "verified": len(valid),
                        "rejected": len(rows) - len(valid),
                        "mean_support": mean_support, "mean_clues": mean_clues,
                        "support_at_least_three": sum(r["support"] >= 3 for r in valid),
                        "deduction_only": sum(r["deduction_only"] for r in valid),
                        "unique_structures": len({r["structure"] for r in valid}),
                        "median_seconds": statistics.median(times),
                        "p95_seconds": times[math.ceil(0.95 * len(times)) - 1]})
    comparison = None
    if args.candidate_revision is not None:
        baseline = by_revision[args.baseline_revision]
        improved = by_revision[args.candidate_revision]
        pairs = [(a, b) for a, b in zip(baseline, improved, strict=True)
                 if a["status"] == b["status"] == "verified"]
        comparison = {
            "both_verified": len(pairs),
            "identical_planted_problem": sum(a["planted_problem"] == b["planted_problem"]
                                             for a, b in pairs),
            "support_improved": sum(b["support"] > a["support"] for a, b in pairs),
            "support_regressed": sum(b["support"] < a["support"] for a, b in pairs),
            "fewer_clues_with_no_support_loss": sum(
                b["total_clues"] < a["total_clues"] and b["support"] >= a["support"]
                for a, b in pairs),
        }
    return {"benchmark": "brainbloom-clue-synthesis-fixed-seeds-v1",
            "scope": "Equal fixed request/seed opportunities, not equal compute. "
                     "Work counters are diagnostic; "
                     "inspect synthesis budgets and actual work before claiming efficiency gains. "
                     "Support is exact for the displayed claim. Runtime includes instrumentation, "
                     "excludes replay/validation.",
            "seeds": args.seeds, "minimum_support": args.minimum_support,
            "summary": summary, "comparison": comparison,
            "oracle": three_clue_oracle() if args.oracle else None, "results": results,
            "timed_comparison": timed_comparison(args, revisions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-revision", type=int, default=5)
    parser.add_argument("--candidate-revision", type=int)
    parser.add_argument("--seeds", default="0,6,11")
    parser.add_argument("--formats", default="multiple-choice")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--minimum-support", choices=("auto", "2", "3", "4"), default="auto")
    parser.add_argument("--seconds-per-case", type=float)
    parser.add_argument("--oracle", action="store_true")
    args = parser.parse_args()
    if args.candidate_revision == args.baseline_revision:
        parser.error("Baseline and candidate revisions must differ")
    args.seeds = [int(seed) for seed in args.seeds.split(",")]
    if not 1 <= len(args.seeds) <= 20 or any(not 0 <= seed < 2**32 for seed in args.seeds):
        parser.error("Supply 1–20 seeds between 0 and 4294967295")
    args.cases = args.cases.split(",")
    if not args.cases or any(case not in CASES for case in args.cases):
        parser.error("Unknown benchmark case; choose " + ", ".join(CASES))
    if args.seconds_per_case is not None and not 0.05 <= args.seconds_per_case <= 1:
        parser.error("Use a time allowance from 0.05 to 1 second per case")
    args.formats = args.formats.split(",")
    if not args.formats or any(k not in ("multiple-choice", "true-false", "type-answer", "riddle")
                               for k in args.formats):
        parser.error("Choose supported quiz formats separated by commas")
    if args.minimum_support != "auto":
        args.minimum_support = int(args.minimum_support)
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
