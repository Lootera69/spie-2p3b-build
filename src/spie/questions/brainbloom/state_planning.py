"""Invent small interacting energy, gate, switch and recharge state machines.

The domain interpreter and core-IR interpreter independently enumerate the whole
reachable graph. SMT separately proves the shortest length and optimal first
actions. All actions take one step; energy is a resource, never the objective.
"""

from __future__ import annotations

from collections import deque
from itertools import permutations

from ...forge.corpus import digest

VERSION = "state-planning-v1"
MAX_STATES = 512
MAX_STEPS = 12
MIN_STEPS = (4, 5, 6)
PROPOSAL_BUDGET = 2_000
SMT_RESOURCE_LIMIT = 2_000_000
MECHANICS = ("energy", "gates", "switches", "recharge")


class ProposalExhausted(RuntimeError):
    """The bounded proposal search found no model satisfying all quality gates."""


def _validate_names(names):
    if (not isinstance(names, list | tuple) or not 4 <= len(names) <= 6
            or any(not isinstance(name, str) or not name.strip() or len(name) > 50
                   or name != name.strip() or any(char in name for char in "\r\n\t")
                   for name in names)
            or len({name.casefold() for name in names}) != len(names)):
        raise ValueError("Use four to six distinct single-line location names without edge spaces")


def _validate(model):
    if not isinstance(model, dict):
        raise ValueError("A state-planning model must be an object")
    names = model.get("names")
    _validate_names(names)
    if not isinstance(names, list):
        raise ValueError("Model location names must be a list")
    n = len(names)
    if type(model.get("level")) is not int or model["level"] != n - 3:
        raise ValueError("State-planning level must match its location count")
    if model.get("version") != VERSION:
        raise ValueError("Unsupported state-planning model version")
    for field, low, high in (("capacity", 3, 8), ("initial_energy", 1, 8),
                             ("charger", 1, n - 2)):
        if type(model.get(field)) is not int or not low <= model[field] <= high:
            raise ValueError(f"Invalid state-planning {field}")
    if model["initial_energy"] > model["capacity"]:
        raise ValueError("Initial energy exceeds capacity")
    gates = model.get("initial_gates")
    if (not isinstance(gates, list) or len(gates) != 2
            or any(type(g) is not int or g not in (0, 1) for g in gates)):
        raise ValueError("Give both gates an initial open (1) or closed (0) setting")
    routes = model.get("routes")
    if (not isinstance(routes, list) or not n <= len(routes) <= 12
            or any(not isinstance(r, list) or len(r) != 4
                   or any(type(value) is not int for value in r) for r in routes)):
        raise ValueError("Routes must be [origin, destination, energy, gate] rows")
    if (any(not 0 <= a < n - 1 or not 0 <= b < n or a == b
            or not 1 <= cost <= 4 or gate not in (-1, 0, 1) for a, b, cost, gate in routes)
            or len({(a, b) for a, b, _, _ in routes}) != len(routes)
            or sum(a == 0 for a, _, _, _ in routes) != 3
            or not {0, 1} <= {gate for _, _, _, gate in routes}):
        raise ValueError("Use distinct directed routes, three from the start, and both gates")
    switches = model.get("switches")
    if (not isinstance(switches, list) or not 1 <= len(switches) <= 2
            or any(not isinstance(s, list) or len(s) != 3
                   or any(type(value) is not int for value in s) for s in switches)):
        raise ValueError("Switches must be [location, gate mask, energy] rows")
    if (any(not 0 <= at < n - 1 or mask not in (1, 2, 3) or cost not in (0, 1)
            for at, mask, cost in switches)
            or len({at for at, _, _ in switches}) != len(switches)
            or not any(at == 0 for at, _, _ in switches)):
        raise ValueError("Use one switch per location, including a switch at the start")


def _initial(model):
    return (0, model["initial_energy"], *model["initial_gates"], 0)


def _successors(model, state, relaxed=None):
    """Direct domain semantics, without AST evaluation or compiler calls."""
    at, energy, gate_a, gate_b, used = state
    if at == len(model["names"]) - 1:
        return []
    result = []
    for origin, destination, cost, gate in model["routes"]:
        if origin != at:
            continue
        if relaxed != "energy" and energy < cost:
            continue
        if relaxed != "gates" and gate != -1 and (gate_a, gate_b)[gate] == 0:
            continue
        result.append((f"move_{origin}_{destination}",
                       (destination, energy if relaxed == "energy" else energy - cost,
                        gate_a, gate_b, used)))
    if relaxed != "switches":
        for location, mask, cost in model["switches"]:
            if location == at and (relaxed == "energy" or energy >= cost):
                result.append((f"switch_{location}",
                               (at, energy if relaxed == "energy" else energy - cost,
                                gate_a ^ (mask & 1), gate_b ^ ((mask >> 1) & 1), used)))
    if (relaxed != "recharge" and at == model["charger"] and not used
            and energy < model["capacity"]):
        result.append(("recharge", (at, model["capacity"], gate_a, gate_b, 1)))
    return sorted(result)


def _graph(model, relaxed=None):
    initial = _initial(model)
    adj, queue = {initial: []}, deque([initial])
    while queue:
        state = queue.popleft()
        adj[state] = _successors(model, state, relaxed)
        for _, nxt in adj[state]:
            if nxt not in adj:
                if len(adj) >= MAX_STATES:
                    raise RuntimeError("State-planning reachable-state budget exhausted")
                adj[nxt] = []
                queue.append(nxt)
    return adj


def _analyse_graph(model, adj, *, committed=True, initial=None):
    initial = _initial(model) if initial is None else initial
    goals = {s for s in adj if s[0] == len(model["names"]) - 1}
    reverse = {s: [] for s in adj}
    for state, successors in adj.items():
        for _, nxt in successors:
            reverse[nxt].append(state)
    distances, queue = dict.fromkeys(sorted(goals), 0), deque(sorted(goals))
    while queue:
        state = queue.popleft()
        for previous in reverse[state]:
            if previous not in distances:
                distances[previous] = distances[state] + 1
                queue.append(previous)
    first = {action: (1 + distances[nxt] if nxt in distances else None)
             for action, nxt in adj[initial]}
    best = distances.get(initial)
    winners = sorted(action for action, cost in first.items() if cost == best and cost is not None)
    trace, states, current = [], [initial], initial
    if best is not None:
        while distances[current]:
            action, nxt = min((a, s) for a, s in adj[current]
                              if distances.get(s) == distances[current] - 1)
            trace.append(action)
            states.append(nxt)
            current = nxt
    result = {"best_steps": best, "first_costs": first, "optimal_first_actions": winners,
            "solution": trace, "solution_states": [list(s) for s in states],
            "reachable_states": len(adj), "dead_end_states": len(adj) - len(distances),
            "branching_states": sum(len(successors) > 1 for successors in adj.values()),
            "reachable_locations": len({s[0] for s in adj}),
            "later_branching_steps": sum(len(adj[s]) > 1 for s in states[1:-1])}
    if committed:
        def committed_costs(start):
            def dominated(s):
                return (s[0] == start[0] and s[2:4] == start[2:4]
                        and s[1] <= start[1] and s[4] >= start[4])

            # Undoing a decision with no gate change and no net energy gain is
            # dominated, including wasting the single recharge on the way back.
            forward = {s: [(a, nxt) for a, nxt in edges if not dominated(nxt)]
                       for s, edges in adj.items() if s == start or not dominated(s)}
            return _analyse_graph(model, forward, committed=False, initial=start)["first_costs"]

        result["committed_first_costs"] = committed_costs(initial)
        result["later_committed_choices"] = [sum(c is not None for c in committed_costs(s).values())
                                              for s in states[1:-1]]
    return result


def solve(model, *, relaxed=None):
    _validate(model)
    if relaxed not in (None, *MECHANICS):
        raise ValueError("Unknown mechanic relaxation")
    return _analyse_graph(model, _graph(model, relaxed))


def compile_model(model, *, relaxed=None):
    """Compile independently to the existing guarded-action core IR."""
    from ...expr import And, Assign, Const, Eq, Le, Lt, Not, Sub, Var
    from ...ir import Action, Kind, Objective, Puzzle, Variable

    _validate(model)
    if relaxed not in (None, *MECHANICS):
        raise ValueError("Unknown mechanic relaxation")
    n = len(model["names"])
    variables = (Variable("location", Kind.LOC), Variable("energy", Kind.INT, 0, model["capacity"]),
                 Variable("gate_a", Kind.BOOL), Variable("gate_b", Kind.BOOL),
                 Variable("recharged", Kind.BOOL))
    initial = dict(zip((v.key for v in variables), _initial(model), strict=True))
    actions = []

    def guards(at, cost):
        terms = [Eq(Var("location"), Const(at))]
        if relaxed != "energy":
            terms.append(Le(Const(cost), Var("energy")))
        return terms

    def spending(cost):
        return ([] if relaxed == "energy" else
                [Assign("energy", Sub(Var("energy"), Const(cost)))])

    for origin, destination, cost, gate in model["routes"]:
        terms = guards(origin, cost)
        if gate != -1 and relaxed != "gates":
            terms.append(Eq(Var(("gate_a", "gate_b")[gate]), Const(1)))
        actions.append(Action(f"move_{origin}_{destination}", And(tuple(terms)),
                              tuple([Assign("location", Const(destination)), *spending(cost)])))
    if relaxed != "switches":
        for at, mask, cost in model["switches"]:
            effects = spending(cost)
            for bit, key in enumerate(("gate_a", "gate_b")):
                if mask & (1 << bit):
                    effects.append(Assign(key, Sub(Const(1), Var(key))))
            actions.append(Action(f"switch_{at}", And(tuple(guards(at, cost))), tuple(effects)))
    if relaxed != "recharge":
        actions.append(Action("recharge", And((Eq(Var("location"), Const(model["charger"])),
                                               Not(Eq(Var("recharged"), Const(1))),
                                               Lt(Var("energy"), Const(model["capacity"])))),
                              (Assign("energy", Const(model["capacity"])),
                               Assign("recharged", Const(1)))))
    return Puzzle("state-planning", "Energy, gates and switches", tuple(f"n{i}" for i in range(n)),
                  tuple((f"n{a}", f"n{b}") for a, b, _, _ in model["routes"]), variables,
                  initial, tuple(sorted(actions, key=lambda a: a.name)),
                  Objective(Eq(Var("location"), Const(n - 1)), MAX_STEPS,
                            requires_unique=False, trap_policy="allowed"))


def _sample(names, level, rng):
    n = len(names)
    start_links = [(0, b) for b in rng.sample(range(1, n), 3)]
    links = set(start_links)
    for a in range(1, n - 1):
        links.add((a, rng.choice([b for b in range(n) if a != b])))
    extras = [(a, b) for a in range(1, n - 1) for b in range(n) if a != b and (a, b) not in links]
    links.update(rng.sample(extras, min(len(extras), n + 3 - len(links))))
    routes = [[a, b, rng.randint(1, 3), -1] for a, b in sorted(links)]
    capacity = rng.randint(6, 8)
    energy = rng.randint(2, 3)
    charger = rng.choice([b for _, b in start_links if b != n - 1])
    gates = rng.choice([[0, 1], [1, 0]])
    # A reachable charger and an initially unaffordable direct exit focus
    # proposals on interactions, without fixing a solution or answer action.
    for route in routes:
        if route[:2] == [0, charger]:
            route[2] = 1
        elif route[:2] == [0, n - 1]:
            route[2] = energy + 1
    indices = rng.sample(range(len(routes)), 2)
    for gate, index in enumerate(indices):
        routes[index][3] = gate
    if level > 1:
        rng.choice([r for i, r in enumerate(routes) if i not in indices])[3] = rng.randrange(2)
    for route in routes:
        if route[:2] == [0, charger] and route[3] >= 0:
            route[3] = gates.index(1)
    if not {0, 1} <= {r[3] for r in routes}:
        return None
    switches = [[0, 3, rng.randrange(2)]]
    if level > 1 or rng.randrange(4):
        switches.append([charger, rng.randint(1, 3), rng.randrange(2)])
    return {"version": VERSION, "names": list(names), "level": level,
            "capacity": capacity, "initial_energy": energy, "initial_gates": gates,
            "charger": charger, "routes": routes, "switches": switches}


def _ablation_signature(result):
    return result["best_steps"], result["optimal_first_actions"]


def propose(names, level, rng):
    _validate_names(names)
    if type(level) is not int or level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("State planning requires level+3 location names")
    rejected = {"unsolved": 0, "choice": 0, "mechanics": 0}
    for attempt in range(PROPOSAL_BUDGET):
        model = _sample(names, level, rng)
        if model is None:
            rejected["mechanics"] += 1
            continue
        result = solve(model)
        if (result["best_steps"] is None
                or not MIN_STEPS[level - 1] <= result["best_steps"] <= MAX_STEPS):
            rejected["unsolved"] += 1
            continue
        if (len(result["optimal_first_actions"]) != 1
                or sum(cost is not None for cost in result["committed_first_costs"].values()) < 2
                or result["reachable_locations"] != len(names)
                or max(result["later_committed_choices"], default=0) < 2):
            rejected["choice"] += 1
            continue
        ablations = {mechanic: solve(model, relaxed=mechanic) for mechanic in MECHANICS}
        if any(_ablation_signature(r) == _ablation_signature(result) for r in ablations.values()):
            rejected["mechanics"] += 1
            continue
        options = [f"move_0_{b}" for a, b, _, _ in model["routes"] if a == 0] + ["switch_0"]
        rng.shuffle(options)
        model.update(options=options, answer_action=result["optimal_first_actions"][0],
                     best_steps=result["best_steps"], solution=result["solution"],
                     search={"budget": PROPOSAL_BUDGET, "attempts": attempt + 1,
                             "rejections": rejected})
        return model
    raise ProposalExhausted("No interacting state plan met the gates within the bounded search")


def structural_key(model):
    """Ignore labels, interior-node naming and the names assigned to the two gates."""
    n = len(model["names"])
    shapes = []
    for interior in permutations(range(1, n - 1)):
        order = (0, *interior, n - 1)
        mapping = {old: new for new, old in enumerate(order)}
        for swap in (False, True):
            routes = sorted((mapping[a], mapping[b], cost,
                             1 - gate if swap and gate >= 0 else gate)
                            for a, b, cost, gate in model["routes"])
            switches = sorted((mapping[at], ((mask & 1) << 1) | ((mask >> 1) & 1)
                               if swap else mask, cost) for at, mask, cost in model["switches"])
            gates = (tuple(reversed(model["initial_gates"])) if swap
                     else tuple(model["initial_gates"]))
            shapes.append((n, model["capacity"], model["initial_energy"], gates,
                           mapping[model["charger"]], tuple(routes), tuple(switches)))
    return digest([VERSION, min(shapes)])


def _crosscheck(model, relaxed=None):
    from ... import search
    from ...validate import validate

    puzzle = compile_model(model, relaxed=relaxed)
    findings = validate(puzzle)
    if findings:
        raise RuntimeError("Invalid compiled state-planning core model: " + str(findings))
    graph = search.explore(puzzle, max_states=MAX_STATES)
    if graph.truncated:
        raise RuntimeError("Core state-planning reachable-state budget exhausted")
    compiled = {state: sorted((action, graph.states[nxt]) for action, nxt in graph.adj[i])
                for i, state in enumerate(graph.states)}
    direct = _graph(model, relaxed)
    if compiled != direct:
        raise RuntimeError("Core IR and independent state-planning transitions disagreed")
    expected_goals = {s for s in direct if s[0] == len(model["names"]) - 1}
    if {graph.states[i] for i in graph.goals} != expected_goals:
        raise RuntimeError("Core IR and state-planning goals disagreed")
    return puzzle, _analyse_graph(model, direct)


def _smt_check(puzzle, expected):
    from dataclasses import replace

    import z3

    from ...ir import Action
    from ...z3_compile import build_unrolling

    # Goal-only padding is used solely for this proof. It makes reaching the
    # goal at H-1 equivalent to reaching it at ANY shorter length, even though
    # the real domain ends immediately at the goal. No wait appears in a plan.
    padded = replace(puzzle, actions=(*puzzle.actions, Action("goal_padding",
                                                             puzzle.objective.goal, ())))
    length = expected["best_steps"]

    def unroll(horizon):
        un = build_unrolling(padded, horizon)
        un.solver.set(rlimit=SMT_RESOURCE_LIMIT, random_seed=0)
        un.solver.add(un.goal_term(horizon))
        return un

    def require(un, wanted):
        status = un.solver.check()
        if status == z3.unknown:
            raise RuntimeError("State-planning SMT verification exhausted its bounded work")
        if status != wanted:
            raise RuntimeError("SMT and independent state-planning optimality disagreed")

    require(unroll(length - 1), z3.unsat)
    optimum = unroll(length)
    require(optimum, z3.sat)
    answer = expected["optimal_first_actions"][0]
    index = next(i for i, action in enumerate(optimum.ground) if action.name == answer)
    optimum.solver.add(z3.Not(optimum.fire[(index, 0)]))
    require(optimum, z3.unsat)
    return {"solver": "z3-bmc", "version": z3.get_version_string(),
            "checks": 3, "resource_limit_per_solver": SMT_RESOURCE_LIMIT,
            "shorter_plan": "unsat", "optimal_plan": "sat", "different_first_action": "unsat",
            "scope": "minimum action count and unique optimal first action; goal-only padding"}


def action_label(model, action):
    if action == "recharge":
        return f"Recharge at {model['names'][model['charger']]}"
    parts = action.split("_")
    if parts[0] == "move":
        return f"Move to {model['names'][int(parts[2])]}"
    if parts[0] == "switch":
        return f"Use switch at {model['names'][int(parts[1])]}"
    raise ValueError("Unknown state-planning action")


def _state_text(model, state):
    at, energy, a, b, used = state
    return (f"{model['names'][at]}, energy {energy}, "
            f"gate A {'open' if a else 'closed'}, gate B {'open' if b else 'closed'}, "
            f"recharge {'used' if used else 'unused'}")


def check(model):
    """Recompute all claims from raw rules, core IR and independent SMT."""
    from ...interpreter import run
    from ...serialize import puzzle_to_json

    puzzle, result = _crosscheck(model)
    strategy = None
    if "design_version" in model or "strategy" in model:
        from . import planning_invention, planning_strategy, state_planning_variety

        if model.get("design_version") == state_planning_variety.VERSION:
            strategy = state_planning_variety.certify(model)
        elif (model.get("design_version") == planning_invention.VERSION
                and model.get("strategy") == planning_invention.STRATEGY):
            strategy = planning_strategy.certify(model, model["strategy"])
        else:
            raise ValueError("Unsupported planning invention version or strategy")
    experience = None
    episode = None
    if "experience_version" in model or "experience_search" in model:
        from . import (
            planning_episode,
            planning_experience,
            planning_experience_v2,
            planning_experience_v3,
        )

        if model.get("experience_version") == planning_experience.VERSION:
            experience = planning_experience.certify(model)
        elif model.get("experience_version") == planning_experience_v2.VERSION:
            experience = planning_experience_v2.certify(model)
        elif model.get("experience_version") == planning_experience_v3.VERSION:
            experience = planning_experience_v3.certify(model)
        elif model.get("experience_version") == "planning-experience-v4":
            from . import planning_experience_v4

            experience = planning_experience_v4.certify(model)
        elif model.get("experience_version") == "planning-experience-v5":
            from . import planning_experience_v5

            experience = planning_experience_v5.certify(model)
        else:
            raise ValueError("Unsupported planning experience version")
        episode = planning_episode.create(model)
    best = result["best_steps"]
    if (best is None or not MIN_STEPS[model["level"] - 1] <= best <= MAX_STEPS
            or len(result["optimal_first_actions"]) != 1):
        raise RuntimeError("State plan must have a unique optimal first action within its bounds")
    if (sum(c is not None for c in result["committed_first_costs"].values()) < 2
            or max(result["later_committed_choices"], default=0) < 2
            or result["reachable_locations"] != len(model["names"])):
        raise RuntimeError("State plan lacks meaningful competing plans or reachable locations")
    options = model.get("options")
    allowed = {f"move_0_{b}" for a, b, _, _ in model["routes"] if a == 0} | {"switch_0"}
    if (not isinstance(options, list) or len(options) != 4
            or any(not isinstance(o, str) for o in options) or set(options) != allowed):
        raise ValueError("Show the three start routes and the start switch as distinct options")
    answer = result["optimal_first_actions"][0]
    if (model.get("answer_action") != answer or type(model.get("best_steps")) is not int
            or model["best_steps"] != best or model.get("solution") != result["solution"]):
        raise RuntimeError("State-plan answer, optimum or witness disagrees "
                           "with independent replay")
    core_replay = run(puzzle, result["solution"])
    keys = [v.key for v in puzzle.variables]
    replay_states = [[state[key] for key in keys] for state in core_replay.states]
    if not core_replay.reached_goal or replay_states != result["solution_states"]:
        raise RuntimeError("State-plan witness and core interpreter disagreed")
    ablations = {}
    for mechanic in MECHANICS:
        _, variant = _crosscheck(model, mechanic)
        if _ablation_signature(variant) == _ablation_signature(result):
            raise RuntimeError(f"The {mechanic} mechanic does not change the answer or optimum")
        ablations[mechanic] = {
            "best_steps": variant["best_steps"],
            "optimal_first_actions": variant["optimal_first_actions"],
            "answer_changes": variant["optimal_first_actions"] != result["optimal_first_actions"],
            "optimum_changes": variant["best_steps"] != best,
            "reachable_states": variant["reachable_states"],
            "solution": variant["solution"], "crosschecked": True,
        }
    smt = _smt_check(puzzle, result)
    steps, option_results = [], {}
    for action in options:
        label = action_label(model, action)
        legal = action in result["first_costs"]
        cost = result["first_costs"].get(action)
        if not legal:
            reason = "It is unavailable initially: check its gate and required energy."
        elif cost is None:
            reason = "After this action no legal continuation reaches the goal."
        else:
            reason = f"The shortest complete plan starting this way takes {cost} actions."
        option_results[label] = {"action": action, "legal": legal, "best_steps": cost,
                                 "is_answer": action == answer, "reason": reason}
        steps.append(f"{label}: {reason}")
    for number, (action, state) in enumerate(zip(result["solution"],
                                                result["solution_states"][1:], strict=True), 1):
        steps.append(f"{number}. {action_label(model, action)} → {_state_text(model, state)}.")
    steps.append(f"{action_label(model, answer)} is the only first action achieving the "
                 f"minimum of {best} actions. Several later optimal plans may share it.")
    return {"method": "state-planning-core-ir-and-independent-bfs", "model": model,
            **({"strategy": strategy} if strategy is not None else {}),
            **({"experience": experience, "episode": episode} if experience is not None else {}),
            "scope": "the stated fully observable rules; minimum action count, unique first action",
            "agree": True, "core_ir": puzzle_to_json(puzzle), "smt": smt,
            "quality": {**result, "mechanics": list(MECHANICS), "ablations": ablations,
                        "state_budget": MAX_STATES, "max_solution_steps": MAX_STEPS,
                        "uniqueness_scope": "optimal first action; not the full action sequence",
                        "committed_choice_scope": "no return dominated by the decision's state"},
            "option_results": option_results, "steps": steps,
            "structural_key": structural_key(model), "structural_key_version": VERSION}


def render(model):
    proof = check(model)
    names = model["names"]
    routes = "; ".join(f"{names[a]}→{names[b]}:{cost}" + (f"/{'AB'[gate]}" if gate >= 0 else "")
                       for a, b, cost, gate in model["routes"])
    switches = "; ".join(f"{names[at]}:"
                         f"{''.join('AB'[bit] for bit in range(2) if mask & (1 << bit))}"
                         f"/{cost}" for at, mask, cost in model["switches"])
    gates = ", ".join(f"{'AB'[i]} {'open' if state else 'closed'}"
                      for i, state in enumerate(model["initial_gates"]))
    stem = (f"Fictional rooms. Start {names[0]}, "
            f"energy {model['initial_energy']}/{model['capacity']}; "
            f"reach {names[-1]}. Every move, switch-use or recharge takes one action. "
            "Energy cannot go below zero.\n"
            "Only listed one-way routes (energy cost/required open gate; omitted gate means none): "
            + routes + f".\nInitially {gates}. "
            "Switches flip each listed gate open↔closed, persistently "
            "(room:gates/energy cost): " + switches + ".\n"
            f"Recharge at {names[model['charger']]} once, restoring energy to {model['capacity']}; "
            "only when below capacity. Revisits allowed.\n"
            "Which first action gives the fewest total actions, with optimal later choices?")
    answer = action_label(model, model["answer_action"])
    explanation = " ".join(proof["steps"])
    if model.get("design_version") == "state-planning-variety-v1":
        explanation = (
            f"{answer} starts a shortest plan of {model['best_steps']} actions. "
            + proof["strategy"]["explanation"]
        )
    if model.get("experience_version") == "planning-experience-v5":
        from .planning_experience_v5 import quiz_stem

        stem = quiz_stem(model)
    elif "episode" in proof:
        scenario = proof["episode"]
        stem = scenario["introduction"] + "\n" + scenario["objective"] + "\n" + stem
    return {"stem": stem, "answer": answer,
            "distractors": [action_label(model, action) for action in model["options"]
                            if action != model["answer_action"]],
            "explanation": explanation, "proof": proof,
            "hints": ["Track energy and both gate settings after every action.",
                      "Recharging restores energy once; switching may close a needed route.",
                      "Compare complete plans; moving immediately may not be the best first step."]}
