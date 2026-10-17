"""Challenge compressed decisions, route-specific chains, and bounded policies."""

from __future__ import annotations

import json
import random
from copy import deepcopy
from fractions import Fraction
from itertools import permutations
from random import Random

import pytest
from tools.benchmark_state_planning import committed_costs, domain_graph, initial, shortest

from spie.forge.corpus import compact, digest
from spie.questions.brainbloom import planning_causal_paths as causal_paths
from spie.questions.brainbloom import planning_experience as experience
from spie.questions.brainbloom import planning_judgment as judgment
from spie.questions.brainbloom import state_planning as domain


def example():
    """Frozen revision13 development-seed103 case with four shortest routes."""
    return {
        "version": domain.VERSION, "names": list("ABCD"), "level": 1,
        "capacity": 8, "initial_energy": 3, "initial_gates": [1, 0], "charger": 2,
        "routes": [[0, 1, 1, -1], [0, 2, 3, -1], [0, 3, 3, 1], [1, 0, 3, 1],
                   [1, 2, 2, 0], [1, 3, 3, 1], [2, 0, 2, 0], [2, 1, 1, -1]],
        "switches": [[0, 1, 1], [2, 2, 0]],
    }


def production(model, **kwargs):
    graph = domain._graph(model)
    quality = experience._evaluate_graph(model, graph, policies=False)
    return judgment.evaluate(model, graph, quality, **kwargs), graph, quality


def raw_decision_forms(model):
    """Full raw-rule route/rival enumeration, independent of production analysis."""
    graph = domain_graph(model)
    remaining = {state: shortest(model, graph, state)[0] for state in graph}
    costs = {state: committed_costs(model, graph, state) for state in graph}
    best_actions = {state: {action for action, target in edges.items()
                           if remaining[state] is not None and remaining[target] is not None
                           and remaining[target] + 1 == remaining[state]}
                    for state, edges in graph.items()}
    meaningful = {state for state, rows in costs.items()
                  if len({cost for cost in rows.values() if cost is not None}) >= 2}
    route_cache = {}

    def routes(start, avoid=frozenset()):
        key = start, avoid
        if key not in route_cache:
            distance = {state: shortest(model, graph, state, avoid)[0] for state in graph}
            found = []

            def visit(state, actions, states):
                if distance[state] is None:
                    return
                if distance[state] == 0:
                    found.append((actions, states))
                else:
                    for action, target in graph[state].items():
                        if target not in avoid and distance[target] == distance[state] - 1:
                            visit(target, [*actions, action], [*states, target])

            visit(start, [], [start])
            route_cache[key] = found
        return route_cache[key]

    def role(action):
        return ("recharge" if action == "recharge" else "switch-start"
                if action == "switch_0" else "switch-away"
                if action.startswith("switch_") else "move")

    all_routes = routes(initial(model))
    forms, chains = set(), []
    for actions, states in all_routes:
        history = [(state, actions[i]) for i, state in enumerate(states[:-1])
                   if state in meaningful]
        nodes, edges = [], []
        for earlier, chosen in history:
            levels = sorted({cost for cost in costs[earlier].values() if cost is not None})
            nodes.append((role(chosen), tuple(sorted(
                (role(action), levels.index(cost), action in best_actions[earlier])
                for action, cost in costs[earlier].items() if cost is not None
            ))))
        for i, (earlier, chosen) in enumerate(history):
            avoid = frozenset(state for state in graph if state[0] == earlier[0]
                              and state[2:4] == earlier[2:4] and state[1] <= earlier[1]
                              and state[4] >= earlier[4])
            for j in range(i + 1, len(history)):
                later = history[j][0]
                if any(
                    other != later and other[0] == later[0]
                    and best_actions[other] != best_actions[later]
                    for alternative, rival in graph[earlier].items() if alternative != chosen
                    for _, rival_states in routes(rival, avoid) for other in rival_states
                ):
                    edges.append((i, j))
        forms.add((tuple(nodes), tuple(sorted(edges))))

        def walk(index, edges=edges):
            return 1 + max((walk(j) for i, j in edges if i == index), default=0)

        chains.append(max((walk(i) for i in range(len(nodes))), default=0))
    return sorted(forms, key=compact), chains, len(all_routes)


def relabel(model, rooms, gates):
    changed = deepcopy(model)
    changed["names"] = [f"Place {i}" for i in range(len(rooms))]
    changed["charger"] = rooms[model["charger"]]
    changed["initial_gates"] = [model["initial_gates"][gates.index(g)] for g in range(2)]
    changed["routes"] = sorted([rooms[a], rooms[b], cost, gates[g] if g >= 0 else -1]
                               for a, b, cost, g in model["routes"])
    changed["switches"] = sorted([rooms[at], sum(1 << gates[g] for g in range(2)
                                               if mask & (1 << g)), cost]
                                 for at, mask, cost in model["switches"])
    return changed


def test_matches_independently_enumerated_routes_decisions_and_causal_chains():
    model = example()
    report, _, _ = production(model)
    forms, chains, route_count = raw_decision_forms(model)
    assert report["decision_signature"] == digest(forms)
    assert report["minimum_dependency_chain"] == min(chains)
    assert report["maximum_dependency_chain"] == max(chains)
    assert report["minimum_meaningful_decisions"] == min(len(nodes) for nodes, _ in forms)
    assert report["maximum_meaningful_decisions"] == max(len(nodes) for nodes, _ in forms)
    assert report["shortest_routes"] == route_count == 4
    assert not report["all_shortest_three_linked_decisions"]
    assert report == json.loads(json.dumps(report))


def test_room_gate_and_edge_relabeling_preserve_complete_judgment_and_policies():
    model = example()
    original, _, _ = production(model, policy_metrics=True)
    for interior in permutations((1, 2)):
        for gates in permutations((0, 1)):
            changed = relabel(model, (0, *interior, 3), gates)
            changed["routes"].reverse()
            changed["switches"].reverse()
            report, _, _ = production(changed, policy_metrics=True)
            assert report == original


def test_reuses_fresh_coverage_and_ignores_saved_route_and_acceptance_claims(monkeypatch):
    model = example()
    expected, graph, quality = production(model)
    coverage = causal_paths.evaluate(model, graph, quality)
    coverage["all_shortest_routes_linked"] = True
    coverage["shortest_routes"] = 999
    quality["solution"] = model["solution"] = ["invented"]
    quality["dimensions"] = model["experience_search"] = {"invented": True}
    before = random.getstate()

    def forbidden(*args, **kwargs):
        raise AssertionError("Existing freshly computed coverage was recomputed")

    monkeypatch.setattr(causal_paths, "evaluate", forbidden)
    assert judgment.evaluate(model, graph, quality, coverage=coverage) == expected
    assert random.getstate() == before


def travel_example():
    # Minimal raw-rule DAG rather than an accepted generator shape. The start
    # has a two-step and three-step viable completion, then only forced travel.
    return {
        "names": list("ABCDE"), "capacity": 6, "initial_energy": 6,
        "initial_gates": [0, 0], "charger": 3, "switches": [],
        "routes": [[0, 1, 1, -1], [0, 2, 1, -1], [1, 4, 1, -1],
                   [2, 3, 1, -1], [3, 4, 1, -1]],
    }


def test_common_forced_travel_does_not_invent_decision_variety():
    model = travel_example()
    before, _, before_quality = production(model)
    changed = deepcopy(model)
    changed["names"].append("F")
    changed["routes"].append([4, 5, 1, -1])
    after, _, after_quality = production(changed)
    assert before["decision_signature"] == after["decision_signature"]
    assert before["meaningful_role_sequence"] == after["meaningful_role_sequence"] == ["move"]
    assert after_quality["dimensions"]["solution_steps"] == (
        before_quality["dimensions"]["solution_steps"] + 1
    )
    assert after_quality["dimensions"]["maximum_forced_steps"] == (
        before_quality["dimensions"]["maximum_forced_steps"] + 1
    )


def test_extra_viable_alternative_changes_the_signature():
    model = travel_example()
    before, _, _ = production(model)
    changed = deepcopy(model)
    changed["routes"].append([0, 3, 1, -1])
    after, _, _ = production(changed)
    assert after["decision_signature"] != before["decision_signature"]
    assert after["minimum_meaningful_decisions"] == before["minimum_meaningful_decisions"] == 1


def test_disconnected_dependency_pairs_are_not_a_three_decision_chain():
    nodes = ("a", "b", "c", "d")
    assert judgment._chain_length(nodes, ((0, 1), (2, 3))) == 2
    assert judgment._chain_length(nodes, ((0, 1), (1, 3), (2, 3))) == 3


def test_context_merges_match_exhaustive_route_specific_chain_forms():
    # Development seeds only. Every layer merges; all same-role decisions hide
    # physical state labels, while witnessed edges depend on the selected route.
    for seed in range(1401, 1421):
        rng = Random(seed)
        layers = [[(0, 0)], *[[(depth, side) for side in range(2)] for depth in range(1, 5)],
                  [(5, 0)]]
        graph = {state: [(f"move_{depth}_{side}", target)
                         for side, target in enumerate(layers[depth + 1])]
                 if depth < 5 else []
                 for depth, layer in enumerate(layers) for state in layer}
        decisions = {state: {"meaningful": depth % 2 == 0, "optimal_actions": [a for a, _ in edges],
                             "actions": [{"action": a, "committed_steps": i + 1}
                                         for i, (a, _) in enumerate(edges)]}
                     for depth, layer in enumerate(layers[:-1]) for state in layer
                     for edges in [graph[state]]}
        relations = {(earlier, action, later) for earlier, edges in graph.items()
                     for action, _ in edges for later in graph
                     if earlier[0] < later[0] and rng.randrange(4) == 0}
        remaining = {state: 5 - state[0] for state in graph}
        actual, _ = judgment._episode_forms(
            layers[0][0], set(layers[-1]), remaining, graph, decisions, relations,
            judgment.MAX_CONTEXTS,
        )
        expected = set()

        def visit(state, history, graph=graph, decisions=decisions,
                  relations=relations, expected=expected):
            if not graph[state]:
                nodes = tuple(judgment._node(decisions[s], a) for s, a in history)
                edges = tuple(sorted((i, j) for j, (later, _) in enumerate(history)
                                     for i, (earlier, action) in enumerate(history[:j])
                                     if (earlier, action, later) in relations))
                expected.add((nodes, edges))
            for action, target in graph[state]:
                visit(target, [*history, (state, action)]
                      if decisions[state]["meaningful"] else history)

        visit(layers[0][0], [])
        assert actual == sorted(expected, key=compact)


def test_bounded_exhaustion_cannot_produce_a_passing_certificate():
    with pytest.raises(judgment.JudgmentExhausted, match="budget exhausted"):
        production(example(), context_budget=0)
    with pytest.raises(judgment.JudgmentExhausted, match="budget exhausted"):
        production(example(), context_budget=2)
    with pytest.raises(ValueError, match="context budget"):
        production(example(), context_budget=True)


def test_successful_detour_is_not_misreported_as_optimal():
    model = travel_example()
    model["charger"] = 0  # No recharge is available on either simple branch.
    # A closed shortcut makes both first rooms equally near in the static map.
    model["routes"].append([2, 4, 1, 0])
    graph = domain._graph(model)
    reports = judgment.policy_metrics(model, graph, 2, horizons=(1, 2, 5))
    shallow, deeper, deepest = reports
    assert shallow["success_probability"] == "1"
    assert shallow["optimal_probability"] == "1/2"
    assert shallow["successful_steps"] == [2, 3]
    assert deeper["success_probability"] == deeper["optimal_probability"] == "1"
    assert deepest["success_probability"] == deepest["optimal_probability"] == "1"
    limited = judgment.policy_metrics(model, graph, 2, horizons=(1,), step_budget=1)[0]
    assert limited["success_probability"] == limited["optimal_probability"] == "0"
    assert limited["step_limit_probability"] == "1"
    for row in [*reports, limited]:
        assert sum(Fraction(row[field]) for field in (
            "success_probability", "dead_end_probability", "step_limit_probability"
        )) == 1


def test_policy_actions_do_not_read_whole_state_solver_or_quality(monkeypatch):
    model = travel_example()
    graph = domain._graph(model)

    def forbidden(*args, **kwargs):
        raise AssertionError("A bounded policy called the whole-state solver")

    monkeypatch.setattr(domain, "solve", forbidden)
    monkeypatch.setattr(domain, "_analyse_graph", forbidden)
    monkeypatch.setattr(judgment, "_shortest_graph", forbidden)
    monkeypatch.setattr(experience, "_evaluate_graph", forbidden)
    assert judgment.policy_metrics(model, graph, 2, horizons=(1, 3))


@pytest.mark.parametrize("horizons", [(), (True,), (0,), (9,), (2, 2)])
def test_invalid_policy_horizons_are_rejected(horizons):
    model = travel_example()
    with pytest.raises(ValueError, match="Policy horizons"):
        judgment.policy_metrics(model, domain._graph(model), 2, horizons=horizons)
