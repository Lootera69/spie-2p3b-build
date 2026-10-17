"""Check causal coverage of every shortest route, independently of room labels.

An earlier *chosen action* can support a link to a later meaningful state. Its
rival must have a shortest committed completion through the same later room in
a changed state with a different unrestricted optimal-action set. All such
rival continuations are considered, not a label-selected sample path.
"""

from __future__ import annotations

from . import planning_experience as experience
from . import state_planning as domain

VERSION = "planning-causal-paths-v1"
MAX_CONTEXTS = 32_768


class CausalCoverageExhausted(RuntimeError):
    """Coverage remains unknown after the explicit context budget is exhausted."""


def _relations(graph, optimal, goals, distances, bits, future):
    optimal_actions = {
        state: frozenset(action for action, target in edges
                         if state in distances and distances.get(target) == distances[state] - 1)
        for state, edges in graph.items()
    }
    supported, witnesses = {}, []
    for earlier in sorted(bits):
        forbidden = experience._dominated(graph, earlier)
        committed = experience._distances(graph, goals, forbidden)
        for alternative, rival in graph[earlier]:
            if rival not in committed:
                continue
            walked, _ = experience._forward(graph, rival, forbidden)
            counterparts = {}
            for state in sorted(walked):
                if state in committed and walked[state] + committed[state] == committed[rival]:
                    counterparts.setdefault(state[0], []).append(state)
            for chosen, target in optimal[earlier]:
                if chosen == alternative:
                    continue
                key = earlier, chosen
                for later in sorted(bits):
                    if not future[target] & bits[later] or supported.get(key, 0) & bits[later]:
                        continue
                    counterpart = next((state for state in counterparts.get(later[0], ())
                                        if state != later and
                                        optimal_actions[state] != optimal_actions[later]), None)
                    if counterpart is None:
                        continue
                    supported[key] = supported.get(key, 0) | bits[later]
                    witnesses.append({
                        "earlier_state": list(earlier), "chosen_action": chosen,
                        "later_state": list(later), "alternative_action": alternative,
                        "alternative_later_state": list(counterpart),
                    })
    return supported, witnesses


def _uncovered(initial, goals, optimal, bits, future, supported, context_budget):
    """Search only paths still lacking a link; subset contexts dominate supersets.

    A mask names later states which would complete a link from an action already
    taken. A smaller mask is harder to cover: if it cannot reach a goal uncovered,
    neither can a superset at the same state. Masks retain only future states.
    """
    contexts = {state: {} for state in optimal}
    contexts[initial][0] = ((), (initial,))
    checked = 0
    # The graph is a shortest-route DAG. Every edge decreases this distance.
    order = experience._distances(optimal, goals)
    for state in sorted(optimal, key=lambda node: (-order[node], node)):
        for mask, (actions, states) in list(contexts[state].items()):
            if checked >= context_budget:
                raise CausalCoverageExhausted(
                    "All-shortest causal coverage context budget exhausted"
                )
            checked += 1
            if state in goals:
                return {"actions": list(actions), "states": list(map(list, states))}, checked
            for action, target in optimal[state]:
                coverage = mask | supported.get((state, action), 0)
                if coverage & bits.get(target, 0):
                    continue
                coverage &= future[target]
                existing = contexts[target]
                if any(previous & coverage == previous for previous in existing):
                    continue
                for previous in list(existing):
                    if coverage & previous == coverage:
                        del existing[previous]
                existing[coverage] = (*actions, action), (*states, target)
    return None, checked


def evaluate(model, graph, quality, *, context_budget=MAX_CONTEXTS):
    """Return exact coverage or raise on exhaustion; never assume missing evidence.

    ``quality`` is the whole-graph decision analysis for this exact graph. Final
    certification must supply a freshly compiled graph and recomputed quality.
    The budget limits processed uncovered path contexts, not successful routes.
    """
    if type(context_budget) is not int or not 0 <= context_budget <= MAX_CONTEXTS:
        raise ValueError("Invalid all-shortest causal coverage context budget")
    initial = domain._initial(model)
    goals = {state for state in graph if state[0] == len(model["names"]) - 1}
    distances = experience._distances(graph, goals)
    if initial not in distances:
        raise ValueError("Causal coverage requires a reachable goal")
    forward, _ = experience._forward(graph, initial)
    states = {state for state in distances
              if forward[state] + distances[state] == distances[initial]}
    optimal = {state: [(action, target) for action, target in graph[state]
                       if target in states and distances[target] == distances[state] - 1]
               for state in states}
    meaningful = {tuple(row["state"]) for row in quality["decisions"] if row["meaningful"]}
    bits = {state: 1 << index for index, state in enumerate(sorted(meaningful))}
    future, route_counts = {}, {}
    for state in sorted(states, key=lambda node: (distances[node], node)):
        future[state] = bits.get(state, 0)
        route_counts[state] = int(state in goals)
        for _, target in optimal[state]:
            future[state] |= future[target]
            route_counts[state] += route_counts[target]
    supported, witnesses = _relations(graph, optimal, goals, distances, bits, future)
    counterexample, contexts = _uncovered(
        initial, goals, optimal, bits, future, supported, context_budget
    )
    return {
        "version": VERSION,
        "scope": "Every shortest route contains a witnessed optimal-action-change link "
        "between two meaningful decisions; all shortest committed rival branches are considered.",
        "all_shortest_routes_linked": counterexample is None,
        "shortest_routes": route_counts[initial],
        "witness_relations": witnesses,
        "unlinked_route": counterexample,
        "contexts_checked": contexts,
        "context_budget": context_budget,
    }
