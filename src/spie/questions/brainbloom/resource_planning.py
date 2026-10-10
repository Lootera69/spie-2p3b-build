"""Finite delivery plans with fuel, inclusive deadlines, and prerequisite tasks.

The planner uses a subset dynamic program. A separate permutation interpreter
replays every complete trip (at most 5! = 120) to certify the displayed answer.
All three kinds of constraint must individually rule out a displayed option.
"""

from __future__ import annotations

from itertools import combinations, permutations

from ...forge.corpus import digest

CONSTRAINTS = ("fuel", "deadline", "dependency")


def _validate(model: dict) -> None:
    """Validate the problem, before either solver consumes user-supplied data."""
    if not isinstance(model, dict):
        raise ValueError("A resource plan model must be an object")
    names = model.get("names")
    if (not isinstance(names, list) or not 4 <= len(names) <= 6
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len({name.casefold() for name in names}) != len(names)):
        raise ValueError("Use four to six distinct location names, including the depot")
    n = len(names)
    if type(model.get("level")) is not int or model["level"] != n - 3:
        raise ValueError("Resource-plan level must match its three to five delivery tasks")
    for field in ("travel_time", "travel_fuel"):
        matrix = model.get(field)
        if (not isinstance(matrix, list) or len(matrix) != n
                or any(not isinstance(row, list) or len(row) != n for row in matrix)):
            raise ValueError(f"{field} must be a square location matrix")
        if any(type(matrix[i][j]) is not int or matrix[i][j] < 0
               or (i == j and matrix[i][j] != 0)
               or matrix[i][j] != matrix[j][i] for i in range(n) for j in range(n)):
            raise ValueError(f"{field} must have symmetric nonnegative entries and zero diagonal")
    if any(bool(model["travel_time"][i][j]) != bool(model["travel_fuel"][i][j])
           for i in range(n) for j in range(n)):
        raise ValueError("Every listed leg must have both positive time and positive fuel")
    if type(model.get("fuel_budget")) is not int or model["fuel_budget"] < 0:
        raise ValueError("Fuel budget must be a nonnegative integer")
    deadlines = model.get("deadlines")
    if (not isinstance(deadlines, list) or len(deadlines) != n or deadlines[0] is not None
            or any(type(t) is not int or t < 0 for t in deadlines[1:])):
        raise ValueError("Give every task a nonnegative deadline and the depot no deadline")
    dependencies = model.get("dependencies")
    if (not isinstance(dependencies, list) or not dependencies
            or any(not isinstance(pair, list) or len(pair) != 2
                   or any(type(i) is not int or not 1 <= i < n for i in pair)
                   or pair[0] == pair[1] for pair in dependencies)
            or len({tuple(pair) for pair in dependencies}) != len(dependencies)):
        raise ValueError("Dependencies must be distinct pairs of different delivery tasks")


def interpret(model: dict, order: list[int]) -> dict:
    """Replay one complete trip, recording violations without pruning or DP logic."""
    _validate(model)
    n = len(model["names"])
    if (not isinstance(order, list) or any(type(i) is not int for i in order)
            or sorted(order) != list(range(1, n))):
        raise ValueError("A complete plan must visit every delivery exactly once")
    return _replay(model, order)


def _replay(model: dict, order: list[int]) -> dict:
    names = model["names"]
    path = [0, *order, 0]
    missing = [{"constraint": "unlisted-leg", "origin": a, "destination": b,
                "reason": f"No listed leg connects {names[a]} and {names[b]}."}
               for a, b in zip(path[:-1], path[1:], strict=True)
               if not model["travel_time"][a][b]]
    if missing:
        return {"order": list(order), "path": path, "time": None, "fuel": None,
                "arrivals": [], "feasible": False, "violations": missing}
    elapsed = 0
    used = 0
    arrivals = []
    violations = []
    # This interpreter always executes the full route, even after a missed limit.
    for origin, destination in zip(path[:-1], path[1:], strict=True):
        elapsed += model["travel_time"][origin][destination]
        used += model["travel_fuel"][origin][destination]
        if destination:
            deadline = model["deadlines"][destination]
            arrivals.append({"task": destination, "time": elapsed, "deadline": deadline})
            if elapsed > deadline:
                violations.append({"constraint": "deadline", "task": destination,
                                   "actual": elapsed, "limit": deadline,
                                   "reason": f"{names[destination]} arrives at minute {elapsed}, "
                                             f"after its deadline of {deadline}."})
    if used > model["fuel_budget"]:
        violations.append({"constraint": "fuel", "actual": used,
                           "limit": model["fuel_budget"],
                           "reason": f"The complete trip needs {used} fuel units, "
                                     f"exceeding the budget of {model['fuel_budget']}."})
    for before, after in model["dependencies"]:
        if order.index(before) > order.index(after):
            violations.append({"constraint": "dependency", "before": before, "after": after,
                               "reason": f"{names[before]} must be delivered before "
                                         f"{names[after]}."})
    return {"order": list(order), "path": path, "time": elapsed, "fuel": used,
            "arrivals": arrivals, "feasible": not violations, "violations": violations}


def solve(model: dict) -> dict:
    """Subset DP retaining exact time/fuel states and counting all feasible routes.

    States merge only when visited tasks, current location, time, and fuel all
    agree. Keeping counts detects equal optima even when several orders merge.
    This solver does not call the complete-route interpreter.
    """
    _validate(model)
    n = len(model["names"])
    finish = (1 << (n - 1)) - 1
    required = [0] * n
    for before, after in model["dependencies"]:
        required[after] |= 1 << (before - 1)
    states = [dict() for _ in range(finish + 1)]
    states[0][(0, 0, 0)] = (1, ())
    state_count = 0
    for mask in range(finish + 1):
        for (last, elapsed, fuel), (count, witness) in states[mask].items():
            state_count += 1
            for task in range(1, n):
                bit = 1 << (task - 1)
                if mask & bit or required[task] & mask != required[task]:
                    continue
                if not model["travel_time"][last][task]:
                    continue
                arrival = elapsed + model["travel_time"][last][task]
                remaining_used = fuel + model["travel_fuel"][last][task]
                if (arrival > model["deadlines"][task]
                        or remaining_used > model["fuel_budget"]):
                    continue
                key = (task, arrival, remaining_used)
                old_count, old_witness = states[mask | bit].get(key, (0, (*witness, task)))
                states[mask | bit][key] = (old_count + count,
                                          min(old_witness, (*witness, task)))
    best = None
    witness = None
    feasible_count = optimal_count = 0
    for (last, elapsed, fuel), (count, route) in states[finish].items():
        if not model["travel_time"][last][0]:
            continue
        if fuel + model["travel_fuel"][last][0] > model["fuel_budget"]:
            continue
        elapsed += model["travel_time"][last][0]
        feasible_count += count
        if best is None or elapsed < best:
            best, witness, optimal_count = elapsed, route, count
        elif elapsed == best:
            optimal_count += count
            witness = min(witness, route)
    return {"best_time": best, "solution": list(witness) if witness else None,
            "feasible_count": feasible_count, "optimal_count": optimal_count,
            "states_checked": state_count}


def _constraint_set(route: dict) -> set[str]:
    return {violation["constraint"] for violation in route["violations"]}


def _all_routes(model: dict) -> list[dict]:
    return [_replay(model, list(order))
            for order in permutations(range(1, len(model["names"])))]


def _matrix(n: int, rng, maximum: int) -> list[list[int]]:
    result = [[0] * n for _ in range(n)]
    for i, j in combinations(range(n), 2):
        result[i][j] = result[j][i] = rng.randint(1, maximum)
    return result


def propose(names: list[str], level: int, rng) -> dict:
    """Seeded bounded search; accepted options make every constraint necessary."""
    if type(level) is not int or level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("Resource plans need level+3 names for a level from one to three")
    for _ in range(3000):
        n = len(names)
        target = rng.sample(range(1, n), n - 1)
        times = _matrix(n, rng, level + 6)
        fuel = _matrix(n, rng, level + 5)
        path = [0, *target, 0]
        # Keep the target cycle, adding a few cross-links. Sparse maps remain
        # readable while allowing several genuinely different complete trips.
        listed = {tuple(sorted((a, b))) for a, b in zip(path[:-1], path[1:], strict=True)}
        spare = [pair for pair in combinations(range(n), 2) if pair not in listed]
        listed.update(rng.sample(spare, min(len(spare), (6, 8, 11)[level - 1] - len(listed))))
        for a, b in combinations(range(n), 2):
            if (a, b) not in listed:
                times[a][b] = times[b][a] = fuel[a][b] = fuel[b][a] = 0
        arrivals = [None] * n
        elapsed = 0
        for origin, destination in zip(path[:-2], path[1:-1], strict=True):
            elapsed += times[origin][destination]
            arrivals[destination] = elapsed + rng.randint(0, 4 * level + 3)
        pairs = list(combinations(target, 2))
        dependencies = [list(pair) for pair in rng.sample(pairs, 1 if level < 3 else 2)]
        model = {"names": list(names), "level": level, "travel_time": times,
                 "travel_fuel": fuel,
                 "fuel_budget": sum(fuel[a][b] for a, b in zip(path[:-1], path[1:],
                                                               strict=True)) + rng.randrange(3),
                 "deadlines": arrivals, "dependencies": dependencies}
        _validate(model)
        routes = _all_routes(model)
        feasible = sorted((r for r in routes if r["feasible"]), key=lambda r: r["time"])
        if not feasible or (len(feasible) > 1 and feasible[0]["time"] == feasible[1]["time"]):
            continue
        winner = feasible[0]
        rejected = [[r for r in routes if _constraint_set(r) == {constraint}]
                    for constraint in CONSTRAINTS]
        if not all(rejected):
            continue
        if not any(r["time"] < winner["time"] for group in rejected for r in group):
            continue
        if level > 1:
            cheapest = min(t for t in times[0][1:] if t)
            if times[0][winner["order"][0]] == cheapest:
                continue
        wrongs = [rng.choice([r for r in group if r["time"] == min(g["time"] for g in group)])
                  for group in rejected]
        options = [winner["order"], *[route["order"] for route in wrongs]]
        rng.shuffle(options)
        model.update(options=options, answer_index=options.index(winner["order"]),
                     solution=winner["order"], best_time=winner["time"])
        # The generation certificate comes from DP, then check independently replays it.
        planned = solve(model)
        if planned["solution"] != model["solution"] or planned["best_time"] != model["best_time"]:
            raise RuntimeError("Resource planner and complete-trip interpreter disagreed")
        return model
    raise RuntimeError("No resource plan passed all constraint gates within the bounded search")


def _label(index: int) -> str:
    return f"Plan {chr(65 + index)}"


def _route_text(names: list[str], order: list[int]) -> str:
    return " → ".join(names[i] for i in [0, *order, 0])


def check(model: dict) -> dict:
    """Certify feasibility, global optimality, option reasons, and the full witness."""
    planned = solve(model)
    routes = _all_routes(model)
    feasible = [r for r in routes if r["feasible"]]
    if not feasible:
        raise RuntimeError("The resource plan is impossible: no feasible complete trip")
    best = min(r["time"] for r in feasible)
    winners = [r for r in feasible if r["time"] == best]
    if len(winners) != 1:
        raise RuntimeError("The resource plan has ambiguous fastest complete trips")
    winner = winners[0]
    if (planned["best_time"] != best or planned["solution"] != winner["order"]
            or planned["feasible_count"] != len(feasible) or planned["optimal_count"] != 1):
        raise RuntimeError("Resource DP and exhaustive complete-trip replay disagreed")
    options = model.get("options")
    if (not isinstance(options, list) or len(options) != 4
            or any(not isinstance(o, list) or any(type(i) is not int for i in o)
                   or sorted(o) != list(range(1, len(model["names"]))) for o in options)
            or len({tuple(o) for o in options}) != 4):
        raise ValueError("Resource plans must show four distinct complete delivery orders")
    answer = model.get("answer_index")
    if (type(answer) is not int or not 0 <= answer < 4
            or options[answer] != winner["order"] or model.get("solution") != winner["order"]
            or type(model.get("best_time")) is not int or model["best_time"] != best):
        raise RuntimeError("The resource plan answer or full witness disagrees with replay")
    option_rows = [_replay(model, option) for option in options]
    wrong_sets = [_constraint_set(r) for i, r in enumerate(option_rows) if i != answer]
    if any(wrong_sets.count({constraint}) != 1 for constraint in CONSTRAINTS):
        raise RuntimeError("Each resource constraint must independently rule out one option")
    if not any(not r["feasible"] and r["time"] < best for r in option_rows):
        raise RuntimeError("A resource plan must reject a faster displayed infeasible option")
    independent = {constraint: sum(_constraint_set(r) == {constraint} for r in routes)
                   for constraint in CONSTRAINTS}
    names = model["names"]
    steps = []
    option_costs = {}
    for i, route in enumerate(option_rows):
        label = _label(i)
        reasons = [v["reason"] for v in route["violations"]]
        option_costs[label] = {**route, "label": label, "reasons": reasons,
                               "is_answer": i == answer}
        if reasons:
            steps.append(f"{label}: {route['time']} minutes, {route['fuel']} fuel. "
                         + " ".join(reasons))
        else:
            arrivals = "; ".join(f"{names[a['task']]} at {a['time']} ≤ {a['deadline']}"
                                 for a in route["arrivals"])
            steps.append(f"{label}: {route['time']} minutes, {route['fuel']} fuel. "
                         f"Deadlines: {arrivals}. Every prerequisite is delivered first.")
    steps.append(f"Choose {_label(answer)}: {_route_text(names, winner['order'])}. "
                 f"It is the unique fastest feasible complete trip, taking {best} minutes "
                 f"including the return to {names[0]}.")
    slower = [r["time"] for r in feasible if r["time"] > best]
    quality = {"locations": len(names), "delivery_tasks": len(names) - 1,
               "constraint_types": list(CONSTRAINTS),
               "dependency_count": len(model["dependencies"]), "option_count": 4,
               "routes_checked": len(routes), "dp_states_checked": planned["states_checked"],
               "listed_legs": sum(bool(model["travel_time"][a][b])
                                  for a, b in combinations(range(len(names)), 2)),
               "allowed_complete_routes": sum(r["time"] is not None for r in routes),
               "feasible_routes": len(feasible), "optimal_routes": 1,
               "best_total_time": best, "winning_fuel": winner["fuel"],
               "optimality_margin": min(slower) - best if slower else None,
               "independently_rejected_routes": independent,
               "constraint_ablation_feasible_counts": {
                   constraint: len(feasible) + count for constraint, count in independent.items()},
               "faster_infeasible_routes": sum(not r["feasible"] and r["time"] is not None
                                                and r["time"] < best
                                                for r in routes),
               "faster_infeasible_options": sum(not r["feasible"] and r["time"] < best
                                                 for r in option_rows),
               "cheapest_first_leg_is_optimal": (model["travel_time"][0][winner["order"][0]]
                                                 == min(t for t in model["travel_time"][0][1:]
                                                        if t))}
    return {"method": "subset-dp-and-independent-complete-trip-replay", "agree": True,
            "scope": "all orders visiting each stated delivery once and returning to the depot; "
                     "listed positive symmetric legs, instant service, no refueling, "
                     "inclusive deadlines; an optimal trip has no waiting",
            "model": model, "steps": steps, "option_costs": option_costs,
            "witness": winner, "quality": quality,
            "structural_key": digest(["resource-plan-v1", len(names), model["travel_time"],
                                      model["travel_fuel"], model["fuel_budget"],
                                      model["deadlines"], model["dependencies"], options])}


def render(model: dict) -> dict:
    proof = check(model)
    names = model["names"]
    depot = names[0]
    legs = "\n".join(f"{names[a]} ↔ {names[b]}: {model['travel_time'][a][b]}/"
                     f"{model['travel_fuel'][a][b]}"
                     for a, b in combinations(range(len(names)), 2)
                     if model["travel_time"][a][b])
    deadlines = "; ".join(f"{names[i]}≤{model['deadlines'][i]}"
                          for i in range(1, len(names)))
    dependencies = "; ".join(f"{names[a]}→{names[b]}"
                             for a, b in model["dependencies"])
    options = "\n".join(f"{chr(65 + i)}: " + "→".join(names[task] for task in order)
                        for i, order in enumerate(model["options"]))
    stem = (f"Fictional stops. Start/end {depot}, minute 0, fuel≤{model['fuel_budget']}. "
            "Visit others once, instantly. No refueling. "
            "Only listed reversible legs (minutes/fuel):\n" + legs
            + "\nArrival deadlines: " + deadlines
            + ".\nDeliver before: " + dependencies
            + ".\nOrders:\n" + options
            + "\nFastest feasible plan?")
    answer = _label(model["answer_index"])
    return {"stem": stem, "answer": answer,
            "distractors": [_label(i) for i in range(4) if i != model["answer_index"]],
            "explanation": " ".join(proof["steps"]), "proof": proof,
            "hints": ["Check the prerequisite order in each plan first.",
                      "Add travel times from minute 0; a deadline concerns arrival at that stop.",
                      "Fuel must cover every leg, including the final return to the depot. "
                      "A faster trip is unusable if it breaks any limit."]}
