"""Authored station episodes over the existing, fully observable planning machine.

The transcript is the only progress input. Every request reconstructs the state
with the core interpreter and crosschecks the complete domain graph. Scenario
prose is deterministic decoration of public model facts, never another rule set.
"""

from __future__ import annotations

from collections import deque

from ...forge.corpus import compact, digest
from ...interpreter import run
from . import planning_scenarios, planning_scenarios_v4, planning_scenarios_v5, state_planning

VERSION = "planning-episode-v1"
MAX_ACTIONS = 128
_FIELDS = (
    "version",
    "names",
    "level",
    "capacity",
    "initial_energy",
    "initial_gates",
    "charger",
    "routes",
    "switches",
)
_GATES = ("A", "B")
_VOICES = (
    {
        "robot": "Pip",
        "caretaker": "Mira",
        "title": "A Proper Send-off",
        "memory": "Mira repaired Pip's speaker, then stayed to hear its first terrible joke.",
        "opening": "This farewell announcement is official. The wobble in my voice is unofficial.",
        "moving": "Proceeding with the dignity expected of a small wheeled appliance.",
        "switching": "The access policy has been revised. No committee was consulted.",
        "charging": "A brief electrical refreshment. I have declined the biscuit.",
        "arrival": "You always waited for me to finish speaking. This one's for you, Mira.",
    },
    {
        "robot": "Relay",
        "caretaker": "Dev",
        "title": "The Last Announcement",
        "memory": "Dev called Relay a colleague while everyone else still called it equipment.",
        "opening": "I have prepared a concise tribute. Concise by station-announcement standards.",
        "moving": "All passengers, meaning me, are proceeding to the next room.",
        "switching": "A decisive statement from the gate department: click.",
        "charging": "The battery appreciates this. It is less articulate than I am.",
        "arrival": "Thank you for making room for me, Dev. You made this station feel like home.",
    },
    {
        "robot": "Dot",
        "caretaker": "Asha",
        "title": "A Message Worth Carrying",
        "memory": "Asha taught Dot that asking for help was a useful feature, not a fault.",
        "opening": "Farewell recording prepared. Emotional composure remains in testing.",
        "moving": "A completely professional amount of determination has been applied.",
        "switching": "The gates have received a strongly worded electrical signal.",
        "charging": "Power restored. Poise is a separate department.",
        "arrival": "You helped me find my voice, Asha. I wanted you to hear what it was for.",
    },
)


def _fact(identifier, source, value, text):
    return {"id": identifier, "kind": "source", "source": source, "value": value, "text": text}


def _raw(model):
    state_planning._validate(model)
    # Solver witnesses, quiz answers and caller-supplied metadata are not evidence.
    raw = {field: model[field] for field in _FIELDS}
    if _v2(model):
        raw["experience_version"] = model["experience_version"]
    return raw


def _v2(model):
    return _scenario_module(model) is not None


def _scenario_module(model):
    # Missing versions retain the original episode; unknown versions fail closed.
    if ("experience_version" not in model
            or model["experience_version"] == "planning-experience-v1"):
        return None
    version = model["experience_version"]
    if version in (planning_scenarios.EXPERIENCE_VERSION, "planning-experience-v3"):
        return planning_scenarios
    if version == planning_scenarios_v4.EXPERIENCE_VERSION:
        return planning_scenarios_v4
    if version == planning_scenarios_v5.EXPERIENCE_VERSION:
        return planning_scenarios_v5
    raise ValueError("Unsupported planning experience version")


def _gate_words(mask):
    return " and ".join(f"gate {_GATES[bit]}" for bit in range(2) if mask & (1 << bit))


def _source_facts(model):
    names = model["names"]
    facts = [
        _fact(
            "rules.actions",
            "state-planning-v1.actions",
            1,
            "Every move, switch use and recharge counts as one action.",
        ),
        _fact(
            "rules.energy",
            "state-planning-v1.energy",
            "spend_if_affordable",
            "Moves and switches require their listed energy and subtract that amount.",
        ),
        _fact(
            "rules.gates",
            "state-planning-v1.gates",
            "open_required",
            "A gated route can be used only while its named gate is open.",
        ),
        _fact(
            "rules.switches",
            "state-planning-v1.switches",
            "toggle",
            "A switch reverses each listed gate: open becomes closed and closed becomes open.",
        ),
        _fact(
            "rules.recharge",
            "state-planning-v1.recharge",
            "once_below_capacity",
            "Recharging is optional, works only below capacity, and can be used once.",
        ),
        _fact(
            "initial",
            "model.initial_energy,model.initial_gates",
            list(state_planning._initial(model)),
            state_planning._state_text(model, state_planning._initial(model)) + ".",
        ),
        _fact(
            "capacity",
            "model.capacity",
            model["capacity"],
            f"Battery capacity is {model['capacity']} energy units.",
        ),
        _fact(
            "charger",
            "model.charger",
            model["charger"],
            f"The charger at {names[model['charger']]} restores energy to {model['capacity']}.",
        ),
        _fact(
            "goal",
            "model.names[-1]",
            len(names) - 1,
            f"Reach {names[-1]} to complete the episode; every legal arrival succeeds.",
        ),
    ]
    for location, name in enumerate(names):
        facts.append(
            _fact(
                f"room.{location}",
                f"model.names[{location}]",
                name,
                f"Room {location} has the map label {name}.",
            )
        )
    for index, (origin, destination, cost, gate) in enumerate(model["routes"]):
        condition = "no gate" if gate == -1 else f"gate {_GATES[gate]} open"
        facts.append(
            _fact(
                f"route.{origin}.{destination}",
                f"model.routes[{index}]",
                {"origin": origin, "destination": destination, "energy": cost, "gate": gate},
                f"{names[origin]} to {names[destination]} is one-way, costs {cost} energy, "
                f"and requires {condition}.",
            )
        )
    for index, (location, mask, cost) in enumerate(model["switches"]):
        facts.append(
            _fact(
                f"switch.{location}",
                f"model.switches[{index}]",
                {"location": location, "gate_mask": mask, "energy": cost},
                f"The switch at {names[location]} reverses {_gate_words(mask)} "
                f"and costs {cost} energy.",
            )
        )
    return facts


def create(model):
    """Return the canonical authored scenario; no random state or solution is used."""
    model = _raw(model)
    if _v2(model):
        return _scenario_module(model).create(model, _source_facts(model))
    fingerprint = digest(model)
    variant = int(fingerprint[:8], 16) % len(_VOICES)
    voice = _VOICES[variant]
    robot, caretaker, names = voice["robot"], voice["caretaker"], model["names"]
    rooms = []
    for location, name in enumerate(names):
        role = (
            "dispatch room"
            if location == 0
            else "farewell hall"
            if location == len(names) - 1
            else "charging alcove"
            if location == model["charger"]
            else "station room"
        )
        rooms.append(
            {"location": location, "name": name, "role": role, "fact_ids": [f"room.{location}"]}
        )
    return {
        "version": VERSION,
        "id": digest([VERSION, fingerprint]),
        "variant": variant,
        "title": voice["title"],
        "introduction": (
            f"{robot}, the station's announcement robot, carries a farewell recording for "
            f"{caretaker}, its retiring caretaker. {voice['memory']} "
            f"The station uses the map's topic labels for its rooms: {names[0]} is the "
            f"dispatch room, and {names[-1]} is the farewell hall."
        ),
        "objective": f"Guide {robot} from {names[0]} to {names[-1]} so {caretaker} can hear "
        "the recording. Every legal arrival completes the farewell; "
        "you can also explore how to use fewer actions.",
        "rooms": rooms,
        "characters": {
            "robot": {
                "name": robot,
                "role": "announcement robot",
                "want": f"Deliver its farewell recording to {caretaker}.",
                "voice": "Warm, earnest and ceremonially official, with dry asides.",
            },
            "caretaker": {
                "name": caretaker,
                "role": "retiring station caretaker",
                "want": "Say goodbye to the station and the colleagues they cared for.",
            },
        },
        "dialogue": {
            "speaker": robot,
            "opening": voice["opening"],
            "kind": "expressive; not mechanical evidence",
        },
        "resolution": {
            "goal_location": len(names) - 1,
            "fact_ids": ["goal"],
            "outcome": f"{robot} arrives and plays the recording for {caretaker}.",
        },
        "source_facts": _source_facts(model),
    }


def _state(model, state, steps):
    return {
        "location": state[0],
        "location_name": model["names"][state[0]],
        "energy": state[1],
        "capacity": model["capacity"],
        "gates": list(state[2:4]),
        "recharged": bool(state[4]),
        "steps": steps,
    }


def _action_fact(action):
    if action == "recharge":
        return "charger"
    return action.replace("move_", "route_").replace("_", ".")


def _action_dependencies(action, state_id):
    rules = (
        ["rules.recharge", "capacity"]
        if action == "recharge"
        else ["rules.energy", "rules.switches" if action.startswith("switch_") else "rules.gates"]
    )
    return [state_id, _action_fact(action), "rules.actions", *rules]


def _consequence(model, action, before, after):
    if _v2(model):
        return _scenario_module(model).consequence(model, action, before, after)
    if action == "recharge":
        return (
            f"Energy rises from {before[1]} to {after[1]}. "
            "The single recharge is now used; gate settings stay the same."
        )
    if action.startswith("move_"):
        return (
            f"Arrive at {model['names'][after[0]]}; energy falls from {before[1]} "
            f"to {after[1]}. Gate settings and recharge availability stay the same."
        )
    changes = "; ".join(
        f"gate {_GATES[bit]} becomes {'open' if after[bit + 2] else 'closed'}"
        for bit in range(2)
        if before[bit + 2] != after[bit + 2]
    )
    return (
        f"{changes[0].upper() + changes[1:]}. Energy changes from {before[1]} to {after[1]}; "
        "location and recharge availability stay the same."
    )


def _local_actions(model, current, step, graph):
    at, energy = current[:2]
    available = dict(graph[current])
    rows = []
    for origin, destination, cost, gate in model["routes"]:
        if origin != at:
            continue
        reasons = []
        if energy < cost:
            reasons.append(f"Needs {cost} energy; only {energy} remains.")
        if gate != -1 and current[gate + 2] == 0:
            reasons.append(f"Gate {_GATES[gate]} is closed.")
        condition = "" if gate == -1 else f" Requires gate {_GATES[gate]} to be open."
        rows.append(
            (
                f"move_{origin}_{destination}",
                "move",
                reasons,
                f"Move to {model['names'][destination]} and spend {cost} energy.{condition}",
            )
        )
    for location, mask, cost in model["switches"]:
        if location != at:
            continue
        reasons = [] if energy >= cost else [f"Needs {cost} energy; only {energy} remains."]
        rows.append(
            (
                f"switch_{location}",
                "switch",
                reasons,
                f"Reverse {_gate_words(mask)} and spend {cost} energy.",
            )
        )
    if at == model["charger"]:
        reasons = []
        if current[4]:
            reasons.append("The single recharge has already been used.")
        if energy >= model["capacity"]:
            reasons.append("The battery is already at capacity.")
        rows.append(
            (
                "recharge",
                "recharge",
                reasons,
                f"Restore energy to {model['capacity']} and use the single recharge.",
            )
        )
    output = []
    for action, kind, reasons, description in sorted(rows):
        legal = action in available
        if legal != (not reasons):
            raise RuntimeError("Episode action explanation disagreed with verified transitions")
        nxt = available.get(action)
        output.append(
            {
                "id": action,
                "kind": kind,
                "label": state_planning.action_label(model, action),
                "legal": legal,
                "reasons": reasons,
                "consequence": _consequence(model, action, current, nxt) if legal else description,
                "next_state": _state(model, nxt, step + 1) if legal else None,
                "fact_ids": _action_dependencies(action, f"state.{step}"),
            }
        )
    return output


def _distances(model, graph):
    reverse = {state: [] for state in graph}
    for state, edges in graph.items():
        for _, target in edges:
            reverse[target].append(state)
    distances = {state: 0 for state in graph if state[0] == len(model["names"]) - 1}
    queue = deque(distances)
    while queue:
        state = queue.popleft()
        for previous in reverse[state]:
            if previous not in distances:
                distances[previous] = distances[state] + 1
                queue.append(previous)
    return distances


def _connection_hint(model, current, step, level):
    """Select a public constraint, without consulting a shortest path or winner."""
    if _v2(model):
        return _scenario_module(model).connection_hint(model, current, step, level)
    at, energy, gate_a, gate_b, used = current
    names, state_id = model["names"], f"state.{step}"
    local = [row for row in model["routes"] if row[0] == at]
    closed = [row for row in local if row[3] != -1 and current[row[3] + 2] == 0]
    expensive = [row for row in local if row[2] > energy]
    switch = next((row for row in model["switches"] if row[0] == at), None)
    if closed:
        gates = sorted({row[3] for row in closed})
        labels = " and ".join(f"gate {_GATES[gate]}" for gate in gates)
        refs = [state_id, "rules.gates", *[f"route.{a}.{b}" for a, b, _, _ in closed]]
        text = (
            f"At {names[at]}, {labels} {'is' if len(gates) == 1 else 'are'} closed. "
            "Compare the outgoing routes' gate labels with the live gate settings."
        )
        if level == 2:
            controls = [row for row in model["switches"] if any(row[1] & (1 << g) for g in gates)]
            if controls:
                descriptions = [
                    f"the console at {names[location]} reverses {_gate_words(mask)} "
                    f"for {cost} energy"
                    for location, mask, cost in controls
                ]
                description = "; ".join(descriptions)
                text += " " + description[0].upper() + description[1:] + ". "
                text += ("Check both gate settings after a reversal, "
                         "as well as the energy to reach a console.")
                refs += ["rules.switches", "rules.energy", *[f"switch.{s[0]}" for s in controls]]
            else:
                text += (" No console changes that closed gate; "
                         "compare routes with different requirements.")
                refs += [f"switch.{s[0]}" for s in model["switches"]]
        return text, refs
    if expensive:
        refs = [state_id, "rules.energy", *[f"route.{a}.{b}" for a, b, _, _ in expensive]]
        text = (
            f"You have {energy} energy at {names[at]}. "
            "Some outgoing routes need more than that; "
            "their displayed costs explain why they are unavailable."
        )
        if level == 2:
            text += (
                " The single recharge is already used, "
                "so further moves and switches can only spend energy."
                if used
                else f" The one-use charger at {names[model['charger']]} fills the battery to "
                f"{model['capacity']}; getting there still has to fit the current energy and gates."
            )
            refs += ["charger", "capacity", "rules.recharge"]
        return text, refs
    if at == model["charger"] and not used and energy < model["capacity"]:
        text = (
            f"This room contains the unused charger. Your battery holds {energy} "
            f"of {model['capacity']} energy units."
        )
        if level == 2:
            text += (
                " A recharge fills the battery once and leaves both gates unchanged. "
                "Compare the energy needed after leaving with those routes' gate requirements."
            )
        return text, [state_id, "charger", "capacity", "rules.recharge", "rules.gates"]
    if switch:
        _, mask, cost = switch
        text = (
            f"The console here reverses {_gate_words(mask)} for {cost} energy. "
            f"Gate A is {'open' if gate_a else 'closed'}; "
            f"gate B is {'open' if gate_b else 'closed'}."
        )
        if level == 2:
            text += (
                " A reversal can close an open gate as well as open a closed one. "
                "Compare the gates needed on the routes after this room before changing them."
            )
        return text, [state_id, f"switch.{at}", "rules.switches", "rules.gates"]
    text = (
        f"At {names[at]}, you have {energy} energy. "
        "Each outgoing route shows both its energy cost and any gate it needs."
    )
    refs = [state_id, "rules.energy", "rules.gates", *[f"route.{a}.{b}" for a, b, _, _ in local]]
    if level == 2:
        text += (
            " Subtract a route's cost, then compare that remainder and the unchanged gates "
            "with the routes leaving its destination."
        )
        destinations = {row[1] for row in local}
        refs += [f"route.{a}.{b}" for a, b, _, _ in model["routes"] if a in destinations]
    return text, refs


def _hint(model, current, step, level, graph, distances, facts):
    if level == 0:
        return None
    state_id = f"state.{step}"
    if current[0] == len(model["names"]) - 1:
        return {
            "level": level,
            "text": ("Delivery complete." if _v2(model)
                     else "The farewell recording has reached its destination."),
            "fact_ids": [state_id, "goal"],
        }
    if current not in distances:
        return {
            "level": level,
            "text": (f"No legal continuation reaches {model['names'][-1]}. Undo or restart."
                     if _v2(model) else
                     "No sequence of legal actions from this state reaches the farewell hall. "
                     "Return to an earlier position or restart to explore another route."),
            "fact_ids": [state_id, "goal", "reachability.current"],
        }
    if level < 3:
        text, refs = _connection_hint(model, current, step, level)
        return {"level": level, "text": text, "fact_ids": list(dict.fromkeys(refs))}
    action, target = min(
        (action, target)
        for action, target in graph[current]
        if distances.get(target) == distances[current] - 1
    )
    dependencies = [fact["id"] for fact in facts if fact["kind"] == "source"] + [state_id]
    facts.append(
        {
            "id": "hint.next",
            "kind": "deduction",
            "source": "verified_graph.reverse_bfs",
            "value": {"action": action, "begins_shortest_continuation": True},
            "depends_on": dependencies,
            "text": "This action begins a shortest legal continuation from the current state.",
        }
    )
    return {
        "level": level,
        "action": action,
        "text": f"{state_planning.action_label(model, action)}. "
        f"{_consequence(model, action, current, target)} "
        + ("Begins a shortest legal continuation." if _v2(model) else
           "This begins a shortest legal continuation from your current position."),
        "fact_ids": [*_action_dependencies(action, state_id), "hint.next"],
    }


def replay(model, scenario, actions, *, hint_level=0):
    """Recompute a bounded action transcript and expose only requested help.

    Illegal/unknown moves, post-goal moves and altered scenarios raise ValueError.
    The action bound limits request size; it is not a fictional deadline or loss.
    Caller state, best_steps, answer_action and saved witnesses are never read.
    """
    if type(hint_level) is not int or hint_level not in range(4):
        raise ValueError("Hint level must be an integer from 0 to 3")
    if (
        not isinstance(actions, list)
        or len(actions) > MAX_ACTIONS
        or any(not isinstance(action, str) or not action or len(action) > 40 for action in actions)
    ):
        raise ValueError(f"Actions must be a list of at most {MAX_ACTIONS} action identifiers")
    model = _raw(model)
    canonical = create(model)
    try:
        matches = isinstance(scenario, dict) and compact(scenario) == compact(canonical)
    except (TypeError, ValueError, RecursionError):
        matches = False
    if not matches:
        raise ValueError("Scenario does not match the canonical episode for this model")
    puzzle, _ = state_planning._crosscheck(model)
    graph = state_planning._graph(model)
    current = state_planning._initial(model)
    states = [current]
    for tick, action in enumerate(actions):
        if current[0] == len(model["names"]) - 1:
            raise ValueError(f"Action {tick + 1} follows an already completed episode")
        choices = dict(graph[current])
        if action not in choices:
            raise ValueError(
                f"Action {tick + 1} is unknown or illegal in its replayed state: {action}"
            )
        current = choices[action]
        states.append(current)
    outcome = run(puzzle, actions)
    core_states = [
        tuple(state[key] for key in ("location", "energy", "gate_a", "gate_b", "recharged"))
        for state in outcome.states
    ]
    if core_states != states or outcome.reached_goal != (current[0] == len(model["names"]) - 1):
        raise RuntimeError("Episode replay disagreed with the core interpreter")
    facts = list(canonical["source_facts"])
    history = []
    voice = _VOICES[canonical["variant"]]
    for step, state in enumerate(states):
        refs = (
            ["initial"]
            if step == 0
            else _action_dependencies(actions[step - 1], f"state.{step - 1}")
        )
        facts.append(
            {
                "id": f"state.{step}",
                "kind": "replay",
                "source": "core.interpreter",
                "value": _state(model, state, step),
                "depends_on": refs,
                "text": state_planning._state_text(model, state) + ".",
            }
        )
        if step:
            action, before = actions[step - 1], states[step - 1]
            kind = (
                "charging"
                if action == "recharge"
                else "switching"
                if action.startswith("switch_")
                else "moving"
            )
            history.append(
                {
                    "step": step,
                    "action": action,
                    "label": state_planning.action_label(model, action),
                    "before": _state(model, before, step - 1),
                    "after": _state(model, state, step),
                    "text": _consequence(model, action, before, state),
                    "fact_ids": [*refs, f"state.{step}"],
                    "dialogue": _scenario_module(model).dialogue(
                        canonical, model, action, before, state, states[:step]
                    ) if _v2(model) else {
                        "speaker": voice["robot"],
                        "text": voice[kind],
                        "kind": "expressive; not mechanical evidence",
                    },
                }
            )
    distances = _distances(model, graph)
    facts.append(
        {
            "id": "reachability.current",
            "kind": "deduction",
            "source": "verified_graph.exhaustive_reachability",
            "value": {"goal_reachable": current in distances},
            "depends_on": [fact["id"] for fact in facts if fact["kind"] == "source"]
            + [f"state.{len(actions)}"],
            "text": "A legal continuation reaches the goal."
            if current in distances
            else "No legal continuation from this state reaches the goal.",
        }
    )
    reached = outcome.reached_goal
    hint = _hint(model, current, len(actions), hint_level, graph, distances, facts)
    local = [] if reached else _local_actions(model, current, len(actions), graph)
    resolution = None
    if reached:
        switch_count = sum(action.startswith("switch_") for action in actions)
        recharge_count = actions.count("recharge")
        resolution = {
            "text": f"At {model['names'][-1]}, {voice['robot']} plays the recording for "
            f"{voice['caretaker']}. The farewell has arrived.",
            "replay_summary": f"You arrived in {len(actions)} actions, used a switch "
            f"{switch_count} times, and recharged {recharge_count} times.",
            "fact_ids": ["goal", *[f"state.{i}" for i in range(len(states))]],
            "dialogue": {
                "speaker": voice["robot"],
                "text": voice["arrival"],
                "kind": "expressive; not mechanical evidence",
            },
        }
        if _v2(model):
            resolution = _scenario_module(model).resolution(canonical, model, actions, states)
    return {
        "version": canonical["version"],
        "scenario": canonical,
        "actions": list(actions),
        "state": _state(model, current, len(actions)),
        "local_actions": local,
        "legal_actions": [row["id"] for row in local if row["legal"]],
        "history": history,
        "goal_reached": reached,
        "status": "complete" if reached else "in_progress" if current in distances else "dead_end",
        "can_append": not reached and len(actions) < MAX_ACTIONS,
        "history_limit": MAX_ACTIONS,
        "hint": hint,
        "resolution": resolution,
        "facts": facts,
    }
