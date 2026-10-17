"""Independent exhaustive paths challenge the invariant causal-coverage DP."""

from __future__ import annotations

from copy import deepcopy
from itertools import permutations
from random import Random

import pytest
from tools.benchmark_state_planning import committed_costs, domain_graph, initial, shortest

from spie.questions.brainbloom import planning_causal_paths as causal
from spie.questions.brainbloom import planning_experience as experience
from spie.questions.brainbloom import state_planning as domain


def example(index):
    """Frozen physical rules from development seeds 101, 103 and 104 only."""
    charger, routes, switches = (
        (1, [[0, 1, 1, -1], [0, 2, 1, -1], [0, 3, 4, -1], [1, 2, 1, 0],
             [1, 3, 2, 1], [2, 0, 1, 0], [2, 1, 1, 0]], [[0, 2, 1], [2, 2, 1]]),
        (2, [[0, 1, 1, -1], [0, 2, 3, -1], [0, 3, 3, 1], [1, 0, 3, 1],
             [1, 2, 2, 0], [1, 3, 3, 1], [2, 0, 2, 0], [2, 1, 1, -1]],
         [[0, 1, 1], [2, 2, 0]]),
        (1, [[0, 1, 3, -1], [0, 2, 1, -1], [0, 3, 3, 1], [1, 0, 2, 1],
             [1, 2, 1, -1], [2, 1, 1, 0], [2, 3, 3, 1]], [[0, 2, 1], [1, 2, 0]]),
    )[index]
    return {
        "version": domain.VERSION, "names": list("ABCD"), "level": 1,
        "capacity": 8, "initial_energy": 3, "initial_gates": [1, 0],
        "charger": charger, "routes": deepcopy(routes), "switches": deepcopy(switches),
    }


def production(model, **kwargs):
    graph = domain._graph(model)
    quality = experience._evaluate_graph(model, graph, policies=False)
    return causal.evaluate(model, graph, quality, **kwargs), quality


def independent(model):
    """Enumerate full routes and rival continuations using only raw-rule BFS."""
    graph = domain_graph(model)
    remaining = {state: shortest(model, graph, state)[0] for state in graph}
    optimal = {state: {action for action, target in edges.items()
                       if remaining[state] is not None and remaining[target] is not None
                       and remaining[target] + 1 == remaining[state]}
               for state, edges in graph.items()}
    meaningful = set()
    for state in graph:
        viable = [cost for cost in committed_costs(model, graph, state).values()
                  if cost is not None]
        if len(viable) >= 2 and len(set(viable)) >= 2:
            meaningful.add(state)
    cache = {}

    def routes(start, avoid=frozenset()):
        key = start, frozenset(avoid)
        if key in cache:
            return cache[key]
        costs = {state: shortest(model, graph, state, avoid)[0] for state in graph}
        found = []

        def visit(state, actions, states):
            if costs[state] is None:
                return
            if costs[state] == 0:
                found.append((actions, states))
                return
            for action, target in graph[state].items():
                if target not in avoid and costs[target] == costs[state] - 1:
                    visit(target, [*actions, action], [*states, target])

        visit(start, [], [start])
        cache[key] = found
        return found

    def counterparts(earlier, alternative):
        avoid = {state for state in graph if state[0] == earlier[0]
                 and state[2:4] == earlier[2:4] and state[1] <= earlier[1]
                 and state[4] >= earlier[4]}
        return {state for _, states in routes(graph[earlier][alternative], avoid)
                for state in states[:-1]}

    def relation(earlier, chosen, later, alternative=None, other=None):
        if earlier not in meaningful or later not in meaningful:
            return False
        alternatives = [alternative] if alternative else graph[earlier]
        return any(action != chosen and any(
            state != later and state[0] == later[0] and optimal[state] != optimal[later]
            and (other is None or state == other)
            for state in counterparts(earlier, action)
        ) for action in alternatives)

    main_routes = routes(initial(model))
    covered = []
    for actions, states in main_routes:
        covered.append(any(relation(earlier, actions[i], later)
                           for i, earlier in enumerate(states[:-1]) for later in states[i + 1:-1]))
    return main_routes, covered, relation


@pytest.mark.parametrize("index,expected", [(0, True), (1, False), (2, True)])
def test_matches_every_independently_enumerated_route_and_rival_branch(index, expected):
    model = example(index)
    report, _ = production(model)
    routes, flags, relation = independent(model)
    assert report["all_shortest_routes_linked"] == all(flags) == expected
    assert report["shortest_routes"] == len(routes)
    for witness in report["witness_relations"]:
        earlier, later = tuple(witness["earlier_state"]), tuple(witness["later_state"])
        chosen = witness["chosen_action"]
        assert any(earlier in states[:-1] and later in states[states.index(earlier) + 1:]
                   and actions[states.index(earlier)] == chosen for actions, states in routes)
        assert relation(earlier, chosen, later, witness["alternative_action"],
                        tuple(witness["alternative_later_state"]))
    if expected:
        assert report["unlinked_route"] is None
    else:
        counterexample = report["unlinked_route"]
        index = next(i for i, (actions, _) in enumerate(routes)
                     if actions == counterexample["actions"])
        assert not flags[index]
        assert counterexample["states"] == [list(state) for state in routes[index][1]]


def test_old_dag_link_gate_is_insufficient_for_every_shortest_route():
    report, quality = production(example(1))
    assert quality["meets_target"]
    assert quality["dimensions"]["causal_links"] == 2
    assert report["shortest_routes"] == 4
    assert not report["all_shortest_routes_linked"]


def relabel(model, rooms, gates):
    changed = deepcopy(model)
    changed["names"] = ["Room " + str(index) for index in range(len(rooms))]
    changed["charger"] = rooms[model["charger"]]
    changed["initial_gates"] = [model["initial_gates"][gates.index(g)] for g in range(2)]
    changed["routes"] = sorted([rooms[a], rooms[b], cost, gates[gate] if gate >= 0 else -1]
                               for a, b, cost, gate in model["routes"])
    changed["switches"] = sorted([rooms[at], sum(1 << gates[g] for g in range(2)
                                               if mask & (1 << g)), cost]
                                 for at, mask, cost in model["switches"])
    return changed


@pytest.mark.parametrize("index", [0, 1, 2])
def test_interior_room_and_gate_relabeling_cannot_change_acceptance(index):
    model = example(index)
    original, _ = production(model)
    for interior in permutations((1, 2)):
        for gates in permutations((0, 1)):
            report, _ = production(relabel(model, (0, *interior, 3), gates))
            assert report["all_shortest_routes_linked"] == original["all_shortest_routes_linked"]
            assert report["shortest_routes"] == original["shortest_routes"]
            assert len(report["witness_relations"]) == len(original["witness_relations"])


def test_bounded_coverage_exhaustion_never_claims_the_gate_passed():
    with pytest.raises(causal.CausalCoverageExhausted, match="budget exhausted"):
        production(example(0), context_budget=0)
    with pytest.raises(ValueError, match="context budget"):
        production(example(0), context_budget=True)


def test_coverage_uses_meaningful_actions_and_ignores_saved_link_and_route_claims():
    model = example(0)
    expected, quality = production(model)
    quality["causal_links"] = []
    quality["solution"] = ["teleport"]
    quality["solution_states"] = []
    model["solution"] = ["teleport"]
    assert causal.evaluate(model, domain._graph(model), quality) == expected
    for row in quality["decisions"]:
        row["meaningful"] = False
    report = causal.evaluate(model, domain._graph(model), quality)
    assert not report["all_shortest_routes_linked"]
    assert report["witness_relations"] == []


def test_subset_context_pruning_matches_exhaustive_paths_through_merging_dags():
    # All branches merge repeatedly; random future promises create incomparable,
    # subset and superset contexts. Plain sets plus full path enumeration are the oracle.
    for seed in range(101, 121):
        rng = Random(seed)
        layers = [[(0, 0)], *[[(depth, side) for side in range(2)] for depth in range(1, 6)]]
        graph = {state: [(f"go_{side}", target) for side, target in enumerate(layers[depth + 1])]
                 if depth + 1 < len(layers) else []
                 for depth, layer in enumerate(layers) for state in layer}
        bits = {state: 1 << i for i, state in enumerate(graph)}
        future = {}
        for layer in reversed(layers):
            for state in layer:
                reachable = {state}
                for _, target in graph[state]:
                    reachable |= future[target]
                future[state] = reachable
        promises = {(state, action): {later for later in future[target] if rng.randrange(4) == 0}
                    for state, edges in graph.items() for action, target in edges}
        flags = []

        def visit(state, promised, covered, graph, promises, flags):
            if not graph[state]:
                flags.append(covered)
            for action, target in graph[state]:
                following = promised | promises[state, action]
                visit(target, following, covered or target in following, graph, promises, flags)

        visit(layers[0][0], set(), False, graph, promises, flags)
        witness, _ = causal._uncovered(
            layers[0][0], set(layers[-1]), graph, bits,
            {state: sum(bits[later] for later in reachable) for state, reachable in future.items()},
            {key: sum(bits[later] for later in choices) for key, choices in promises.items()},
            causal.MAX_CONTEXTS,
        )
        assert (witness is None) == all(flags)
