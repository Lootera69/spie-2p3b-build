"""Audit fixed-seed state plans with a separate domain interpreter and BFS oracle.

The oracle does not call the production compiler, transition function or solver.
Runtime is local observed throughput, not a human-difficulty or compute claim.
Run with ``python tools/benchmark_state_planning.py --seeds 0,1,2,3,4,5,6,7,8,9``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import statistics
import sys
from collections import deque
from importlib.metadata import version
from itertools import permutations
from pathlib import Path
from time import perf_counter

from spie import search
from spie.forge.corpus import digest
from spie.questions.brainbloom import state_planning
from spie.validate import validate

RELAXATIONS = (None, "energy", "gates", "switches", "recharge")
NAMES = ("Depot", "Orchard", "Harbour", "Meadow", "Tower", "Summit")


def initial(model):
    return (0, model["initial_energy"], *model["initial_gates"], 0)


def successors(model, state, relaxed=None):
    """Independent raw-model transition specification for the audit."""
    location, battery, left, right, consumed = state
    transitions = {}
    if location == len(model["names"]) - 1:
        return transitions
    for row in model["routes"]:
        origin, destination, spend, gate = row
        enough = battery >= spend or relaxed == "energy"
        unlocked = gate == -1 or (left, right)[gate] == 1 or relaxed == "gates"
        if location == origin and enough and unlocked:
            remainder = battery if relaxed == "energy" else battery - spend
            transitions[f"move_{origin}_{destination}"] = (
                destination, remainder, left, right, consumed,
            )
    for site, mask, spend in model["switches"]:
        if (site != location or relaxed == "switches"
                or (battery < spend and relaxed != "energy")):
            continue
        settings = [left, right]
        for gate in range(2):
            if mask & (2 ** gate):
                settings[gate] = 1 - settings[gate]
        remainder = battery if relaxed == "energy" else battery - spend
        transitions[f"switch_{site}"] = (site, remainder, *settings, consumed)
    if (location == model["charger"] and consumed == 0
            and battery < model["capacity"] and relaxed != "recharge"):
        transitions["recharge"] = (location, model["capacity"], left, right, 1)
    return dict(sorted(transitions.items()))


def domain_graph(model, relaxed=None):
    start = initial(model)
    graph, pending = {}, deque([start])
    discovered = {start}
    # A bound derived independently from the declared finite state dimensions.
    bound = len(model["names"]) * (model["capacity"] + 1) * 4 * 2
    while pending:
        state = pending.popleft()
        graph[state] = successors(model, state, relaxed)
        for target in graph[state].values():
            assert 0 <= target[0] < len(model["names"])
            assert 0 <= target[1] <= model["capacity"]
            assert all(bit in (0, 1) for bit in target[2:])
            if target not in discovered:
                discovered.add(target)
                assert len(discovered) <= bound
                pending.append(target)
    return graph


def shortest(model, graph, start, avoid=frozenset()):
    """Forward BFS counting all shortest action sequences, including merged paths."""
    if start in avoid:
        return None, 0, []
    goal = len(model["names"]) - 1
    distances, counts, witnesses = {start: 0}, {start: 1}, {start: ()}
    queue, best, total, winner = deque([start]), None, 0, None
    while queue:
        state = queue.popleft()
        distance = distances[state]
        if best is not None and distance > best:
            break
        if state[0] == goal:
            best, total = distance, total + counts[state]
            winner = min(winner, witnesses[state]) if winner is not None else witnesses[state]
            continue
        for action, target in graph[state].items():
            if target in avoid:
                continue
            path = (*witnesses[state], action)
            if target not in distances:
                distances[target] = distance + 1
                counts[target], witnesses[target] = counts[state], path
                queue.append(target)
            elif distances[target] == distance + 1:
                counts[target] += counts[state]
                witnesses[target] = min(witnesses[target], path)
    return best, total, list(winner or ())


def committed_costs(model, graph, start):
    """Exclude plans that first undo their move without improving their state."""
    dominated = {state for state in graph if state[0] == start[0]
                 and state[2:4] == start[2:4] and state[1] <= start[1]
                 and state[4] >= start[4]}
    costs = {}
    for action, target in graph[start].items():
        remaining, _, _ = shortest(model, graph, target, dominated)
        costs[action] = None if remaining is None else remaining + 1
    return costs


def oracle(model, relaxed=None):
    graph, start = domain_graph(model, relaxed), initial(model)
    best, count, witness = shortest(model, graph, start)
    costs = {}
    for action, target in graph[start].items():
        remaining, _, _ = shortest(model, graph, target)
        costs[action] = None if remaining is None else remaining + 1
    states, current = [start], start
    for action in witness:
        current = graph[current][action]
        states.append(current)
    later = [committed_costs(model, graph, state) for state in states[1:-1]]
    return {"best_steps": best, "optimal_plan_count": count, "solution": witness,
            "solution_states": [list(state) for state in states], "first_costs": costs,
            "optimal_first_actions": [action for action, cost in costs.items()
                                      if cost is not None and cost == best],
            "committed_first_costs": committed_costs(model, graph, start),
            "reachable_states": len(graph),
            "reachable_locations": len({state[0] for state in graph}),
            "transition_count": sum(len(actions) for actions in graph.values()),
            "goal_states": sum(state[0] == len(model["names"]) - 1 for state in graph),
            "later_committed_choices": [sum(cost is not None for cost in row.values())
                                        for row in later],
            "later_committed_costs": later, "graph": graph}


def audit_model(model, *, all_relaxations=True):
    """Compare every reachable transition, not just one successful witness."""
    reports = {}
    for relaxed in RELAXATIONS if all_relaxations else (None,):
        expected = oracle(model, relaxed)
        actual = state_planning.solve(model, relaxed=relaxed)
        for field in ("best_steps", "first_costs", "optimal_first_actions", "solution",
                      "solution_states", "reachable_states", "reachable_locations",
                      "committed_first_costs", "later_committed_choices"):
            assert actual[field] == expected[field], (
                relaxed, field, actual[field], expected[field],
            )
        puzzle = state_planning.compile_model(model, relaxed=relaxed)
        assert not validate(puzzle)
        assert all(action.cost == 1 for action in puzzle.actions)
        assert not puzzle.objective.requires_unique
        compiled = search.explore(puzzle)
        assert not compiled.truncated
        observed = {state: {action: compiled.states[target]
                            for action, target in compiled.adj[index]}
                    for index, state in enumerate(compiled.states)}
        assert observed == expected["graph"], relaxed
        assert {compiled.states[index] for index in compiled.goals} == {
            state for state in expected["graph"] if state[0] == len(model["names"]) - 1
        }, relaxed
        reports[relaxed or "baseline"] = {key: value for key, value in expected.items()
                                          if key != "graph"}
    return reports


def topology_key(model):
    """A label- and interior-permutation-invariant route topology fingerprint."""
    count = len(model["names"])
    variants = []
    for middle in permutations(range(1, count - 1)):
        renaming = {old: new for new, old in enumerate((0, *middle, count - 1))}
        variants.append(tuple(sorted((renaming[a], renaming[b])
                                     for a, b, _, _ in model["routes"])))
    return digest([count, min(variants)])


def measure(level, seed):
    start = perf_counter()
    try:
        model = state_planning.propose(list(NAMES[:level + 3]), level, random.Random(seed))
    except state_planning.ProposalExhausted as exc:
        # A verifier failure or implementation error must abort the benchmark.
        # Only the documented proposal-budget exhaustion is an expected rejection.
        generated = perf_counter()
        try:
            state_planning.propose(list(NAMES[:level + 3]), level, random.Random(seed))
        except state_planning.ProposalExhausted as replay_exc:
            assert str(replay_exc) == str(exc)
        else:
            raise AssertionError("A rejected seed succeeded during deterministic replay") from exc
        return {"level": level, "seed": seed, "status": "rejected", "reason": str(exc),
                "generation_seconds": round(generated - start, 6),
                "replay_seconds": round(perf_counter() - generated, 6),
                "search": {"budget": state_planning.PROPOSAL_BUDGET,
                           "attempts": state_planning.PROPOSAL_BUDGET, "rejections": None}}
    generated = perf_counter()
    proof = state_planning.check(model)
    checked = perf_counter()
    reports = audit_model(model)
    audited = perf_counter()
    base = reports["baseline"]
    assert model == state_planning.propose(list(NAMES[:level + 3]), level, random.Random(seed))
    assert proof == state_planning.check(model)
    replayed = perf_counter()
    assert model["best_steps"] == base["best_steps"]
    assert base["optimal_first_actions"] == [model["answer_action"]]
    committed = base["committed_first_costs"]
    assert sum(cost is not None for cost in committed.values()) >= 2
    assert max(base["later_committed_choices"], default=0) >= 2
    signature = (base["best_steps"], base["optimal_first_actions"])
    ablations = {key: {**{field: value[field] for field in
                         ("best_steps", "optimal_first_actions", "reachable_states")},
                       "answer_changes": value["optimal_first_actions"]
                       != base["optimal_first_actions"],
                       "optimum_changes": value["best_steps"] != base["best_steps"]}
                 for key, value in reports.items() if key != "baseline"}
    assert all((row["best_steps"], row["optimal_first_actions"]) != signature
               for row in ablations.values())
    alternative = [cost for action, cost in committed.items()
                   if cost is not None and action != model["answer_action"]]
    assert alternative
    assert min(alternative) > base["best_steps"]
    assert sum(model["search"]["rejections"].values()) + 1 == model["search"]["attempts"]
    return {"level": level, "seed": seed, "status": "verified",
            "generation_seconds": round(generated - start, 6),
            "certification_seconds": round(checked - generated, 6),
            "independent_audit_seconds": round(audited - checked, 6),
            "replay_seconds": round(replayed - audited, 6),
            "best_steps": base["best_steps"], "optimal_plan_count": base["optimal_plan_count"],
            "legal_first_actions": len(base["first_costs"]),
            "committed_first_costs": committed,
            "first_move_margin": min(alternative) - base["best_steps"],
            "later_committed_choices": base["later_committed_choices"],
            "reachable_states": base["reachable_states"], "ablations": ablations,
            "structure": state_planning.structural_key(model), "topology": topology_key(model),
            "search": model["search"], "model": model, "smt": proof["smt"],
            "independent_audit": reports}


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None}
    return {"count": len(values), "min": min(values), "median": statistics.median(values),
            "p95": values[math.ceil(0.95 * len(values)) - 1], "max": max(values)}


def summarize(rows):
    valid = [row for row in rows if row["status"] == "verified"]
    attempts = sum(row["search"]["attempts"] for row in rows)
    reasons = {reason: sum(row["search"]["rejections"][reason] for row in valid)
               for reason in ("unsolved", "choice", "mechanics")}
    return {"requested": len(rows), "verified": len(valid), "rejected": len(rows) - len(valid),
            "request_acceptance_rate": len(valid) / len(rows),
            "proposals_attempted": attempts,
            "proposals_rejected": attempts - len(valid),
            "proposal_acceptance_rate": len(valid) / attempts if attempts else None,
            "known_proposal_rejection_reasons": reasons,
            "proposal_rejections_without_reason_breakdown": attempts - len(valid)
            - sum(reasons.values()),
            "distinct_structures": len({row["structure"] for row in valid}),
            "distinct_topologies": len({row["topology"] for row in valid}),
            "multiple_optimal_continuations": sum(row["optimal_plan_count"] > 1 for row in valid),
            "committed_first_branching": sum(sum(cost is not None for cost in
                                                row["committed_first_costs"].values()) >= 2
                                             for row in valid),
            "later_committed_branching": sum(any(count > 1 for count in
                                                 row["later_committed_choices"]) for row in valid),
            "mechanic_necessity": {mechanic: {
                "signature_changes": sum(row["ablations"][mechanic]["answer_changes"]
                                         or row["ablations"][mechanic]["optimum_changes"]
                                         for row in valid),
                "answer_changes": sum(row["ablations"][mechanic]["answer_changes"]
                                      for row in valid),
                "optimum_changes": sum(row["ablations"][mechanic]["optimum_changes"]
                                       for row in valid),
                "unreachable_after_removal": sum(row["ablations"][mechanic]["best_steps"] is None
                                                 for row in valid),
            } for mechanic in RELAXATIONS[1:]},
            "best_steps": distribution([row["best_steps"] for row in valid]),
            "reachable_states": distribution([row["reachable_states"] for row in valid]),
            "first_move_margin": distribution([row["first_move_margin"] for row in valid]),
            "seconds": {**{field: distribution([row[field + "_seconds"] for row in rows
                                                if field + "_seconds" in row]) for field in
                           ("generation", "certification", "independent_audit", "replay")},
                        "generation_and_certification": distribution([
                            row["generation_seconds"] + row.get("certification_seconds", 0)
                            for row in rows])}}


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = [Path(__file__).resolve(), Path(state_planning.__file__).resolve(),
             root / "src/spie/search.py", root / "src/spie/interpreter.py",
             root / "src/spie/z3_compile.py"]
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def run(args):
    hashes = source_hashes()
    rows = [measure(level, seed) for level in args.levels for seed in args.seeds]
    assert source_hashes() == hashes, "Benchmark sources changed during the measurement"
    return {"benchmark": "brainbloom-state-planning-fixed-seeds-v2",
            "scope": "Independent raw-domain BFS and full compiled transition comparison; "
                     "all four mechanic ablations; seeded replay; all actions cost one step. "
                     "Committed alternatives exclude undo-only returns with no state gain. "
                     "Only the optimal first action is unique; later paths may tie. "
                     "Timing phases are separate local observations. No human-difficulty claim.",
            "configuration": {"seeds": args.seeds, "levels": args.levels,
                              "proposal_budget": state_planning.PROPOSAL_BUDGET,
                              "maximum_states": state_planning.MAX_STATES,
                              "maximum_steps": state_planning.MAX_STEPS},
            "environment": {"python": sys.version, "platform": platform.platform(),
                            "z3_solver": version("z3-solver"), "source_sha256": hashes},
            "summary": summarize(rows),
            "levels": {str(level): summarize([row for row in rows if row["level"] == level])
                       for level in args.levels},
            "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--levels", default="1,2,3")
    parser.add_argument("--out", type=Path, help="Write JSON evidence to a new file")
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
        parser.error("Levels must be a comma-separated list from 1,2,3")
    if len(set(args.seeds)) != len(args.seeds) or len(set(args.levels)) != len(args.levels):
        parser.error("Do not repeat seeds or levels")
    if args.out and args.out.exists():
        parser.error("Choose a new output path; benchmark evidence is never overwritten")
    report = run(args)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"output": str(args.out), "summary": report["summary"]}, indent=2))
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
