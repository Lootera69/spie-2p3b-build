"""Compare guided state-plan repair with independent restarts at an equal model budget.

Strategy expectations come from raw rules and the separate forward-BFS oracle.
No search metadata is trusted as evidence that an accepted plan defeats a greedy choice.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import random
import sys
from collections import Counter
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from spie.questions.brainbloom import state_planning

if __package__:
    from . import benchmark_state_planning as state_audit
else:
    import benchmark_state_planning as state_audit

NAMES = state_audit.NAMES
audit_model = state_audit.audit_model
distribution = state_audit.distribution
initial = state_audit.initial
oracle = state_audit.oracle
topology_key = state_audit.topology_key

PHYSICAL_FIELDS = ("version", "names", "level", "capacity", "initial_energy",
                   "initial_gates", "charger", "routes", "switches")
STRATEGY = "invest-energy"


def physical_rules(model):
    """Strip claims and history before comparing independently observed models."""
    return {field: copy.deepcopy(model[field]) for field in PHYSICAL_FIELDS}


def rule_key(model):
    raw = json.dumps(physical_rules(model), sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def strategy_oracle(model, result=None):
    """Evaluate the specified strategy using raw initial action costs and exact BFS."""
    result = oracle(model) if result is None else result
    # The charger cannot be at the initial room in the declared physical family.
    spend = {f"move_{origin}_{destination}": cost
             for origin, destination, cost, _ in model["routes"] if origin == 0}
    spend.update({f"switch_{site}": cost for site, _, cost in model["switches"] if site == 0})
    legal = sorted(result["first_costs"])
    assert set(legal) <= set(spend)
    spend = {action: spend[action] for action in legal}
    cheapest = min(spend.values(), default=None)
    greedy = [action for action in legal if spend[action] == cheapest]
    winners = result["optimal_first_actions"]
    winner = winners[0] if len(winners) == 1 else None
    best = result["best_steps"]
    failures = []
    if winner is None or best is None:
        failures.append("no_unique_optimal_first_action")
    if not greedy:
        failures.append("no_legal_first_action")
    if winner is not None and spend[winner] <= cheapest:
        failures.append("winner_does_not_invest_more_energy")
    if any(result["committed_first_costs"][action] is None for action in greedy):
        failures.append("a_cheapest_action_has_no_committed_solution")
    if best is None or any(result["first_costs"][action] is None
                           or result["first_costs"][action] <= best for action in greedy):
        failures.append("a_cheapest_action_is_not_strictly_worse")
    gaps = [result["first_costs"][action] - best for action in greedy
            if best is not None and result["first_costs"][action] is not None]
    return {"strategy": STRATEGY, "qualifies": not failures, "failures": failures,
            "best_steps": best, "winner": winner, "legal_initial_energy_costs": spend,
            "minimum_initial_energy": cheapest, "minimum_energy_actions": greedy,
            "winner_initial_energy": spend.get(winner),
            "minimum_energy_total_steps": {action: result["first_costs"][action]
                                           for action in greedy},
            "minimum_energy_committed_steps": {action: result["committed_first_costs"][action]
                                               for action in greedy},
            "minimum_action_penalty": min(gaps, default=None)}


def existing_gates(model, reports):
    """Recheck the existing acceptance gates using independently computed reports."""
    base = reports["baseline"]
    best = base["best_steps"]
    signature = best, base["optimal_first_actions"]
    return (best is not None and (4, 5, 6)[model["level"] - 1] <= best <= 12
            and len(base["optimal_first_actions"]) == 1
            and sum(cost is not None for cost in base["committed_first_costs"].values()) >= 2
            and max(base["later_committed_choices"], default=0) >= 2
            and base["reachable_locations"] == len(model["names"])
            and all((reports[mechanic]["best_steps"], reports[mechanic]["optimal_first_actions"])
                    != signature for mechanic in ("energy", "gates", "switches", "recharge")))


@contextmanager
def observe_search():
    """Count actual graph work and retain evaluated rules without trusting telemetry."""
    graph_impl, sample_impl = state_planning._graph, state_planning._sample
    observations = {"graph_calls": Counter(), "sample_calls": 0, "sample_nulls": 0,
                    "sample_keys": [], "sample_sequence": [], "evaluated_keys": [], "models": {}}

    def sample(*args, **kwargs):
        model = sample_impl(*args, **kwargs)
        observations["sample_calls"] += 1
        if model is None:
            observations["sample_nulls"] += 1
            observations["sample_sequence"].append(None)
        else:
            key = rule_key(model)
            observations["sample_keys"].append(key)
            observations["sample_sequence"].append(key)
            observations["models"][key] = physical_rules(model)
        return model

    def graph(model, relaxed=None):
        observations["graph_calls"][relaxed or "baseline"] += 1
        if relaxed is None:
            key = rule_key(model)
            observations["evaluated_keys"].append(key)
            observations["models"][key] = physical_rules(model)
        return graph_impl(model, relaxed)

    with (patch.object(state_planning, "_sample", sample),
          patch.object(state_planning, "_graph", graph)):
        yield observations


def observed_work(observations):
    calls = observations["graph_calls"]
    return {"sample_calls": observations["sample_calls"],
            "sample_nulls": observations["sample_nulls"],
            "baseline_graph_calls": calls["baseline"],
            "ablation_graph_calls": sum(count for key, count in calls.items() if key != "baseline"),
            "total_graph_calls": sum(calls.values()),
            "graph_calls_by_mechanic": dict(calls),
            "distinct_evaluated_rules": len(set(observations["evaluated_keys"]))}


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    relatives = ("tools/benchmark_planning_invention.py", "tools/benchmark_state_planning.py",
                 "src/spie/questions/brainbloom/planning_invention.py",
                 "src/spie/questions/brainbloom/planning_strategy.py",
                 "src/spie/questions/brainbloom/state_planning.py", "src/spie/search.py",
                 "src/spie/interpreter.py", "src/spie/z3_compile.py")
    return {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
            for relative in relatives}


def audit_strategy_certificate(model, expected, certificate):
    """Check every strategy claim and every continuation in the independent raw graph."""
    base = oracle(model)
    assert expected["qualifies"]
    for field, wanted in {
        "strategy": STRATEGY,
        "optimal_first_action": expected["winner"],
        "best_steps": expected["best_steps"],
        "optimal_immediate_energy": expected["winner_initial_energy"],
        "cheapest_first_actions": expected["minimum_energy_actions"],
        "minimum_immediate_energy": expected["minimum_initial_energy"],
        "minimum_extra_steps": expected["minimum_action_penalty"],
        "reachable_states": base["reachable_states"],
    }.items():
        assert certificate[field] == wanted, (field, certificate[field], wanted)
    first = certificate["first_action_results"]
    assert set(first) == set(base["first_costs"])
    start, graph = initial(model), base["graph"]
    dominated = {state for state in graph if state[0] == start[0]
                 and state[2:4] == start[2:4] and state[1] <= start[1]
                 and state[4] >= start[4]}
    for action, row in first.items():
        assert row["immediate_energy"] == expected["legal_initial_energy_costs"][action]
        cost = base["first_costs"][action]
        assert row["extra_steps"] == (None if cost is None else cost - base["best_steps"])
        for kind, costs in (("unrestricted", base["first_costs"]),
                            ("committed", base["committed_first_costs"])):
            continuation = row[kind]
            assert continuation["best_steps"] == costs[action]
            if costs[action] is None:
                assert continuation["solution"] == continuation["solution_states"] == []
                continue
            actions, states = continuation["solution"], continuation["solution_states"]
            assert actions[0] == action and len(actions) == costs[action]
            assert len(states) == len(actions) + 1 and states[0] == list(start)
            current = start
            for number, move in enumerate(actions, 1):
                current = graph[current][move]
                assert states[number] == list(current)
                if kind == "committed":
                    assert current not in dominated
            assert current[0] == len(model["names"]) - 1


def audit_history(model, observations):
    """Replay edits and prove the accepted final edit rescued a rejected parent."""
    history = model["search"]["repair_history"]
    if not history:
        assert model["search"]["accepted_via"] == "restart"
        assert rule_key(model) in observations["sample_keys"]
        return []
    assert model["search"]["accepted_via"] == "repair"
    assert history[0]["parent"] in observations["sample_keys"]
    audited = []
    for index, event in enumerate(history):
        parent = observations["models"][event["parent"]]
        child = observations["models"][event["child"]]
        assert event["parent_model"] == parent and event["child_model"] == child
        assert rule_key(parent) == event["parent"] and rule_key(child) == event["child"]
        assert event["parent"] != event["child"]
        if index:
            assert history[index - 1]["child"] == event["parent"]
        edit, changed = event["edit"], physical_rules(parent)
        slot = changed
        for part in edit["path"][:-1]:
            slot = slot[part]
        assert slot[edit["path"][-1]] == edit["before"]
        slot[edit["path"][-1]] = edit["after"]
        assert changed == child
        reports = {mechanic or "baseline": oracle(parent, mechanic)
                   for mechanic in (None, "energy", "gates", "switches", "recharge")}
        parent_strategy = strategy_oracle(parent, reports["baseline"])
        parent_existing = existing_gates(parent, reports)
        assert not (parent_existing and parent_strategy["qualifies"])
        audited.append({**copy.deepcopy(event), "parent_model": parent, "child_model": child,
                        "parent_passes_existing_gates": parent_existing,
                        "parent_strategy": parent_strategy,
                        "edit_replayed": True, "parent_rejected_independently": True})
    assert history[-1]["child"] == rule_key(model)
    return audited


def audit_work(telemetry, observations, *, accepted):
    work = observed_work(observations)
    attempts = telemetry["model_evaluations"]
    assert telemetry["graph_evaluations"] == work["total_graph_calls"]
    assert attempts == telemetry["restarts"] + telemetry["repairs_evaluated"]
    assert attempts == sum(telemetry["rejections"].values()) + int(accepted)
    assert attempts == (work["baseline_graph_calls"] + telemetry["rejections"]["shape"]
                        + telemetry["rejections"]["duplicate"])
    assert telemetry["restarts"] == work["sample_calls"]
    assert 0 <= attempts <= telemetry["budget"]
    if not accepted:
        assert attempts == telemetry["budget"]
    if telemetry["mode"] == "restart":
        assert telemetry["repairs_evaluated"] == 0
    return work


def verify_restart_samples(level, seed, observations):
    rng = random.Random(seed)
    expected = []
    for _ in range(observations["sample_calls"]):
        model = state_planning._sample(list(NAMES[:level + 3]), level, rng)
        expected.append(None if model is None else rule_key(model))
    assert expected == observations["sample_sequence"], "Restart baseline changed the sampler"


def measure(mode, level, seed, budget):
    from spie.questions.brainbloom import planning_invention, planning_strategy

    started = perf_counter()
    try:
        model = planning_invention.propose(list(NAMES[:level + 3]), level,
                                           random.Random(seed), mode=mode, budget=budget)
    except planning_invention.InventionExhausted as exc:
        model, telemetry = None, exc.search
    else:
        telemetry = model["search"]
    generated = perf_counter()
    # The measured first run is uninstrumented. Record actual work during exact
    # replay so hashing/copying sampled worlds does not bias the timing comparison.
    replay_started = perf_counter()
    with observe_search() as observations:
        try:
            replay = planning_invention.propose(list(NAMES[:level + 3]), level,
                                                random.Random(seed), mode=mode, budget=budget)
        except planning_invention.InventionExhausted as exc:
            assert model is None and exc.search == telemetry
        else:
            assert replay == model
    replay_seconds = perf_counter() - replay_started
    work = audit_work(telemetry, observations, accepted=model is not None)
    if mode == "restart":
        verify_restart_samples(level, seed, observations)
    common = {"mode": mode, "level": level, "seed": seed,
              "generation_seconds": round(generated - started, 6),
              "replay_seconds": round(replay_seconds, 6),
              "search": telemetry, "observed_work": work}
    if model is None:
        return {**common, "status": "exhausted"}
    assert model["design_version"] == planning_invention.VERSION
    assert model["strategy"] == STRATEGY
    checking = perf_counter()
    proof = state_planning.check(model)
    certificate = planning_strategy.certify(model)
    checked = perf_counter()
    reports = audit_model(model)
    assert existing_gates(model, reports)
    expected = strategy_oracle(model, reports["baseline"])
    audit_strategy_certificate(model, expected, certificate)
    repairs = audit_history(model, observations)
    audited = perf_counter()
    return {**common, "status": "verified", "model": model,
            "certification_seconds": round(checked - checking, 6),
            "independent_audit_seconds": round(audited - checked, 6),
            "independent_strategy": expected, "strategy_certificate": certificate,
            "independent_physical_audit": reports, "smt": proof["smt"],
            "structure": state_planning.structural_key(model), "topology": topology_key(model),
            "accepted_repair_history": repairs, "rescued_by_repair": bool(repairs),
            "last_repair_rescued_strategy": bool(repairs)
            and repairs[-1]["parent_passes_existing_gates"]
            and not repairs[-1]["parent_strategy"]["qualifies"]}


def legacy_context(level, seed):
    """Original proposer frequency only; its stopping condition/budget differ."""
    from spie.questions.brainbloom import planning_strategy

    with observe_search() as observations:
        try:
            model = state_planning.propose(list(NAMES[:level + 3]), level, random.Random(seed))
        except state_planning.ProposalExhausted:
            return {"level": level, "seed": seed, "status": "exhausted",
                    "observed_work": observed_work(observations)}
    state_planning.check(model)
    reports = audit_model(model)
    assert existing_gates(model, reports)
    expected = strategy_oracle(model, reports["baseline"])
    if expected["qualifies"]:
        audit_strategy_certificate(model, expected, planning_strategy.certify(model))
    else:
        try:
            planning_strategy.certify(model)
        except ValueError:
            pass
        else:
            raise AssertionError("Strategy checker accepted an independently rejected legacy model")
    return {"level": level, "seed": seed, "status": "verified", "model": model,
            "observed_work": observed_work(observations), "independent_strategy": expected}


def summarize(rows):
    verified = [row for row in rows if row["status"] == "verified"]
    attempts = sum(row["search"]["model_evaluations"] for row in rows)
    timings = {}
    for field in ("generation", "certification", "independent_audit", "replay"):
        values = [row[field + "_seconds"] for row in rows if field + "_seconds" in row]
        timings[field] = {**distribution(values), "total": sum(values)}
    return {"requested": len(rows), "verified": len(verified),
            "exhausted": len(rows) - len(verified), "acceptance_rate": len(verified) / len(rows),
            "budgeted_candidate_attempts": attempts,
            "verified_per_candidate_attempt": len(verified) / attempts if attempts else None,
            "actual_baseline_graph_calls": sum(row["observed_work"]["baseline_graph_calls"]
                                               for row in rows),
            "actual_ablation_graph_calls": sum(row["observed_work"]["ablation_graph_calls"]
                                               for row in rows),
            "actual_total_graph_calls": sum(row["observed_work"]["total_graph_calls"]
                                            for row in rows),
            "repair_attempts": sum(row["search"]["repairs_evaluated"] for row in rows),
            "rejection_reasons": dict(sum((Counter(row["search"]["rejections"]) for row in rows),
                                           Counter())),
            "distinct_structures": len({row["structure"] for row in verified}),
            "distinct_topologies": len({row["topology"] for row in verified}),
            "rescued_by_repair": sum(row["rescued_by_repair"] for row in verified),
            "last_repair_rescued_strategy": sum(row["last_repair_rescued_strategy"]
                                                for row in verified),
            "minimum_action_penalty": distribution([
                row["independent_strategy"]["minimum_action_penalty"] for row in verified]),
            "seconds": timings}


def paired_outcomes(rows):
    cases = {}
    for row in rows:
        cases.setdefault((row["level"], row["seed"]), {})[row["mode"]] = row
    pairs = list(cases.values())
    return {"both_verified": sum(all(row[mode]["status"] == "verified"
                                     for mode in ("guided", "restart")) for row in pairs),
            "guided_only_verified": sum(row["guided"]["status"] == "verified"
                                        and row["restart"]["status"] != "verified"
                                        for row in pairs),
            "restart_only_verified": sum(row["restart"]["status"] == "verified"
                                         and row["guided"]["status"] != "verified"
                                         for row in pairs),
            "both_exhausted": sum(all(row[mode]["status"] == "exhausted"
                                      for mode in ("guided", "restart")) for row in pairs)}


def run(args):
    # Import both implementations before timing either mode.
    from spie.questions.brainbloom import planning_invention, planning_strategy

    assert planning_invention.STRATEGY in planning_strategy.STRATEGIES
    hashes = source_hashes()
    rows = []
    cases = [(level, seed) for level in args.levels for seed in args.seeds]
    for index, (level, seed) in enumerate(cases):
        for mode in ("guided", "restart") if index % 2 == 0 else ("restart", "guided"):
            row = measure(mode, level, seed, args.budget)
            rows.append(row)
            if args.progress:
                print(f"{mode} level={level} seed={seed}: {row['status']} "
                      f"after {row['search']['model_evaluations']} candidates", file=sys.stderr)
    legacy = [legacy_context(level, seed) for level in args.levels for seed in args.seeds]
    legacy_valid = [row for row in legacy if row["status"] == "verified"]
    assert source_hashes() == hashes, "Recorded source files changed during the benchmark"
    return {"benchmark": "planning-invention-equal-candidate-budget-v1",
            "scope": "Both modes use the unchanged sampler and identical acceptance gates. "
                     "Equal budgets count attempts including invalid/duplicate proposals; "
                     "actual baseline and ablation graph work is independently counted. "
                     "Generation, certificate, raw audit and replay timings are separate. "
                     "Modes alternate order. Legacy frequency is contextual; "
                     "it is not an efficiency comparison.",
            "configuration": {"seeds": args.seeds, "levels": args.levels, "budget": args.budget,
                              "strategy": STRATEGY,
                              "legacy_budget": state_planning.PROPOSAL_BUDGET},
            "environment": {"python": sys.version, "platform": platform.platform(),
                            "z3_solver": version("z3-solver"), "source_sha256": hashes},
            "summary": {mode: summarize([row for row in rows if row["mode"] == mode])
                        for mode in ("guided", "restart")},
            "paired_outcomes": paired_outcomes(rows),
            "levels": {str(level): {mode: summarize([row for row in rows if row["level"] == level
                                                     and row["mode"] == mode])
                                    for mode in ("guided", "restart")} for level in args.levels},
            "legacy_context": {"requested": len(legacy), "verified": len(legacy_valid),
                               "exhausted": len(legacy) - len(legacy_valid),
                               "strategy_qualified": sum(row["independent_strategy"]["qualifies"]
                                                         for row in legacy_valid),
                               "results": legacy},
            "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--levels", default="1,2,3")
    parser.add_argument("--budget", type=int, default=1000)
    parser.add_argument("--out", type=Path, help="Write evidence to a new JSON file")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    if not __debug__:
        parser.error("Do not use Python -O: independent audit assertions must remain enabled")
    try:
        args.seeds = [int(value) for value in args.seeds.split(",")]
        args.levels = [int(value) for value in args.levels.split(",")]
    except ValueError:
        parser.error("Seeds and levels must be comma-separated integers")
    if not 1 <= len(args.seeds) <= 20 or any(not 0 <= seed < 2**32 for seed in args.seeds):
        parser.error("Supply 1 to 20 seeds between 0 and 4294967295")
    if not args.levels or any(level not in (1, 2, 3) for level in args.levels):
        parser.error("Levels must be chosen from 1,2,3")
    if len(set(args.seeds)) != len(args.seeds) or len(set(args.levels)) != len(args.levels):
        parser.error("Do not repeat seeds or levels")
    if not 0 <= args.budget <= 2000:
        parser.error("Budget must be between 0 and 2000")
    if args.out and args.out.exists():
        parser.error("Choose a new output path; benchmark evidence is never overwritten")
    report = run(args)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"output": str(args.out), "summary": report["summary"],
                          "legacy_strategy_qualified": report["legacy_context"][
                              "strategy_qualified"]},
                         indent=2))
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
