"""Small directed route puzzles, independently checked by exhaustive path enumeration."""

from __future__ import annotations

import heapq

from ...forge.corpus import digest


def shortest(edges, start, goal):
    queue = [(0, (start,))]
    visited = set()
    while queue:
        cost, path = heapq.heappop(queue)
        node = path[-1]
        if node == goal:
            return cost, list(path)
        if node in visited:
            continue
        visited.add(node)
        for a, b, weight in edges:
            if a == node and b not in visited:
                heapq.heappush(queue, (cost + weight, (*path, b)))
    raise ValueError("No route reaches the destination")


def paths(edges, start, goal, seen=()):
    if start == goal:
        return [(0, [goal])]
    return [(weight + cost, [start, *path])
            for a, b, weight in edges if a == start and b not in (*seen, start)
            for cost, path in paths(edges, b, goal, (*seen, start))]


def propose(names, level, rng):
    n = len(names)
    first = [1, 2, 3, n - 1]
    for _ in range(80):
        edges = [[0, b, rng.randint(1, 15)] for b in first]
        edges.extend([a, a + 1, rng.randint(1, 9)] for a in range(1, n - 1))
        edges.extend([a, b, rng.randint(1, 12)] for a in range(1, n - 2)
                     for b in range(a + 2, n) if rng.random() < 0.45)
        options = []
        for b in first:
            price = next(w for a, v, w in edges if a == 0 and v == b)
            cost, path = shortest(edges, b, n - 1)
            options.append({"next": b, "cost": price + cost, "path": [0, *path]})
        ordered = sorted(options, key=lambda o: o["cost"])
        if ordered[0]["cost"] == ordered[1]["cost"]:
            continue
        cheap = min((w, b) for a, b, w in edges if a == 0)[1]
        if level > 1 and cheap == ordered[0]["next"]:
            continue
        return {"names": names, "edges": edges, "start": 0, "goal": n - 1,
                "options": options, "answer": ordered[0]["next"]}
    raise ValueError("No route with a unique best first move found; try another variation")


def check(model):
    all_routes = paths(model["edges"], model["start"], model["goal"])
    checked = {o["next"]: min(cost for cost, path in all_routes if path[1] == o["next"])
               for o in model["options"]}
    claimed = {o["next"]: o["cost"] for o in model["options"]}
    winners = [node for node, cost in checked.items() if cost == min(checked.values())]
    if checked != claimed or winners != [model["answer"]]:
        raise RuntimeError("Dijkstra/exhaustive route checks disagreed")
    for option in model["options"]:
        if (option["cost"], option["path"]) not in all_routes:
            raise RuntimeError("A claimed best route cannot be replayed")
    names = model["names"]
    steps = []
    for option in model["options"]:
        route = " → ".join(names[i] for i in option["path"])
        weights = [next(w for x, y, w in model["edges"] if (x, y) == (a, b))
                   for a, b in zip(option["path"][:-1], option["path"][1:], strict=True)]
        steps.append(f"Starting with {names[option['next']]}, a cheapest route is {route}: "
                     + " + ".join(map(str, weights)) + f" = {option['cost']}.")
    steps.append(f"Choose {names[model['answer']]}; it gives the lowest complete route cost.")
    costs = sorted(checked.values())
    return {"method": "dijkstra-and-exhaustive-route-replay", "agree": True,
            "scope": "the displayed directed routes and positive travel costs",
            "model": model, "route_model": model, "steps": steps,
            "quality": {"locations": len(names), "routes_checked": len(all_routes),
                        "best_total_cost": costs[0], "optimality_margin": costs[1] - costs[0]},
            "structural_key": digest(["route-v1", len(names), sorted(model["edges"]),
                                       model["start"], model["goal"]])}


def render(model):
    names = model["names"]
    proof = check(model)
    start, goal = names[model["start"]], names[model["goal"]]
    stem = (f"Travel from {start} to {goal}. This invented map has one-way routes; "
            "numbers are travel costs. Only listed routes are allowed.\n"
            + "\n".join(f"{names[a]} → {names[b]}: {w}" for a, b, w in model["edges"])
            + "\nPossible first stops: " + ", ".join(names[o["next"]] for o in model["options"])
            + ".\nWhich first stop minimizes the full trip's cost?")
    return {"stem": stem, "answer": names[model["answer"]],
            "distractors": [names[o["next"]] for o in model["options"]
                            if o["next"] != model["answer"]],
            "explanation": (f"Start with {names[model['answer']]}. Its cheapest complete trip "
                            f"costs {proof['quality']['best_total_cost']}, lower than any other "
                            "first stop's best complete trip."), "proof": proof,
            "hints": ["Compare the full trip through each possible first stop.",
                      "Add every route cost through to the destination; the cheapest first leg "
                      "need not give the cheapest whole trip."]}
