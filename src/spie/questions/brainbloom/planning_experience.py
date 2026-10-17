"""Bounded design comparison for complete, fully observable planning episodes.

The target is structural, not a claim about enjoyment: every shortest episode has
two consequential committed decisions, and a witnessed earlier choice changes the
best continuation at a later decision. Physical/profile/ablation gates are never
traded for this target. Policies are diagnostics, not an adversarial objective.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from fractions import Fraction

from . import state_planning as domain
from . import state_planning_variety as variety

VERSION = "planning-experience-v1"
CERTIFICATE_VERSION = "planning-experience-core-bfs-v1"
PROPOSAL_BUDGET = 48
POLICY_STEPS = 36
TARGET = {"minimum_meaningful_decisions": 2, "minimum_causal_links": 1}
RANK_DIMENSIONS = (
    "meaningful_decisions_capped_at_2",
    "causal_links_capped_at_1",
    "negative_trap_choices_on_optimal_episodes",
    "negative_maximum_forced_steps",
    "negative_rule_rows",
    "negative_solution_steps",
)
POLICIES = (
    "minimum-immediate-energy",
    "minimum-move-energy",
    "nearest-goal-room",
    "charge-then-nearest-room",
    "switch-then-nearest-room",
    "horizon-1",
    "horizon-2",
    "horizon-3",
)


class ExperienceExhausted(domain.ProposalExhausted):
    """The chosen profile did not satisfy the unchanged target within budget."""

    def __init__(self, diagnostics):
        self.search = deepcopy(diagnostics)
        super().__init__(
            f"Planning experience {diagnostics['requested_profile']} did not meet "
            "its declared decision target within the bounded search"
        )


def _distances(adj, goals, forbidden=frozenset()):
    reverse = {state: [] for state in adj if state not in forbidden}
    for source in reverse:
        for _, target in adj[source]:
            if target in reverse:
                reverse[target].append(source)
    distance = dict.fromkeys(sorted(set(goals) & reverse.keys()), 0)
    pending = deque(distance)
    while pending:
        state = pending.popleft()
        for previous in reverse[state]:
            if previous not in distance:
                distance[previous] = distance[state] + 1
                pending.append(previous)
    return distance


def _forward(adj, start, forbidden=frozenset()):
    if start in forbidden:
        return {}, {}
    distances, parents, pending = {start: 0}, {start: None}, deque([start])
    while pending:
        state = pending.popleft()
        for action, target in adj[state]:
            if target not in forbidden and target not in distances:
                distances[target] = distances[state] + 1
                parents[target] = state, action
                pending.append(target)
    return distances, parents


def _prefix(parents, target):
    actions, states = [], [target]
    while parents[target] is not None:
        target, action = parents[target]
        actions.append(action)
        states.append(target)
    return actions[::-1], states[::-1]


def _suffix(adj, state, distances):
    actions, states = [], [state]
    while distances[state]:
        action, target = min(
            (action, target)
            for action, target in adj[state]
            if distances.get(target) == distances[state] - 1
        )
        actions.append(action)
        states.append(target)
        state = target
    return actions, states


def _dominated(adj, start):
    return frozenset(
        state
        for state in adj
        if state[0] == start[0]
        and state[2:4] == start[2:4]
        and state[1] <= start[1]
        and state[4] >= start[4]
    )


def _decision(adj, state, goals, distances):
    committed = _distances(adj, goals, _dominated(adj, state))
    rows = []
    for action, target in adj[state]:
        solution, states = _suffix(adj, target, committed) if target in committed else ([], [])
        rows.append(
            {
                "action": action,
                "next_state": list(target),
                "best_steps": 1 + distances[target] if target in distances else None,
                "committed_steps": 1 + committed[target] if target in committed else None,
                "committed_solution": [action, *solution] if target in committed else [],
                "committed_states": [list(state), *map(list, states)] if states else [],
            }
        )
    costs = [row["committed_steps"] for row in rows if row["committed_steps"] is not None]
    return {
        "state": list(state),
        "best_remaining": distances.get(state),
        "optimal_actions": [
            row["action"]
            for row in rows
            if row["best_steps"] is not None and row["best_steps"] == distances.get(state)
        ],
        "committed_actions": [row["action"] for row in rows if row["committed_steps"] is not None],
        "meaningful": len(costs) >= 2 and len(set(costs)) >= 2,
        "trap_choices": sum(row["best_steps"] is None for row in rows),
        "forced": sum(row["best_steps"] is not None for row in rows) == 1,
        "actions": rows,
    }


def _causal_links(adj, optimal, decisions, goals, distances):
    """Compare reachable branches; never manufacture a counterfactual state.

    The rival state lies on a shortest *committed* completion of the rival first
    action. Both witnesses start at the earlier decision. Different optimal
    actions at the same later room establish a continuation consequence, not
    merely a difference in state vectors or a longer detour.
    """
    links, witnessed = [], set()
    meaningful = {state for state, row in decisions.items() if row["meaningful"]}
    for earlier in sorted(meaningful):
        forbidden = _dominated(adj, earlier)
        committed = _distances(adj, goals, forbidden)
        for chosen, target in optimal[earlier]:
            reachable, parents = _forward(optimal, target)
            later_points = meaningful & reachable.keys()
            for alternative, rival in adj[earlier]:
                if alternative == chosen or rival not in committed:
                    continue
                rival_distances, rival_parents = _forward(adj, rival, forbidden)
                for later in sorted(later_points):
                    if (earlier, later) in witnessed:
                        continue
                    candidates = [
                        state
                        for state, walked in rival_distances.items()
                        if state != later
                        and state[0] == later[0]
                        and state in committed
                        and walked + committed[state] == committed[rival]
                    ]
                    for counterpart in sorted(candidates):
                        counterpart_actions = sorted(
                            action
                            for action, nxt in adj[counterpart]
                            if distances.get(nxt) == distances[counterpart] - 1
                        )
                        if counterpart_actions == decisions[later]["optimal_actions"]:
                            continue
                        actual_actions, actual_states = _prefix(parents, later)
                        other_actions, other_states = _prefix(rival_parents, counterpart)
                        actual_end, actual_end_states = _suffix(adj, later, distances)
                        other_end, other_end_states = _suffix(adj, counterpart, committed)
                        links.append(
                            {
                                "earlier_state": list(earlier),
                                "later_state": list(later),
                                "alternative_later_state": list(counterpart),
                                "chosen_action": chosen,
                                "alternative_action": alternative,
                                "chosen_prefix": [chosen, *actual_actions],
                                "chosen_prefix_states": [list(earlier), *map(list, actual_states)],
                                "alternative_prefix": [alternative, *other_actions],
                                "alternative_prefix_states": [
                                    list(earlier),
                                    *map(list, other_states),
                                ],
                                "chosen_completion": actual_end,
                                "chosen_completion_states": list(map(list, actual_end_states)),
                                "alternative_completion": other_end,
                                "alternative_completion_states": list(map(list, other_end_states)),
                                "changed_fields": [
                                    key
                                    for index, key in enumerate(
                                        ("location", "energy", "gate_a", "gate_b", "recharged")
                                    )
                                    if later[index] != counterpart[index]
                                ],
                                "later_optimal_actions": decisions[later]["optimal_actions"],
                                "alternative_later_optimal_actions": counterpart_actions,
                            }
                        )
                        witnessed.add((earlier, later))
                        # One replayable counterexample suffices for this ordered pair.
                        break
    return links


def _room_distances(model):
    graph = {room: [] for room in range(len(model["names"]))}
    for origin, destination, _, _ in model["routes"]:
        graph[origin].append(("route", destination))
    return _distances(graph, {len(model["names"]) - 1})


def _policy_actions(model, adj, policy):
    room_distance = _room_distances(model)
    goal = len(model["names"]) - 1
    horizon_cache = {}

    def frontier(state, depth):
        key = state, depth
        if key in horizon_cache:
            return horizon_cache[key]
        if state[0] == goal:
            value = (0, 0, 0)
        elif depth == 0 or not adj[state]:
            value = (1, room_distance.get(state[0], 999), -state[1])
        else:
            value = min(frontier(target, depth - 1) for _, target in adj[state])
        horizon_cache[key] = value
        return value

    selected = {}
    for state, edges in adj.items():
        if not edges:
            selected[state] = []
            continue
        choices = edges
        if policy == "minimum-move-energy":
            choices = [edge for edge in edges if edge[0].startswith("move_")] or edges
        elif policy == "charge-then-nearest-room":
            choices = [edge for edge in edges if edge[0] == "recharge"] or edges
        elif policy == "switch-then-nearest-room":
            choices = [edge for edge in edges if edge[0].startswith("switch_")] or edges
        if policy.startswith("horizon-"):
            scores = [frontier(target, int(policy[-1]) - 1) for _, target in choices]
        elif policy in ("minimum-immediate-energy", "minimum-move-energy"):
            scores = [state[1] - target[1] for _, target in choices]
        else:
            scores = [room_distance.get(target[0], 999) for _, target in choices]
        best = min(scores)
        selected[state] = [
            edge for edge, score in zip(choices, scores, strict=True) if score == best
        ]
    return selected


def _policies(model, adj, initial, best):
    """Exact tie probabilities, serialized as browser-stable rational strings.

    JSON numbers such as 0.0 become integers after JSON.stringify, breaking the
    strict saved-proof comparison. Rational strings also avoid silently rounding
    away tiny but possible outcomes within the bounded policy simulation.
    """
    goal, reports = len(model["names"]) - 1, []
    for policy in POLICIES:
        selected = _policy_actions(model, adj, policy)
        live = {initial: Fraction(1)}
        success = optimal = deadend = weighted_steps = Fraction(0)
        successful_steps, tied_states = set(), set()
        for step in range(POLICY_STEPS + 1):
            following = {}
            for state, probability in live.items():
                if state[0] == goal:
                    success += probability
                    weighted_steps += probability * step
                    successful_steps.add(step)
                    if step == best:
                        optimal += probability
                elif not selected[state]:
                    deadend += probability
                elif step == POLICY_STEPS:
                    following[state] = following.get(state, 0) + probability
                else:
                    actions = selected[state]
                    if len(actions) > 1:
                        tied_states.add(state)
                    for _, target in actions:
                        following[target] = following.get(target, 0) + probability / len(actions)
            live = following
        state, actions, states = initial, [], [list(initial)]
        for _ in range(POLICY_STEPS):
            if state[0] == goal or not selected[state]:
                break
            action, state = selected[state][0]
            actions.append(action)
            states.append(list(state))
        reports.append(
            {
                "policy": policy,
                "tie_rule": "uniform-over-all-preferred-actions-at-every-step",
                "probability_encoding": "exact-rational-string",
                "step_budget": POLICY_STEPS,
                "success_probability": str(success),
                "optimal_probability": str(optimal),
                "dead_end_probability": str(deadend),
                "step_limit_probability": str(sum(live.values())),
                "successful_steps": sorted(successful_steps),
                "mean_successful_steps": str(weighted_steps / success) if success else None,
                "tied_states": len(tied_states),
                "example_actions": actions,
                "example_states": states,
            }
        )
    return reports


def _evaluate_graph(model, adj, *, policies=True):
    initial = (0, model["initial_energy"], *model["initial_gates"], 0)
    goals = {state for state in adj if state[0] == len(model["names"]) - 1}
    distances = _distances(adj, goals)
    if initial not in distances:
        raise ValueError("A planning experience needs a reachable goal")
    forward, _ = _forward(adj, initial)
    best = distances[initial]
    optimal_states = {state for state in distances if forward[state] + distances[state] == best}
    optimal = {
        state: [
            (action, target)
            for action, target in adj[state]
            if target in optimal_states and distances.get(target) == distances[state] - 1
        ]
        for state in optimal_states
    }
    decisions = {
        state: _decision(adj, state, goals, distances)
        for state in optimal_states
        if state not in goals
    }
    minima, maxima, forced = {}, {}, {}
    for state in sorted(optimal_states, key=lambda item: distances[item]):
        if state in goals:
            minima[state] = maxima[state] = forced[state] = 0
        else:
            meaningful = int(decisions[state]["meaningful"])
            minima[state] = meaningful + min(minima[target] for _, target in optimal[state])
            maxima[state] = meaningful + max(maxima[target] for _, target in optimal[state])
            forced[state] = int(decisions[state]["forced"]) + max(
                forced[target] for _, target in optimal[state]
            )
    links = _causal_links(adj, optimal, decisions, goals, distances)
    pairs = {(tuple(row["earlier_state"]), tuple(row["later_state"])) for row in links}
    solution, states = _suffix(adj, initial, distances)
    dimensions = {
        "minimum_meaningful_decisions": minima[initial],
        "maximum_meaningful_decisions": maxima[initial],
        "meaningful_states": sum(row["meaningful"] for row in decisions.values()),
        "causal_links": len(pairs),
        "trap_choices_on_optimal_episodes": sum(row["trap_choices"] for row in decisions.values()),
        "maximum_forced_steps": forced[initial],
        "rule_rows": len(model["routes"]) + len(model["switches"]) + 1,
        "solution_steps": best,
        "reachable_states": len(adj),
        "dead_end_states": len(adj) - len(distances),
    }
    rank = [
        min(dimensions["minimum_meaningful_decisions"], 2),
        min(dimensions["causal_links"], 1),
        -dimensions["trap_choices_on_optimal_episodes"],
        -dimensions["maximum_forced_steps"],
        -dimensions["rule_rows"],
        -best,
    ]
    return {
        "version": CERTIFICATE_VERSION,
        "method": "complete-graph-forward-and-reverse-bfs-with-replayed-branch-witnesses",
        "scope": (
            "Decision minima cover all shortest episodes; causal links give explicit branches."
        ),
        "meaningful_scope": "Two committed goal-reaching actions with unequal complete costs.",
        "commitment_scope": (
            "No return to the decision room with unchanged gates and no resource gain."
        ),
        "human_experience": "Unmeasured; humor, emotional interest and enjoyment need paired play.",
        "target": dict(TARGET),
        "meets_target": (
            minima[initial] >= TARGET["minimum_meaningful_decisions"]
            and len(pairs) >= TARGET["minimum_causal_links"]
        ),
        "dimensions": dimensions,
        "rank_dimensions": list(RANK_DIMENSIONS),
        "rank": rank,
        "solution": solution,
        "solution_states": list(map(list, states)),
        "decisions": [decisions[state] for state in sorted(decisions)],
        "causal_links": links,
        "policy_checks": _policies(model, adj, initial, best) if policies else [],
    }


def evaluate(model):
    """Measure either a baseline or a new model using independently compiled rules."""
    return _evaluate_graph(model, variety._compiled_graph(model))


def certify(model):
    """Recompute every structural claim; saved answers/search/quality are not evidence."""
    if model.get("experience_version") != VERSION:
        raise ValueError("Unsupported planning experience version")
    graph = variety._compiled_graph(model)
    variants = {mechanic: variety._compiled_graph(model, mechanic) for mechanic in domain.MECHANICS}
    profile = variety._profile_record(model, graph, variants["energy"])
    certificate = _evaluate_graph(model, graph)
    best = certificate["dimensions"]["solution_steps"]
    initial = (0, model["initial_energy"], *model["initial_gates"], 0)
    initial_decision = next(
        row for row in certificate["decisions"] if row["state"] == list(initial)
    )
    if (
        not domain.MIN_STEPS[model["level"] - 1] <= best <= domain.MAX_STEPS
        or len(initial_decision["optimal_actions"]) != 1
        or len(initial_decision["committed_actions"]) < 2
        or not any(
            len(row["committed_actions"]) >= 2
            for row in certificate["decisions"]
            if row["state"] != list(initial)
        )
        or len({state[0] for state in graph}) != len(model["names"])
    ):
        raise ValueError("Planning experience does not preserve physical and decision gates")
    ablations = {}
    for mechanic, variant in variants.items():
        distances = _distances(variant, {s for s in variant if s[0] == len(model["names"]) - 1})
        variant_best = distances.get(initial)
        winners = [
            action
            for action, target in variant[initial]
            if target in distances and distances[target] + 1 == variant_best
        ]
        if (variant_best, winners) == (best, initial_decision["optimal_actions"]):
            raise ValueError(f"The {mechanic} ablation must change the answer or optimum")
        ablations[mechanic] = {"best_steps": variant_best, "optimal_first_actions": winners}
    if not certificate["meets_target"]:
        raise ValueError("Planning experience does not meet the declared episode decision target")
    certificate.update(strategy=profile["strategy"], ablations=ablations, core_graphs=5)
    return certificate


def _foundation_at(template, index):
    fields = ("capacity", "initial_energy", "initial_gates", "charger", "routes", "switches")
    values = variety._FOUNDATIONS[(template["level"], template["strategy"])][index]
    return {**deepcopy(template), **dict(zip(fields, deepcopy(values), strict=True))}


def propose(names, level, rng, *, requested_profile=None, budget=PROPOSAL_BUDGET):
    """Compare bounded physical revisions, retaining the best eligible candidate."""
    domain._validate_names(names)
    if type(level) is not int or level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("State planning requires level+3 location names")
    if requested_profile is not None and requested_profile not in variety.PROFILES:
        raise ValueError("Unknown state-planning variety profile")
    if type(budget) is not int or not 0 <= budget <= PROPOSAL_BUDGET:
        raise ValueError("Invalid planning experience budget")
    profile = requested_profile if requested_profile is not None else rng.choice(variety.PROFILES)
    diagnostics = {
        "version": VERSION,
        "mode": "bounded-compare-and-revise-best-retained",
        "requested_profile": profile,
        "profile_selection": (
            "explicit" if requested_profile is not None else "uniform-before-synthesis"
        ),
        "budget": budget,
        "model_evaluations": 0,
        "graph_evaluations": 0,
        "accepted_edits": 0,
        "best_updates": 0,
        "target": dict(TARGET),
        "rank_dimensions": list(RANK_DIMENSIONS),
        "rejections": dict.fromkeys(
            (
                "shape",
                "length",
                "choices",
                "mechanics",
                "profile",
                "duplicate",
                "experience",
                "not_better",
            ),
            0,
        ),
        "comparisons": [],
    }
    if budget == 0:
        raise ExperienceExhausted(diagnostics)
    current, foundation = variety._foundation(names, level, profile, rng)
    diagnostics["foundation"] = foundation
    template = deepcopy(current)
    other_foundations = list(range(len(variety._FOUNDATIONS[(level, profile)])))
    other_foundations.remove(foundation)
    rng.shuffle(other_foundations)
    foundations = [foundation, *other_foundations]
    diagnostics["foundation_order"] = foundations
    best_model = best_quality = None
    seen = set()
    for attempt in range(budget):
        is_foundation = attempt < len(foundations)
        if is_foundation:
            candidate = _foundation_at(template, foundations[attempt])
        else:
            parent = best_model if best_model is not None and rng.randrange(3) == 0 else current
            candidate = variety._mutate(parent, rng)
        diagnostics["model_evaluations"] += 1
        key = variety._physical_key(candidate)
        if key in seen:
            diagnostics["rejections"]["duplicate"] += 1
            continue
        seen.add(key)
        _, reason, graphs = variety._assess(candidate)
        diagnostics["graph_evaluations"] += graphs
        if reason:
            diagnostics["rejections"][reason] += 1
            continue
        quality = _evaluate_graph(candidate, domain._graph(candidate), policies=False)
        diagnostics["graph_evaluations"] += 1
        if not is_foundation:
            diagnostics["accepted_edits"] += 1
        # Explore a quality-preserving physical walk, but never confuse the last
        # feasible edit with the retained best experience.
        current = candidate
        improvement = best_quality is None or quality["rank"] > best_quality["rank"]
        diagnostics["comparisons"].append(
            {
                "attempt": attempt + 1,
                "origin": "foundation" if is_foundation else "revision",
                "physical_key": key,
                "dimensions": quality["dimensions"],
                "rank": quality["rank"],
                "meets_target": quality["meets_target"],
                "retained": improvement,
            }
        )
        if not quality["meets_target"]:
            diagnostics["rejections"]["experience"] += 1
        if improvement:
            best_model, best_quality = deepcopy(candidate), quality
            diagnostics["best_updates"] += 1
            diagnostics["selected_attempt"] = attempt + 1
        else:
            diagnostics["rejections"]["not_better"] += 1
    if best_model is None or not best_quality["meets_target"]:
        diagnostics["best_dimensions"] = best_quality["dimensions"] if best_quality else None
        raise ExperienceExhausted(diagnostics)
    variety._relabel(best_model, rng)
    best_model["experience_version"] = VERSION
    result = domain.solve(best_model)
    certificate = certify(best_model)
    if certificate["rank"] != best_quality["rank"]:
        raise RuntimeError("Experience quality changed under mechanical relabeling")
    if certificate["solution"] != result["solution"]:
        raise RuntimeError("Experience compiler and physical solver disagree")
    options = [f"move_0_{b}" for a, b, _, _ in best_model["routes"] if a == 0] + ["switch_0"]
    rng.shuffle(options)
    diagnostics.update(
        core_graph_evaluations=5,
        graph_evaluations=diagnostics["graph_evaluations"] + 6,
        best_dimensions=certificate["dimensions"],
        best_rank=certificate["rank"],
        selected_physical_key=variety._physical_key(best_model),
    )
    best_model.update(
        options=options,
        answer_action=result["optimal_first_actions"][0],
        best_steps=result["best_steps"],
        solution=result["solution"],
        experience_search=diagnostics,
    )
    return best_model
