"""Measure consequential decision structure without changing physical mechanics.

The signature is the set of *all shortest* compressed decision episodes. A node
records the selected action's semantic role and every committed viable rival's
role, ordinal completion-cost rank, and unrestricted optimality. Edges record
replayed continuation consequences on that same episode. Ordinary travel,
absolute detour lengths, trap counts, path multiplicity, and room labels cannot
by themselves make a new signature. This is a declared behavioral abstraction,
not a complete isomorphism test of the physical state machine.

Dependency depth is the longest directed chain within each complete shortest
episode, then minimized/maximized over episodes. Two disconnected links are not
a three-decision chain. The optional policies have bounded transition lookahead
and a static room-distance frontier; exact solution distances score outcomes
only and are never supplied to a policy.
"""

from __future__ import annotations

from fractions import Fraction
from math import lcm

from ...forge.corpus import compact, digest
from . import planning_causal_paths as causal_paths
from . import planning_experience as experience
from . import state_planning as domain

VERSION = "planning-judgment-v1"
MAX_CONTEXTS = 32_768
POLICY_HORIZONS = (1, 2, 3, 5)
POLICY_STEPS = 36


class JudgmentExhausted(RuntimeError):
    """The exact decision-episode proof exceeded its declared context budget."""


def _action_role(action):
    """Moves share a role: a forced corridor must not invent a new decision."""
    if action == "recharge":
        return "recharge"
    if action.startswith("switch_"):
        return "switch-start" if action == "switch_0" else "switch-away"
    if action.startswith("move_"):
        return "move"
    raise ValueError("Unknown planning action role")


def _node(decision, chosen):
    viable = [row for row in decision["actions"] if row["committed_steps"] is not None]
    ranks = {cost: index for index, cost in enumerate(sorted(
        {row["committed_steps"] for row in viable}
    ))}
    return (_action_role(chosen), tuple(sorted(
        (_action_role(row["action"]), ranks[row["committed_steps"]],
         row["action"] in decision["optimal_actions"])
        for row in viable
    )))


def _shortest_graph(model, graph):
    initial = domain._initial(model)
    goals = {state for state in graph if state[0] == len(model["names"]) - 1}
    remaining = experience._distances(graph, goals)
    if initial not in remaining:
        raise ValueError("Planning judgment requires a reachable goal")
    walked, _ = experience._forward(graph, initial)
    states = {state for state in remaining if state in walked
              and walked[state] + remaining[state] == remaining[initial]}
    optimal = {state: [(action, target) for action, target in graph[state]
                       if target in states and remaining[target] == remaining[state] - 1]
               for state in states}
    return initial, goals & states, remaining, optimal


def _episode_forms(initial, goals, remaining, optimal, decisions, relations, context_budget):
    """Merge only histories with identical retained state/action choices.

    A history excludes nonmeaningful moves, switches, and recharges. The retained
    state/action pairs are necessary to preserve route-specific dependency edges
    through merging DAGs; a union of edges from incompatible routes is unsound.
    """
    contexts = {state: set() for state in optimal}
    contexts[initial].add(())
    forms, checked, scheduled = set(), 0, 1
    for state in sorted(optimal, key=lambda item: (-remaining[item], item)):
        for history in sorted(contexts[state]):
            if checked >= context_budget:
                raise JudgmentExhausted("Decision-episode context budget exhausted")
            checked += 1
            if state in goals:
                nodes = tuple(_node(decisions[earlier], action) for earlier, action in history)
                edges = tuple(sorted((i, j) for j, (later, _) in enumerate(history)
                                     for i, (earlier, chosen) in enumerate(history[:j])
                                     if (earlier, chosen, later) in relations))
                forms.add((nodes, edges))
                continue
            for action, target in optimal[state]:
                following = ((*history, (state, action)) if decisions[state]["meaningful"]
                             else history)
                if following not in contexts[target]:
                    # Bound pending work too, so a wide layer cannot allocate
                    # arbitrarily many contexts before the processing check.
                    if scheduled >= context_budget:
                        raise JudgmentExhausted("Decision-episode context budget exhausted")
                    contexts[target].add(following)
                    scheduled += 1
        contexts[state].clear()
    return sorted(forms, key=compact), checked


def _chain_length(nodes, edges):
    longest = [1] * len(nodes)
    for earlier, later in sorted(edges, key=lambda edge: (edge[1], edge[0])):
        longest[later] = max(longest[later], longest[earlier] + 1)
    return max(longest, default=0)


def _policy_actions(model, graph, horizon):
    """Choose all tied bounded plans; never consult whole-state goal distances.

    A visible terminal completion beats a nonterminal frontier; the shortest
    visible completion wins. Otherwise prefer the smallest static directed-room
    distance at the horizon, then greater remaining energy. Static distances
    ignore energy, gates, switches and recharge. They contain no solved policy.
    """
    room_distance = experience._room_distances(model)
    goal, cache = len(model["names"]) - 1, {}

    def frontier(state, depth):
        key = state, depth
        if key not in cache:
            if state[0] == goal:
                value = (0, 0, 0)
            elif depth == 0 or not graph[state]:
                value = (1, room_distance.get(state[0], len(model["names"]) + 1), -state[1])
            else:
                options = []
                for _, target in graph[state]:
                    score = frontier(target, depth - 1)
                    options.append((0, score[1] + 1, 0) if score[0] == 0 else score)
                value = min(options)
            cache[key] = value
        return cache[key]

    selected = {}
    for state, edges in graph.items():
        scores = [frontier(target, horizon - 1) for _, target in edges]
        best = min(scores, default=None)
        selected[state] = [edge for edge, score in zip(edges, scores, strict=True)
                           if score == best]
    return selected


def evaluate_policies(model, graph, *, horizons=POLICY_HORIZONS, step_budget=POLICY_STEPS,
                      best_steps=None):
    """Exact uniform-tie probabilities within an explicit finite step budget.

    Reaching the goal late is successful but suboptimal. Live probability at the
    budget is reported separately from dead ends and never counted as success.
    Rational strings survive browser JSON round trips without float ambiguity.
    """
    if (not isinstance(horizons, tuple | list) or not horizons
            or any(type(depth) is not int or not 1 <= depth <= 8 for depth in horizons)
            or len(set(horizons)) != len(horizons)):
        raise ValueError("Policy horizons must be distinct integers between one and eight")
    if type(step_budget) is not int or not 0 <= step_budget <= POLICY_STEPS:
        raise ValueError("Invalid policy step budget")
    initial = domain._initial(model)
    if best_steps is None:
        goals = {state for state in graph if state[0] == len(model["names"]) - 1}
        best_steps = experience._distances(graph, goals).get(initial)
    if type(best_steps) is not int or best_steps < 0:
        raise ValueError("Policy measurement requires a reachable goal and shortest length")
    reports = []
    for horizon in horizons:
        selected = _policy_actions(model, graph, horizon)
        # All layer probabilities share a denominator. Integer masses avoid
        # repeated rational normalization at every edge while remaining exact.
        base = lcm(*(len(edges) or 1 for edges in selected.values()))
        denominator = base ** step_budget
        live = {initial: 1}
        success = optimal = dead_end = weighted_steps = 0
        successful_steps, tied_states = set(), set()
        for step in range(step_budget + 1):
            following = {}
            scale = base ** (step_budget - step)
            for state, mass in live.items():
                # All reachable goal states count, not just shortest-DAG goals.
                if state[0] == len(model["names"]) - 1:
                    success += mass * scale
                    weighted_steps += mass * scale * step
                    successful_steps.add(step)
                    if step == best_steps:
                        optimal += mass * scale
                elif not selected[state]:
                    dead_end += mass * scale
                elif step == step_budget:
                    following[state] = following.get(state, 0) + mass
                else:
                    if len(selected[state]) > 1:
                        tied_states.add(state)
                    share = mass * (base // len(selected[state]))
                    for _, target in selected[state]:
                        following[target] = following.get(target, 0) + share
            live = following
        reports.append({
            "policy": f"bounded-lookahead-{horizon}",
            "horizon": horizon,
            "tie_rule": "uniform-over-all-preferred-actions-at-every-step",
            "frontier": "terminal-first-then-static-room-distance-then-remaining-energy",
            "probability_encoding": "exact-rational-string",
            "step_budget": step_budget,
            "success_probability": str(Fraction(success, denominator)),
            "optimal_probability": str(Fraction(optimal, denominator)),
            "dead_end_probability": str(Fraction(dead_end, denominator)),
            "step_limit_probability": str(Fraction(sum(live.values()), denominator)),
            "successful_steps": sorted(successful_steps),
            "mean_successful_steps": str(Fraction(weighted_steps, success)) if success else None,
            "tied_states": len(tied_states),
        })
    return reports


def policy_metrics(model, graph, best_steps=None, *, horizons=POLICY_HORIZONS,
                   step_budget=POLICY_STEPS):
    """Measure a requested horizon subset, reusing a freshly solved best length."""
    return evaluate_policies(model, graph, horizons=horizons, step_budget=step_budget,
                             best_steps=best_steps)


def evaluate(model, graph, quality, *, coverage=None, policy_metrics=False,
             context_budget=MAX_CONTEXTS):
    """Return an exact JSON-stable certificate or raise on bounded exhaustion.

    ``quality`` must be the freshly computed decision analysis of ``graph``.
    ``coverage`` may reuse a freshly computed planning_causal_paths certificate
    for this graph. Its explicit witnessed triples, not its saved acceptance
    flag, establish edges. Final certification must pass a newly compiled graph
    and recomputed analyses; model answers and saved search claims are ignored.
    """
    if type(context_budget) is not int or not 0 <= context_budget <= MAX_CONTEXTS:
        raise ValueError("Invalid decision-episode context budget")
    initial, goals, remaining, optimal = _shortest_graph(model, graph)
    decisions = {tuple(row["state"]): row for row in quality["decisions"]}
    if set(decisions) != set(optimal) - goals:
        raise ValueError("Decision analysis does not match the shortest-route graph")
    if coverage is None:
        coverage = causal_paths.evaluate(model, graph, quality)
    relations = {(tuple(row["earlier_state"]), row["chosen_action"], tuple(row["later_state"]))
                 for row in coverage["witness_relations"]}
    forms, checked = _episode_forms(
        initial, goals, remaining, optimal, decisions, relations, context_budget
    )
    # Dynamic programming counts every action route, including compressed ties.
    routes = {}
    for state in sorted(optimal, key=lambda item: (remaining[item], item)):
        routes[state] = int(state in goals) + sum(routes[target] for _, target in optimal[state])
    lengths = [len(nodes) for nodes, _ in forms]
    chains = [_chain_length(nodes, edges) for nodes, edges in forms]
    roles = min(tuple(node[0] for node in nodes) for nodes, _ in forms)
    return {
        "version": VERSION,
        "signature_scope": "All shortest compressed meaningful-decision forms, viable "
        "alternative roles and ordinal committed costs, and route-specific witnessed edges.",
        "meaningful_scope": "At least two committed goal-reaching actions with unequal costs.",
        "chain_scope": "Number of decisions in the longest directed witnessed chain on each "
        "complete shortest route; then minimum and maximum across those routes.",
        "decision_signature": digest(forms),
        "signature_status": "complete",
        "distinct_decision_episodes": len(forms),
        "meaningful_role_sequence": list(roles),
        "minimum_meaningful_decisions": min(lengths),
        "maximum_meaningful_decisions": max(lengths),
        "minimum_dependency_chain": min(chains),
        "maximum_dependency_chain": max(chains),
        "all_shortest_three_linked_decisions": min(chains) >= 3,
        "chain_status": "complete",
        "shortest_routes": routes[initial],
        "contexts_checked": checked,
        "context_budget": context_budget,
        "policy_checks": evaluate_policies(model, graph, best_steps=remaining[initial])
        if policy_metrics else [],
    }
