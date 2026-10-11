"""Certify a requested first-decision strategy from the compiled reachable graph.

This checker never reads proposal diagnostics, saved answers or domain-solver
results. The ordinary state-planning proof separately checks the compiler against
raw rules and certifies mechanic necessity and later branching. Here independent
forward searches establish the narrower, explicitly named strategy claim.
"""

from __future__ import annotations

from collections import deque

from ... import search
from ...validate import validate

VERSION = "planning-strategy-core-bfs-v1"
STRATEGIES = ("invest-energy",)
MAX_STATES = 512


def _shortest(graph, start, forbidden=frozenset()):
    """Return one lexicographically first shortest action/state witness, or None."""
    if start in forbidden:
        return None
    parents = {start: None}
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current in graph.goals:
            actions, states = [], [current]
            while parents[current] is not None:
                previous, action = parents[current]
                actions.append(action)
                states.append(previous)
                current = previous
            return list(reversed(actions)), list(reversed(states))
        for action, target in sorted(graph.adj[current]):
            if target not in forbidden and target not in parents:
                parents[target] = current, action
                pending.append(target)
    return None


def certify(model, strategy="invest-energy"):
    """Recompute a strategy certificate without trusting authored metadata.

    ``invest-energy`` requires a unique best first action that spends more energy
    than every cheapest legal action. All cheapest ties must admit a complete
    continuation without undoing their decision into a dominated starting state,
    yet take strictly more actions even when unrestricted continuation is allowed.

    ValueError rejects an unknown or unmet strategy. RuntimeError signals a core
    compilation/exploration failure, which a caller must not treat as a rejected
    proposal. Saved strategy certificates should be compared to this return value.
    """
    from .state_planning import compile_model

    if strategy not in STRATEGIES:
        raise ValueError("Unknown planning strategy; choose invest-energy")
    try:
        puzzle = compile_model(model)
    except ValueError as exc:
        raise RuntimeError("Invalid state-planning rules for strategy certification") from exc
    findings = validate(puzzle)
    if findings:
        raise RuntimeError("Invalid compiled strategy model: " + str(findings))
    if any(action.cost != 1 for action in puzzle.actions):
        raise RuntimeError("Strategy certification requires unit-action costs")
    graph = search.explore(puzzle, max_states=MAX_STATES)
    if graph.truncated:
        raise RuntimeError("Strategy reachable-state budget exhausted")
    if (not graph.initial_live or graph.initial not in graph.index
            or set(graph.var_keys) != {"location", "energy", "gate_a", "gate_b", "recharged"}):
        raise RuntimeError("Strategy compiler did not produce the expected live state variables")
    indices = {name: index for index, name in enumerate(graph.var_keys)}
    start = graph.index[graph.initial]
    initial = graph.states[start]
    initial_edges = sorted(graph.adj[start])
    if not initial_edges:
        raise ValueError("The invest-energy strategy needs competing legal first actions")
    if len({action for action, _ in initial_edges}) != len(initial_edges):
        raise RuntimeError("Strategy graph contains ambiguous first-action names")

    def value(state, key):
        return state[indices[key]]

    # Returning with the same gates, no more energy and no more remaining
    # recharge opportunity merely undoes a decision. A gate change or net energy
    # gain may justify a return, and is deliberately retained.
    dominated = {index for index, state in enumerate(graph.states)
                 if all(value(state, key) == value(initial, key)
                        for key in ("location", "gate_a", "gate_b"))
                 and value(state, "energy") <= value(initial, "energy")
                 and value(state, "recharged") >= value(initial, "recharged")}

    def continuation(action, target, forbidden=frozenset()):
        result = _shortest(graph, target, forbidden)
        if result is None:
            return {"best_steps": None, "solution": [], "solution_states": []}
        actions, states = result
        return {"best_steps": len(actions) + 1, "solution": [action, *actions],
                "solution_states": [list(initial), *(list(graph.states[i]) for i in states)]}

    first = {}
    for action, target in initial_edges:
        energy = value(initial, "energy") - value(graph.states[target], "energy")
        if energy < 0:
            raise RuntimeError("Strategy initial actions must spend rather than restore energy")
        first[action] = {"immediate_energy": energy,
                         "unrestricted": continuation(action, target),
                         "committed": continuation(action, target, dominated)}

    costs = {action: row["unrestricted"]["best_steps"] for action, row in first.items()}
    feasible = [cost for cost in costs.values() if cost is not None]
    if not feasible:
        raise ValueError("The invest-energy strategy requires a reachable goal")
    best = min(feasible)
    winners = [action for action, cost in costs.items() if cost == best]
    if len(winners) != 1:
        raise ValueError("The invest-energy strategy requires a unique optimal first action")
    answer = winners[0]
    minimum_energy = min(row["immediate_energy"] for row in first.values())
    cheapest = [action for action, row in first.items()
                if row["immediate_energy"] == minimum_energy]
    if first[answer]["immediate_energy"] <= minimum_energy:
        raise ValueError("The optimal first action must invest more than the minimum energy")
    if any(first[action]["committed"]["best_steps"] is None for action in cheapest):
        raise ValueError("Every cheapest first action must have a successful "
                         "committed continuation")
    if any(costs[action] is None or costs[action] <= best for action in cheapest):
        raise ValueError("Every cheapest first action must require strictly more total actions")
    for row in first.values():
        cost = row["unrestricted"]["best_steps"]
        row["extra_steps"] = None if cost is None else cost - best

    return {
        "version": VERSION, "strategy": strategy,
        "method": "complete-core-ir-graph-and-independent-forward-bfs",
        "scope": "First decision only; total action count with optimal later choices. "
                 "Every minimum-energy legal first action is checked, including all ties.",
        "policy": "Choose any initially legal action with minimum immediate energy expenditure.",
        "committed_scope": "No return with the same location and gates, no more energy, "
                           "and no more remaining recharge opportunity than at the first decision.",
        "optimal_first_action": answer, "best_steps": best,
        "optimal_immediate_energy": first[answer]["immediate_energy"],
        "cheapest_first_actions": cheapest, "minimum_immediate_energy": minimum_energy,
        "minimum_extra_steps": min(first[action]["extra_steps"] for action in cheapest),
        "first_action_results": first, "reachable_states": len(graph.states),
        "state_budget": MAX_STATES,
    }
