"""Bounded graph synthesis with separately checked opening mechanisms.

A finite bank of feasible physical layouts starts a quality-preserving walk over route topology,
resource costs and switch effects. The requested mechanism is selected *before*
that walk and never substituted after solving. Foundations contain physical
rules only, not answers; every foundation and accepted edit is solved afresh.
Labels, interior-node order and gate names are randomized separately.

The certificate uses the compiled complete graph and independent forward BFS.
The ordinary domain checker still supplies transition equivalence, all four
mechanic ablations and SMT proof of the unique optimal first action.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy

from ... import search
from ...forge.corpus import digest
from ...validate import validate
from . import state_planning as domain

VERSION = "state-planning-variety-v1"
CERTIFICATE_VERSION = "state-planning-variety-core-bfs-v1"
PROFILES = ("switch-first", "recharge-first", "remote-switch-first", "conserve-energy")
PROPOSAL_BUDGET = 48


class VarietyExhausted(domain.ProposalExhausted):
    """The selected mechanism was unavailable within its declared budget."""

    def __init__(self, diagnostics):
        self.search = deepcopy(diagnostics)
        super().__init__(
            "The selected state-planning strategy "
            f"{diagnostics['requested_profile']} was unavailable "
            "within its bounded search"
        )


def _path(adj, start, goal, *, forbidden=frozenset(), transition=None, accept=None):
    """Shortest path, optionally in a small product graph for action ordering."""
    if start in forbidden:
        return None
    initial = (start, 0)
    parents, pending = {initial: None}, deque([initial])
    while pending:
        current = pending.popleft()
        state, flag = current
        if state[0] == goal and (accept is None or accept(flag)):
            actions, states = [], [state]
            while parents[current] is not None:
                previous, action = parents[current]
                actions.append(action)
                states.append(previous[0])
                current = previous
            return {
                "steps": len(actions),
                "solution": actions[::-1],
                "solution_states": [list(s) for s in states[::-1]],
            }
        for action, target in sorted(adj[state]):
            if target in forbidden:
                continue
            next_flag = transition(flag, state, action, target) if transition else flag
            node = (target, next_flag)
            if node not in parents:
                parents[node] = current, action
                pending.append(node)
    return None


def _first_results(model, adj):
    initial = (0, model["initial_energy"], *model["initial_gates"], 0)
    goal = len(model["names"]) - 1
    dominated = {
        s
        for s in adj
        if s[0] == initial[0]
        and s[2:4] == initial[2:4]
        and s[1] <= initial[1]
        and s[4] >= initial[4]
    }
    first = {}
    for action, target in sorted(adj[initial]):
        row = {"immediate_energy": initial[1] - target[1]}
        for label, forbidden in (("unrestricted", frozenset()), ("committed", dominated)):
            found = _path(adj, target, goal, forbidden=forbidden)
            row[label] = (
                {"best_steps": None, "solution": [], "solution_states": []}
                if found is None
                else {
                    "best_steps": found["steps"] + 1,
                    "solution": [action, *found["solution"]],
                    "solution_states": [list(initial), *found["solution_states"]],
                }
            )
        first[action] = row
    return first


def _policy_checks(model, first, winner):
    def minimum(actions):
        if not actions:
            return []
        cost = min(first[a]["immediate_energy"] for a in actions)
        return [a for a in actions if first[a]["immediate_energy"] == cost]

    legal = sorted(first)
    moves = [a for a in legal if a.startswith("move_")]
    policies = [
        ("use-start-switch", [a for a in legal if a == "switch_0"]),
        ("move-to-charger", [a for a in legal if a == f"move_0_{model['charger']}"]),
        ("move-immediately", moves),
        ("minimum-immediate-energy", minimum(legal)),
        ("minimum-move-energy", minimum(moves)),
    ]
    rows = []
    for policy, actions in policies:
        verdict = (
            "unavailable"
            if not actions
            else "optimal"
            if actions == [winner]
            else "mixed"
            if winner in actions
            else "suboptimal"
        )
        rows.append(
            {
                "policy": policy,
                "actions": actions,
                "verdict": verdict,
                "first_costs": {a: first[a]["unrestricted"]["best_steps"] for a in actions},
            }
        )
    return rows


def _profile_record(model, adj, energy_adj):
    """Derive the claim from edges, never from saved solution or search metadata."""
    profile = model.get("strategy")
    if model.get("design_version") != VERSION or profile not in PROFILES:
        raise ValueError("Unsupported state-planning variety version or strategy")
    first = _first_results(model, adj)
    viable = [a for a, row in first.items() if row["committed"]["best_steps"] is not None]
    costs = {a: row["unrestricted"]["best_steps"] for a, row in first.items()}
    reachable = [c for c in costs.values() if c is not None]
    if not reachable or len(viable) < 2:
        raise ValueError("A strategy needs at least two committed goal-reaching first actions")
    best = min(reachable)
    winners = [a for a, cost in costs.items() if cost == best]
    if len(winners) != 1:
        raise ValueError("A strategy needs a unique optimal first action")
    winner = winners[0]
    initial = (0, model["initial_energy"], *model["initial_gates"], 0)
    goal = len(model["names"]) - 1
    charger_action = f"move_0_{model['charger']}"
    evidence = {}
    if profile == "switch-first":
        if winner != "switch_0" or not any(a.startswith("move_") for a in viable):
            raise ValueError("switch-first requires the start switch to beat a viable move")
        explanation = (
            "Switching at the start beats every immediate move, "
            "including a move with a complete continuation."
        )
        evidence["committed_move_alternatives"] = [a for a in viable if a.startswith("move_")]
    elif profile == "recharge-first":
        if winner != charger_action:
            raise ValueError("recharge-first requires moving to the charger first")

        def left_uncharged(flag, state, action, target):
            return int(
                bool(
                    flag
                    or (
                        state[0] == model["charger"] and not state[4] and action.startswith("move_")
                    )
                )
            )

        counterexample = _path(adj, initial, goal, transition=left_uncharged, accept=bool)
        if counterexample is not None and counterexample["steps"] <= best:
            raise ValueError("Every optimum must recharge before first leaving the charger")
        explanation = (
            "Reach the charger first. Every shortest plan recharges before leaving it; "
            "a local switch may be used before charging."
        )
        evidence["leaving_charger_before_recharge"] = counterexample
    elif profile == "remote-switch-first":
        if not winner.startswith("move_") or winner == charger_action:
            raise ValueError("remote-switch-first requires a noncharger opening move")
        location = int(winner.split("_")[-1])
        remote = f"switch_{location}"
        if not any(at == location for at, _, _ in model["switches"]):
            raise ValueError("The winning remote room must have a switch")

        def switch_order(flag, state, action, target):
            if flag == 0 and action == remote:
                return 1
            if flag == 0 and action == "recharge":
                return 2
            return flag

        counterexample = _path(
            adj, initial, goal, transition=switch_order, accept=lambda flag: flag != 1
        )
        if counterexample is not None and counterexample["steps"] <= best:
            raise ValueError("Every optimum must use the remote switch before recharging")
        explanation = (
            "Visit the other switch first. Every shortest plan uses "
            "that switch before recharging."
        )
        evidence.update(remote_switch=remote, without_remote_switch_before_recharge=counterexample)
    else:
        if not winner.startswith("move_"):
            raise ValueError("conserve-energy requires a winning move")
        relaxed = _first_results(model, energy_adj)
        relaxed_costs = {a: row["unrestricted"]["best_steps"] for a, row in relaxed.items()}
        relaxed_best = min(c for c in relaxed_costs.values() if c is not None)
        relaxed_winners = sorted(a for a, c in relaxed_costs.items() if c == relaxed_best)
        rivals = [
            a
            for a in viable
            if a.startswith("move_")
            and first[a]["immediate_energy"] > first[winner]["immediate_energy"]
            and a in relaxed_winners
        ]
        if not rivals:
            raise ValueError(
                "Conserving energy must beat a viable costlier move "
                "that becomes optimal without energy limits"
            )
        explanation = (
            "The winning move saves energy against a viable costlier move. "
            "Ignoring energy makes that rival optimal, "
            "so the resource changes the first decision."
        )
        evidence.update(
            higher_energy_committed_rivals=rivals,
            energy_relaxed_best_steps=relaxed_best,
            energy_relaxed_optimal_first_actions=relaxed_winners,
        )

    move_before_switch = False
    if winner.startswith("move_") and "switch_0" in viable:
        destination = int(winner.split("_")[-1])
        gate = next(g for a, b, _, g in model["routes"] if a == 0 and b == destination)
        mask = next(mask for at, mask, _ in model["switches"] if at == 0)
        move_before_switch = gate >= 0 and bool(model["initial_gates"][gate] and mask & (1 << gate))
    for row in first.values():
        cost = row["unrestricted"]["best_steps"]
        row["extra_steps"] = None if cost is None else cost - best
    return {
        "version": CERTIFICATE_VERSION,
        "strategy": profile,
        "method": "complete-core-ir-graph-and-independent-forward-bfs",
        "scope": "First decision with optimal later play; ordering covers every shortest plan.",
        "committed_scope": (
            "No return with unchanged gates, no more energy " "and no more recharge opportunity."
        ),
        "optimal_first_action": winner,
        "best_steps": best,
        "first_action_results": first,
        "evidence": evidence,
        "move_before_start_switch": move_before_switch,
        "explanation": explanation,
        "policy_checks": _policy_checks(model, first, winner),
        "reachable_states": len(adj),
        "state_budget": domain.MAX_STATES,
    }


def _compiled_graph(model, relaxed=None):
    puzzle = domain.compile_model(model, relaxed=relaxed)
    findings = validate(puzzle)
    if findings or any(action.cost != 1 for action in puzzle.actions):
        raise RuntimeError("Invalid unit-action core model for variety certification")
    graph = search.explore(puzzle, max_states=domain.MAX_STATES)
    expected_keys = ("location", "energy", "gate_a", "gate_b", "recharged")
    if graph.truncated or not graph.initial_live or graph.var_keys != expected_keys:
        raise RuntimeError("Incomplete or unexpected core graph for variety certification")
    expected_initial = (0, model["initial_energy"], *model["initial_gates"], 0)
    expected_goals = {
        i for i, state in enumerate(graph.states) if state[0] == len(model["names"]) - 1
    }
    if graph.initial != expected_initial or graph.goals != expected_goals:
        raise RuntimeError("Unexpected core initial state or goals for variety certification")
    return {
        state: sorted((action, graph.states[target]) for action, target in graph.adj[index])
        for index, state in enumerate(graph.states)
    }


def certify(model):
    """Independently recompute a versioned certificate from compiled physical rules."""
    if model.get("design_version") != VERSION or model.get("strategy") not in PROFILES:
        raise ValueError("Unsupported state-planning variety version or strategy")
    return _profile_record(
        model,
        _compiled_graph(model),
        _compiled_graph(model, "energy") if model["strategy"] == "conserve-energy" else None,
    )


# Physical foundations are expanded below. Tuple fields are capacity, initial
# energy, initial gates, charger, directed routes and switch rows. Distinct
# topologies supply starting layouts. No solution or answer is stored here.
_FOUNDATIONS = {
    (1, "switch-first"): [
        (
            8,
            2,
            [0, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 1, -1],
                [0, 3, 4, 0],
                [1, 0, 4, -1],
                [1, 2, 1, -1],
                [1, 3, 3, -1],
                [2, 1, 3, 1],
                [2, 3, 2, 0],
            ],
            [[0, 3, 1], [2, 2, 0]],
        ),
        (
            3,
            3,
            [0, 1],
            1,
            [
                [0, 1, 1, -1],
                [0, 2, 1, -1],
                [0, 3, 4, -1],
                [1, 2, 1, 1],
                [1, 3, 2, 0],
                [2, 0, 1, -1],
                [2, 1, 1, -1],
            ],
            [[0, 1, 1], [2, 1, 1]],
        ),
        (
            4,
            3,
            [1, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 1, -1],
                [0, 3, 3, 1],
                [1, 0, 1, 0],
                [1, 2, 1, -1],
                [1, 3, 3, -1],
                [2, 0, 1, -1],
            ],
            [[0, 2, 1], [1, 3, 0]],
        ),
        (
            7,
            3,
            [1, 0],
            1,
            [
                [0, 1, 1, -1],
                [0, 2, 1, 0],
                [0, 3, 4, -1],
                [1, 2, 2, -1],
                [2, 0, 2, -1],
                [2, 1, 2, -1],
                [2, 3, 1, 1],
            ],
            [[0, 3, 0], [1, 1, 1]],
        ),
    ],
    (1, "recharge-first"): [
        (
            8,
            3,
            [0, 1],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 3, -1],
                [0, 3, 3, 0],
                [1, 2, 2, 1],
                [1, 3, 3, 0],
                [2, 0, 2, 1],
                [2, 1, 1, -1],
            ],
            [[0, 1, 1], [1, 1, 0]],
        ),
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 3, -1],
                [0, 3, 3, 1],
                [1, 0, 3, -1],
                [1, 2, 2, -1],
                [2, 0, 2, 0],
                [2, 1, 1, -1],
            ],
            [[0, 2, 1], [1, 2, 0]],
        ),
        (
            5,
            2,
            [0, 1],
            2,
            [
                [0, 1, 2, -1],
                [0, 2, 1, -1],
                [0, 3, 4, -1],
                [1, 0, 3, -1],
                [1, 2, 1, 1],
                [2, 1, 3, -1],
                [2, 3, 3, 0],
            ],
            [[0, 2, 0], [2, 1, 0]],
        ),
        (
            5,
            4,
            [1, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 1, -1],
                [0, 3, 3, 1],
                [1, 0, 2, -1],
                [1, 2, 1, 0],
                [2, 0, 1, -1],
                [2, 1, 1, -1],
            ],
            [[0, 1, 0], [2, 2, 0]],
        ),
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 3, -1],
                [0, 3, 3, 1],
                [1, 0, 3, -1],
                [1, 2, 2, -1],
                [2, 0, 2, 0],
                [2, 1, 1, -1],
            ],
            [[0, 2, 1]],
        ),
    ],
    (1, "remote-switch-first"): [
        (
            8,
            6,
            [1, 0],
            1,
            [
                [0, 1, 1, -1],
                [0, 2, 1, -1],
                [0, 3, 4, 1],
                [1, 0, 1, 0],
                [1, 2, 2, -1],
                [2, 0, 3, -1],
                [2, 1, 1, -1],
            ],
            [[0, 1, 1], [2, 2, 0]],
        ),
    ],
    (1, "conserve-energy"): [
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 2, 0],
                [0, 2, 1, -1],
                [0, 3, 3, 1],
                [1, 0, 3, -1],
                [1, 2, 1, -1],
                [2, 0, 2, -1],
                [2, 1, 1, -1],
            ],
            [[0, 1, 0], [1, 3, 1]],
        ),
    ],
    (2, "switch-first"): [
        (
            8,
            4,
            [0, 1],
            2,
            [
                [0, 1, 2, 0],
                [0, 2, 2, 1],
                [0, 3, 1, -1],
                [1, 0, 2, 0],
                [1, 2, 2, -1],
                [1, 3, 3, 0],
                [1, 4, 2, -1],
                [2, 0, 1, 1],
                [2, 3, 1, 1],
                [2, 4, 1, 0],
                [3, 0, 3, 0],
                [3, 2, 2, -1],
            ],
            [[0, 3, 1], [2, 2, 0]],
        ),
        (
            8,
            4,
            [1, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 1, -1],
                [0, 3, 3, 1],
                [1, 0, 1, 0],
                [2, 0, 2, -1],
                [2, 1, 2, -1],
                [2, 3, 3, -1],
                [3, 4, 2, 1],
            ],
            [[0, 3, 1], [2, 1, 0]],
        ),
        (
            8,
            3,
            [0, 1],
            2,
            [
                [0, 1, 1, -1],
                [0, 3, 1, 1],
                [0, 4, 4, 1],
                [1, 2, 1, -1],
                [1, 3, 3, -1],
                [2, 0, 3, 0],
                [2, 3, 1, -1],
                [3, 1, 1, -1],
            ],
            [[0, 1, 0], [3, 1, 0]],
        ),
        (
            8,
            4,
            [1, 0],
            1,
            [
                [0, 1, 2, 0],
                [0, 2, 2, 1],
                [0, 3, 1, -1],
                [1, 0, 3, -1],
                [1, 4, 3, 1],
                [2, 3, 1, -1],
                [2, 4, 2, -1],
                [3, 1, 2, -1],
            ],
            [[0, 3, 1], [2, 3, 1]],
        ),
        (
            8,
            5,
            [1, 0],
            2,
            [
                [0, 1, 1, 0],
                [0, 2, 3, -1],
                [0, 3, 3, -1],
                [1, 0, 3, 1],
                [2, 0, 1, -1],
                [2, 3, 1, -1],
                [3, 0, 2, -1],
                [3, 4, 3, 1],
            ],
            [[0, 3, 0], [1, 1, 1]],
        ),
        (
            8,
            3,
            [1, 0],
            3,
            [
                [0, 1, 1, 0],
                [0, 2, 3, -1],
                [0, 3, 2, -1],
                [1, 0, 1, 0],
                [2, 0, 2, 0],
                [2, 3, 1, 0],
                [2, 4, 2, 1],
                [3, 1, 2, -1],
                [3, 2, 3, -1],
            ],
            [[0, 3, 0]],
        ),
    ],
    (2, "recharge-first"): [
        (
            8,
            3,
            [1, 0],
            1,
            [
                [0, 1, 1, -1],
                [0, 2, 3, -1],
                [0, 3, 1, -1],
                [1, 0, 2, -1],
                [1, 2, 3, 0],
                [1, 3, 2, -1],
                [2, 0, 4, 0],
                [2, 4, 3, 1],
                [3, 0, 1, 0],
                [3, 1, 1, 1],
                [3, 4, 2, 1],
            ],
            [[0, 1, 0], [2, 2, 0]],
        ),
        (
            5,
            5,
            [0, 1],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 1, -1],
                [0, 3, 1, 1],
                [1, 3, 1, -1],
                [1, 4, 2, 0],
                [2, 1, 2, -1],
                [2, 3, 1, 1],
                [3, 0, 3, -1],
            ],
            [[0, 2, 1], [2, 3, 1]],
        ),
        (
            8,
            3,
            [0, 1],
            3,
            [
                [0, 2, 1, 1],
                [0, 3, 3, -1],
                [0, 4, 4, -1],
                [1, 3, 3, -1],
                [2, 3, 2, 1],
                [2, 4, 3, -1],
                [3, 0, 2, 0],
                [3, 1, 2, -1],
            ],
            [[0, 2, 0], [3, 1, 1]],
        ),
        (
            8,
            5,
            [1, 0],
            3,
            [
                [0, 1, 2, -1],
                [0, 2, 3, -1],
                [0, 3, 1, 0],
                [1, 3, 1, -1],
                [2, 1, 2, -1],
                [2, 4, 3, 1],
                [3, 0, 1, 0],
                [3, 1, 3, -1],
            ],
            [[0, 3, 0], [2, 2, 0]],
        ),
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 3, -1],
                [0, 4, 3, 1],
                [1, 2, 2, -1],
                [1, 3, 1, -1],
                [2, 0, 2, 0],
                [2, 1, 1, -1],
                [3, 0, 1, -1],
            ],
            [[0, 2, 1]],
        ),
    ],
    (2, "remote-switch-first"): [
        (
            7,
            3,
            [0, 1],
            1,
            [
                [0, 2, 1, -1],
                [0, 3, 1, -1],
                [0, 4, 4, -1],
                [1, 2, 1, -1],
                [1, 4, 3, 0],
                [2, 0, 1, 0],
                [2, 3, 3, 1],
                [3, 1, 2, -1],
            ],
            [[0, 2, 0], [3, 3, 0]],
        ),
        (
            7,
            6,
            [1, 0],
            2,
            [
                [0, 1, 2, 0],
                [0, 3, 1, 0],
                [0, 4, 3, 1],
                [1, 2, 1, -1],
                [1, 3, 1, -1],
                [2, 0, 1, -1],
                [2, 3, 1, -1],
                [3, 1, 3, -1],
            ],
            [[0, 1, 1], [1, 3, 0]],
        ),
    ],
    (2, "conserve-energy"): [
        (
            6,
            3,
            [0, 1],
            3,
            [
                [0, 1, 2, -1],
                [0, 2, 2, 1],
                [0, 3, 1, -1],
                [1, 0, 2, -1],
                [1, 4, 3, -1],
                [2, 3, 1, -1],
                [2, 4, 3, 1],
                [3, 2, 3, 0],
            ],
            [[0, 2, 0], [3, 1, 0]],
        ),
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 2, 0],
                [0, 2, 1, -1],
                [0, 4, 3, 1],
                [1, 2, 1, -1],
                [1, 3, 1, -1],
                [2, 0, 2, -1],
                [2, 1, 1, -1],
                [3, 0, 1, -1],
            ],
            [[0, 1, 0], [1, 3, 1]],
        ),
    ],
    (3, "switch-first"): [
        (
            8,
            3,
            [1, 0],
            1,
            [
                [0, 2, 3, -1],
                [0, 3, 1, 0],
                [0, 4, 2, -1],
                [1, 0, 1, -1],
                [1, 2, 2, -1],
                [2, 4, 1, 0],
                [2, 5, 3, 1],
                [3, 0, 3, -1],
                [3, 1, 2, 0],
                [3, 4, 3, 1],
                [4, 0, 2, -1],
                [4, 1, 3, 0],
            ],
            [[0, 2, 0], [1, 1, 0]],
        ),
        (
            8,
            4,
            [1, 0],
            4,
            [
                [0, 1, 1, -1],
                [0, 3, 3, -1],
                [0, 4, 1, -1],
                [1, 2, 2, 1],
                [2, 4, 2, -1],
                [2, 5, 3, 0],
                [3, 1, 3, -1],
                [4, 0, 1, -1],
                [4, 1, 3, 1],
            ],
            [[0, 2, 0], [2, 2, 0]],
        ),
        (
            7,
            4,
            [0, 1],
            4,
            [
                [0, 1, 2, -1],
                [0, 3, 1, 1],
                [0, 4, 1, -1],
                [1, 3, 3, 1],
                [2, 0, 1, -1],
                [2, 3, 2, -1],
                [3, 0, 1, -1],
                [3, 5, 2, 0],
                [4, 2, 1, -1],
            ],
            [[0, 3, 0], [2, 2, 1]],
        ),
        (
            7,
            3,
            [1, 0],
            1,
            [
                [0, 1, 1, -1],
                [0, 2, 1, 0],
                [0, 5, 4, -1],
                [1, 4, 1, -1],
                [2, 0, 2, -1],
                [2, 1, 2, -1],
                [2, 5, 1, 1],
                [3, 2, 1, -1],
                [4, 3, 1, -1],
            ],
            [[0, 3, 0], [1, 1, 1]],
        ),
    ],
    (3, "recharge-first"): [
        (
            8,
            3,
            [0, 1],
            3,
            [
                [0, 1, 3, 0],
                [0, 2, 1, -1],
                [0, 3, 2, -1],
                [1, 0, 3, -1],
                [1, 3, 3, -1],
                [1, 4, 2, -1],
                [1, 5, 1, 0],
                [2, 0, 1, 1],
                [2, 4, 3, 1],
                [3, 0, 1, 1],
                [3, 2, 3, -1],
                [4, 1, 3, 1],
            ],
            [[0, 3, 0], [2, 2, 0]],
        ),
        (
            7,
            5,
            [1, 0],
            1,
            [
                [0, 1, 1, -1],
                [0, 2, 3, -1],
                [0, 4, 1, 0],
                [1, 0, 1, 0],
                [2, 3, 2, -1],
                [2, 5, 3, 1],
                [3, 0, 1, -1],
                [4, 0, 1, -1],
                [4, 1, 3, -1],
            ],
            [[0, 3, 0], [1, 3, 0]],
        ),
        (
            7,
            4,
            [0, 1],
            4,
            [
                [0, 2, 1, -1],
                [0, 4, 1, -1],
                [0, 5, 3, 0],
                [1, 3, 1, 1],
                [2, 3, 1, 0],
                [3, 0, 1, -1],
                [3, 4, 3, -1],
                [4, 1, 2, -1],
                [4, 3, 3, -1],
            ],
            [[0, 2, 1], [4, 3, 0]],
        ),
        (
            8,
            3,
            [1, 0],
            3,
            [
                [0, 1, 3, -1],
                [0, 2, 2, -1],
                [0, 3, 1, -1],
                [1, 2, 1, -1],
                [2, 5, 3, 1],
                [3, 0, 2, -1],
                [3, 4, 2, -1],
                [4, 0, 1, 0],
                [4, 3, 2, 1],
            ],
            [[0, 1, 1], [2, 3, 0]],
        ),
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 1, -1],
                [0, 2, 3, -1],
                [0, 5, 3, 1],
                [1, 2, 2, -1],
                [1, 3, 1, -1],
                [2, 1, 1, -1],
                [2, 4, 1, 0],
                [3, 0, 1, -1],
                [4, 0, 1, -1],
            ],
            [[0, 2, 1]],
        ),
    ],
    (3, "remote-switch-first"): [
        (
            4,
            2,
            [0, 1],
            2,
            [
                [0, 3, 1, -1],
                [0, 4, 3, -1],
                [0, 5, 3, 0],
                [1, 0, 2, -1],
                [2, 0, 1, -1],
                [2, 4, 2, 1],
                [3, 1, 1, 0],
                [3, 2, 1, -1],
                [4, 3, 2, -1],
            ],
            [[0, 2, 0], [3, 1, 0]],
        ),
        (
            8,
            6,
            [1, 0],
            3,
            [
                [0, 1, 1, 1],
                [0, 2, 3, 1],
                [0, 4, 1, -1],
                [1, 5, 2, -1],
                [2, 4, 2, -1],
                [3, 0, 3, -1],
                [3, 4, 2, 0],
                [4, 2, 3, -1],
                [4, 3, 1, -1],
            ],
            [[0, 1, 0], [4, 3, 1]],
        ),
    ],
    (3, "conserve-energy"): [
        (
            6,
            3,
            [0, 1],
            3,
            [
                [0, 1, 2, -1],
                [0, 2, 2, 1],
                [0, 3, 1, -1],
                [1, 0, 2, -1],
                [1, 5, 3, -1],
                [2, 3, 1, -1],
                [2, 5, 3, 1],
                [3, 4, 1, 0],
                [4, 2, 1, -1],
            ],
            [[0, 2, 0], [3, 1, 0]],
        ),
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 2, 0],
                [0, 2, 1, -1],
                [0, 5, 3, 1],
                [1, 2, 1, -1],
                [1, 4, 1, -1],
                [2, 0, 2, -1],
                [2, 1, 1, -1],
                [3, 0, 1, -1],
                [4, 3, 1, -1],
            ],
            [[0, 1, 0], [1, 3, 1]],
        ),
        (
            8,
            3,
            [1, 0],
            2,
            [
                [0, 1, 2, 0],
                [0, 2, 1, -1],
                [0, 5, 3, 1],
                [1, 2, 1, -1],
                [1, 3, 1, -1],
                [2, 1, 1, -1],
                [2, 4, 1, -1],
                [3, 0, 1, -1],
                [4, 0, 1, -1],
            ],
            [[0, 1, 0], [1, 3, 1]],
        ),
    ],
}


def _foundation(names, level, profile, rng):
    entries = _FOUNDATIONS[(level, profile)]
    # Where both are feasible, sample the charger/switch relationship first.
    # More stored layouts in one role must not turn that visible role into an
    # accidental predictor of the chosen opening mechanism.
    groups = {}
    for i, entry in enumerate(entries):
        at_charger = any(at == entry[3] for at, _, _ in entry[5])
        groups.setdefault(at_charger, []).append(i)
    role = rng.choice(sorted(groups))
    index = rng.choice(groups[role])
    capacity, energy, gates, charger, routes, switches = deepcopy(entries[index])
    model = {
        "version": domain.VERSION,
        "names": list(names),
        "level": level,
        "capacity": capacity,
        "initial_energy": energy,
        "initial_gates": list(gates),
        "charger": charger,
        "routes": [list(row) for row in routes],
        "switches": [list(row) for row in switches],
        "design_version": VERSION,
        "strategy": profile,
    }
    return model, index


def _physical_key(model):
    return digest(
        {
            key: model[key]
            for key in (
                "capacity",
                "initial_energy",
                "initial_gates",
                "charger",
                "routes",
                "switches",
            )
        }
    )


def _mutate(model, rng):
    """One or two local edits; graph validation and solving decide acceptance."""
    changed = deepcopy(model)
    n = len(model["names"])
    for _ in range(1 + int(rng.randrange(4) == 0)):
        edit = rng.randrange(12)
        if edit == 0:
            rng.choice(changed["routes"])[2] = rng.randint(1, 4)
        elif edit == 1:
            rng.choice(changed["routes"])[3] = rng.choice((-1, 0, 1))
        elif edit == 2:
            changed["capacity"] = rng.randint(max(3, changed["initial_energy"]), 8)
        elif edit == 3:
            changed["initial_energy"] = rng.randint(1, changed["capacity"])
        elif edit == 4:
            switch = rng.choice(changed["switches"])
            switch[1], switch[2] = rng.randint(1, 3), rng.randrange(2)
        elif edit == 5:
            gate = rng.randrange(2)
            changed["initial_gates"][gate] ^= 1
        elif edit == 6 and len(changed["routes"]) < 12:
            links = {(a, b) for a, b, _, _ in changed["routes"]}
            available = [
                (a, b) for a in range(1, n - 1) for b in range(n) if a != b and (a, b) not in links
            ]
            if available:
                a, b = rng.choice(available)
                changed["routes"].append([a, b, rng.randint(1, 4), rng.choice((-1, 0, 1))])
        elif edit == 7 and len(changed["routes"]) > n:
            removable = [row for row in changed["routes"] if row[0] != 0]
            changed["routes"].remove(rng.choice(removable))
        elif edit == 8:
            row = rng.choice(changed["routes"])
            row[1] = rng.choice([b for b in range(n) if b != row[0]])
        elif edit == 9:
            changed["charger"] = rng.randrange(1, n - 1)
        elif edit == 10:
            if len(changed["switches"]) > 1:
                changed["switches"][1][0] = rng.randrange(1, n - 1)
        else:
            if len(changed["switches"]) > 1:
                changed["switches"].pop()
            else:
                changed["switches"].append(
                    [rng.randrange(1, n - 1), rng.randint(1, 3), rng.randrange(2)]
                )
    changed["routes"].sort()
    return changed


def _assess(model):
    try:
        domain._validate(model)
    except ValueError:
        return None, "shape", 0
    adj = domain._graph(model)
    result = domain._analyse_graph(model, adj)
    steps = result["best_steps"]
    if steps is None or not domain.MIN_STEPS[model["level"] - 1] <= steps <= domain.MAX_STEPS:
        return None, "length", 1
    if (
        len(result["optimal_first_actions"]) != 1
        or sum(c is not None for c in result["committed_first_costs"].values()) < 2
        or max(result["later_committed_choices"], default=0) < 2
        or result["reachable_locations"] != len(model["names"])
    ):
        return None, "choices", 1
    variants = {mechanic: domain._graph(model, mechanic) for mechanic in domain.MECHANICS}
    ablations = {key: domain._analyse_graph(model, graph) for key, graph in variants.items()}
    if any(
        domain._ablation_signature(row) == domain._ablation_signature(result)
        for row in ablations.values()
    ):
        return None, "mechanics", 5
    try:
        _profile_record(model, adj, variants["energy"])
    except ValueError:
        return None, "profile", 5
    return result, None, 5


def _relabel(model, rng):
    n = len(model["names"])
    interior = list(range(1, n - 1))
    rng.shuffle(interior)
    mapping = dict(zip(range(n), (0, *interior, n - 1), strict=True))
    swap = bool(rng.randrange(2))
    model["charger"] = mapping[model["charger"]]
    model["routes"] = sorted(
        [mapping[a], mapping[b], cost, 1 - gate if swap and gate >= 0 else gate]
        for a, b, cost, gate in model["routes"]
    )
    model["switches"] = sorted(
        [mapping[at], ((mask & 1) << 1) | ((mask >> 1) & 1) if swap else mask, cost]
        for at, mask, cost in model["switches"]
    )
    if swap:
        model["initial_gates"].reverse()


def propose(names, level, rng, *, requested_profile=None, budget=PROPOSAL_BUDGET):
    """Select a mechanism before solving; refine only within that mechanism."""
    domain._validate_names(names)
    if type(level) is not int or level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("State planning requires level+3 location names")
    if requested_profile is not None and requested_profile not in PROFILES:
        raise ValueError("Unknown state-planning variety profile")
    if type(budget) is not int or not 0 <= budget <= PROPOSAL_BUDGET:
        raise ValueError("Invalid state-planning variety budget")
    profile = requested_profile if requested_profile is not None else rng.choice(PROFILES)
    diagnostics = {
        "version": VERSION,
        "mode": "bounded-quality-preserving-graph-edits",
        "requested_profile": profile,
        "profile_selection": "explicit" if requested_profile else "uniform-before-synthesis",
        "budget": budget,
        "model_evaluations": 0,
        "graph_evaluations": 0,
        "core_graph_evaluations": 0,
        "accepted_edits": 0,
        "topology_edits": 0,
        "rejections": dict.fromkeys(
            ("shape", "length", "choices", "mechanics", "profile", "duplicate"), 0
        ),
    }
    if budget == 0:
        raise VarietyExhausted(diagnostics)
    model, foundation = _foundation(names, level, profile, rng)
    diagnostics["foundation"] = foundation
    result, reason, graphs = _assess(model)
    diagnostics["model_evaluations"] += 1
    diagnostics["graph_evaluations"] += graphs
    if reason is not None:
        diagnostics["rejections"][reason] += 1
        raise VarietyExhausted(diagnostics)
    seen = {_physical_key(model)}
    for _ in range(1, budget):
        candidate = _mutate(model, rng)
        key = _physical_key(candidate)
        diagnostics["model_evaluations"] += 1
        if key in seen:
            diagnostics["rejections"]["duplicate"] += 1
            continue
        seen.add(key)
        assessment, reason, graphs = _assess(candidate)
        diagnostics["graph_evaluations"] += graphs
        if reason is not None:
            diagnostics["rejections"][reason] += 1
            continue
        diagnostics["accepted_edits"] += 1
        diagnostics["topology_edits"] += int(
            {(a, b) for a, b, _, _ in candidate["routes"]}
            != {(a, b) for a, b, _, _ in model["routes"]}
        )
        model, result = candidate, assessment
    _relabel(model, rng)
    # Relabeling can change the lexical tie-break among later optimal plans.
    result = domain.solve(model)
    diagnostics["graph_evaluations"] += 1
    certificate = certify(model)
    diagnostics["core_graph_evaluations"] = 2 if profile == "conserve-energy" else 1
    diagnostics["graph_evaluations"] += diagnostics["core_graph_evaluations"]
    if (
        certificate["optimal_first_action"] != result["optimal_first_actions"][0]
        or certificate["best_steps"] != result["best_steps"]
    ):
        raise RuntimeError("Domain and independent strategy graph disagree")
    options = [f"move_0_{b}" for a, b, _, _ in model["routes"] if a == 0] + ["switch_0"]
    rng.shuffle(options)
    model.update(
        options=options,
        answer_action=result["optimal_first_actions"][0],
        best_steps=result["best_steps"],
        solution=result["solution"],
        search=diagnostics,
    )
    return model
