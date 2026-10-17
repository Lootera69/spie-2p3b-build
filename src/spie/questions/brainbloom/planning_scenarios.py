"""Concise authored situations for the second planning-experience version.

These stories decorate the same public route machine. Delivery is automatic on
arrival: no inventory, dialogue choice, deadline or other rule is introduced.
"""

from __future__ import annotations

from ...forge.corpus import digest

VERSION = "planning-episode-v2"
EXPERIENCE_VERSION = "planning-experience-v2"
_KIND = "expressive; not mechanical evidence"
_PREMISES = (
    {
        "id": "farewell-recording",
        "title": "A Proper Send-off",
        "robot": "Pip",
        "recipient": "Mira",
        "robot_role": "station announcement robot",
        "recipient_role": "retiring station caretaker",
        "start": "dispatch room",
        "destination": "farewell hall",
        "introduction": "Mira is retiring. She repaired Pip's speaker and listened to its first "
        "terrible joke. Now Pip wants to play her a farewell recording.",
        "want": "Play a farewell recording for Mira.",
        "recipient_want": "Share a goodbye with Pip and the station.",
        "opening": "A small announcement. An unusually large amount of feeling.",
        "outcome": "Pip plays the farewell recording for Mira.",
        "heading": "Farewell delivered",
        "arrival": "You always let me finish speaking. This one's for you, Mira.",
        "moves": (
            "The recording is ready. I am still rehearsing the hello.",
            "Mira would call this making an effort. I have recorded the effort.",
            "A farewell deserves the personal delivery service.",
        ),
        "empty": "No energy left. The recording can wait here with me.",
        "charger": "A place to gather my watts, if needed.",
        "charge": "Electrical composure restored. Emotional composure is separate.",
        "return": "A second look is allowed. Mira taught me that.",
    },
    {
        "id": "radio-repair-notes",
        "title": "Notes for the Next Broadcast",
        "robot": "Relay",
        "recipient": "Dev",
        "robot_role": "community radio helper",
        "recipient_role": "volunteer radio presenter",
        "start": "workshop",
        "destination": "radio studio",
        "introduction": "Relay has repair notes for Dev at the community radio studio. "
        "Dev once put Relay's shy weather report on air; this is a chance to help back.",
        "want": "Deliver the radio repair notes to Dev.",
        "recipient_want": "Read Relay's notes to plan the radio repairs.",
        "opening": "Today's forecast: helpful, with scattered technical annotations.",
        "outcome": "Relay delivers the repair notes, and Dev reads them at the studio desk.",
        "heading": "Repair notes delivered",
        "arrival": "You gave my voice some airtime, Dev. These notes are my reply.",
        "moves": (
            "Dev likes useful details. These notes have several.",
            "This is the off-air part of community radio.",
            "I am resisting the urge to announce my own arrival.",
        ),
        "empty": "Zero energy. The notes, fortunately, use no batteries.",
        "charger": "The charging facilities have excellent reception.",
        "charge": "Power back up. Still no need for a station jingle.",
        "return": "Revisiting the location. No repeat broadcast required.",
    },
    {
        "id": "opening-night-invitation",
        "title": "A Seat in the Audience",
        "robot": "Dot",
        "recipient": "Asha",
        "robot_role": "theatre stage robot",
        "recipient_role": "retired set designer",
        "start": "prop room",
        "destination": "theatre office",
        "introduction": "Asha built the sets and taught Dot its backstage routes. "
        "Dot carries her an opening-night invitation: this time, Asha gets a seat in the audience.",
        "want": "Give Asha her opening-night invitation.",
        "recipient_want": "Enjoy a performance from the audience after years of making sets.",
        "opening": "One invitation. No dramatic entrance has been commissioned.",
        "outcome": "Dot gives Asha the invitation to watch the performance from the audience.",
        "heading": "Invitation delivered",
        "arrival": "You made a place for everyone on stage, Asha. We saved a seat for you.",
        "moves": (
            "Usually I carry scenery. This is considerably more personal.",
            "Asha should see the view from the other side of the curtain.",
            "Personal delivery. I have kept the theatrics modest.",
        ),
        "empty": "No energy left. A perfectly reasonable place for an intermission.",
        "charger": "A charging point. Every backstage area has its stars.",
        "charge": "Battery refreshed. The invitation remains understated.",
        "return": "Revisiting a room is not the same as forgetting one's lines.",
    },
)


def create(model, source_facts):
    fingerprint = digest(model)
    variant = int(fingerprint[:8], 16) % len(_PREMISES)
    premise = _PREMISES[variant]
    names = model["names"]
    rooms = []
    for location, name in enumerate(names):
        role = (premise["start"] if location == 0 else premise["destination"]
                if location == len(names) - 1 else "charging alcove"
                if location == model["charger"] else "connecting room")
        rooms.append({"location": location, "name": name, "role": role,
                      "fact_ids": [f"room.{location}"]})
    return {
        "version": VERSION,
        "id": digest([VERSION, fingerprint]),
        "variant": variant,
        "premise": premise["id"],
        "title": premise["title"],
        "introduction": premise["introduction"],
        "objective": f"Guide {premise['robot']} from {names[0]} to {names[-1]}, "
        f"the {premise['destination']}. Every legal arrival succeeds.",
        "rooms": rooms,
        "characters": {
            "robot": {"name": premise["robot"], "role": premise["robot_role"],
                      "want": premise["want"], "voice": "Warm, observant, with dry asides."},
            "caretaker": {"name": premise["recipient"], "role": premise["recipient_role"],
                          "want": premise["recipient_want"]},
        },
        "dialogue": {"speaker": premise["robot"], "opening": premise["opening"], "kind": _KIND},
        "resolution": {"goal_location": len(names) - 1, "fact_ids": ["goal"],
                       "outcome": premise["outcome"], "heading": premise["heading"],
                       "destination": premise["destination"]},
        "source_facts": source_facts,
    }


def consequence(model, action, before, after):
    energy = f"Energy {before[1]} → {after[1]}."
    if action == "recharge":
        return f"{energy} Recharge used; gates unchanged."
    if action.startswith("move_"):
        return f"Arrive at {model['names'][after[0]]}. {energy} Gates unchanged."
    changes = "; ".join(f"gate {'AB'[bit]} {'open' if after[bit + 2] else 'closed'}"
                        for bit in range(2) if before[bit + 2] != after[bit + 2])
    return f"{changes[0].upper() + changes[1:]}. {energy}"


def _gates(mask):
    return " and ".join(f"gate {'AB'[bit]}" for bit in range(2) if mask & (1 << bit))


def connection_hint(model, current, step, level):
    """Levels 1–2 connect public constraints without querying any winning path."""
    at, energy, gate_a, gate_b, used = current
    names, state_id = model["names"], f"state.{step}"
    local = [row for row in model["routes"] if row[0] == at]
    closed = [row for row in local if row[3] != -1 and current[row[3] + 2] == 0]
    expensive = [row for row in local if row[2] > energy]
    switch = next((row for row in model["switches"] if row[0] == at), None)
    if closed:
        gates = {row[3] for row in closed}
        text = f"Closed: {_gates(sum(1 << gate for gate in gates))}. Compare route gate labels."
        refs = [state_id, "rules.gates", *[f"route.{a}.{b}" for a, b, _, _ in closed]]
        if level == 2:
            controls = [s for s in model["switches"] if any(s[1] & (1 << g) for g in gates)]
            if controls:
                text += " " + "; ".join(
                    f"{names[at]} reverses {_gates(mask)} for {cost} energy"
                    for at, mask, cost in controls
                ) + ". A reversal may also close a gate."
                refs += ["rules.switches", "rules.energy", *[f"switch.{s[0]}" for s in controls]]
            else:
                text += " No console changes these gates; compare other route requirements."
                refs += [f"switch.{s[0]}" for s in model["switches"]]
        return text, refs
    if expensive:
        text = f"Energy {energy}; some outgoing routes cost more."
        refs = [state_id, "rules.energy", *[f"route.{a}.{b}" for a, b, _, _ in expensive]]
        if level == 2:
            if (model.get("experience_version") == "planning-experience-v3"
                    and at == model["charger"] and not used):
                text += f" The unused charger here fills to {model['capacity']} once. "
                text += "Compare that energy with the outgoing route costs."
            else:
                text += (" Recharge used; no further action can add energy." if used else
                         f" The charger at {names[model['charger']]} fills to {model['capacity']} "
                         "once; reaching it still needs affordable, open routes.")
            refs += ["charger", "capacity", "rules.recharge"]
        return text, refs
    if at == model["charger"] and not used and energy < model["capacity"]:
        text = f"Unused charger here; battery {energy}/{model['capacity']}."
        if level == 2:
            text += " Filling uses the one recharge. Check costs and gates beyond this room."
        return text, [state_id, "charger", "capacity", "rules.recharge", "rules.gates"]
    if switch:
        _, mask, cost = switch
        text = (f"This console reverses {_gates(mask)} for {cost} energy. "
                f"A is {'open' if gate_a else 'closed'}; B is {'open' if gate_b else 'closed'}.")
        if level == 2:
            text += " Compare both resulting gate settings with later route requirements."
        return text, [state_id, f"switch.{at}", "rules.switches", "rules.gates"]
    text = f"Energy {energy}. Compare costs and gate labels on outgoing routes."
    refs = [state_id, "rules.energy", "rules.gates", *[f"route.{a}.{b}" for a, b, _, _ in local]]
    if level == 2:
        text += " After paying each cost, compare the remaining energy and unchanged gates "
        text += "with the next room's routes."
        destinations = {row[1] for row in local}
        refs += [f"route.{a}.{b}" for a, b, _, _ in model["routes"] if a in destinations]
    return text, refs


def dialogue(scenario, model, action, before, after, prior_states):
    """React to an observed event, without implying a plan or an unseen event."""
    premise = _PREMISES[scenario["variant"]]
    if action == "recharge":
        text = f"{before[1]} to {after[1]} energy. {premise['charge']}"
    elif action.startswith("switch_"):
        closed = ["AB"[bit] for bit in range(2) if before[bit + 2] and not after[bit + 2]]
        opened = ["AB"[bit] for bit in range(2) if not before[bit + 2] and after[bit + 2]]
        reports = []
        if opened:
            reports.append(f"Opened {', '.join(opened)}")
        if closed:
            reports.append(f"closed {', '.join(closed)}")
        text = "; ".join(reports) + ". The gates have accepted the amendment."
        text = text[0].upper() + text[1:]
    else:
        place = model["names"][after[0]]
        previous_locations = [state[0] for i, state in enumerate(prior_states)
                              if i == 0 or prior_states[i - 1][0] != state[0]]
        visits = previous_locations.count(after[0])
        connecting_rooms = {state[0] for state in prior_states
                            if state[0] not in (0, model["charger"], len(model["names"]) - 1)}
        if after[0] == len(model["names"]) - 1:
            text = f"At {place}. {premise['arrival']}"
        elif visits:
            text = f"Back at {place}, visit {visits + 1}."
            # The first return gets a reaction; subsequent visits need no encore.
            if len(set(previous_locations)) == len(previous_locations):
                text += " " + premise["return"]
        elif after[1] == 0:
            text = (f"At {place}, with 0 energy." if any(s[1] == 0 for s in prior_states)
                    else f"At {place}. {premise['empty']}")
        elif after[0] == model["charger"] and not after[4]:
            text = f"At {place}. {premise['charger']}"
        else:
            text = f"At {place}. {premise['moves'][len(connecting_rooms)]}"
    return {"speaker": premise["robot"], "text": text, "kind": _KIND}


def resolution(scenario, model, actions, states):
    premise = _PREMISES[scenario["variant"]]
    moves = sum(action.startswith("move_") for action in actions)
    switches = sum(action.startswith("switch_") for action in actions)
    recharges = actions.count("recharge")
    summary = (f"Arrived in {len(actions)} actions: {moves} moves, "
               f"{switches} switch uses, {recharges} recharges. Energy remaining: {states[-1][1]}.")
    if model.get("experience_version") == "planning-experience-v3":
        # Preserve the exact revision-12 replay text for existing saved puzzles.
        counts = ((len(actions), "action"), (moves, "move"),
                  (switches, "switch use"), (recharges, "recharge"))
        terms = [f"{count} {noun}{'' if count == 1 else 's'}" for count, noun in counts]
        summary = (f"Arrived in {terms[0]}: {', '.join(terms[1:])}. "
                   f"Energy remaining: {states[-1][1]}.")
    return {
        "text": f"At {model['names'][-1]}, {premise['outcome']}",
        "replay_summary": summary,
        "fact_ids": ["goal", *[f"state.{i}" for i in range(len(states))]],
        "dialogue": {"speaker": premise["robot"], "text": premise["arrival"], "kind": _KIND},
    }
