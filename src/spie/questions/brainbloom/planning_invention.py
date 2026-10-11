"""Bounded invention around an explicit planning strategy, with solver-guided repair.

The unchanged v1 sampler supplies fresh worlds. A small beam retains near misses;
failed quality gates and the solver's actual paths direct local edits. Search
diagnostics guide invention only: the core/SMT and strategy certificates remain
independent acceptance checks when the model is rendered.
"""

from __future__ import annotations

from copy import deepcopy

from ...forge.corpus import digest
from . import state_planning as domain

VERSION = "planning-invention-v1"
STRATEGY = "invest-energy"
PROPOSAL_BUDGET = 2_000
BEAM_SIZE = 8
RESTART_INTERVAL = 4
MAX_REPAIR_DEPTH = 6


class InventionExhausted(domain.ProposalExhausted):
    def __init__(self, search):
        super().__init__("No strategy-qualified state plan met all gates within the bounded search")
        self.search = deepcopy(search)


def physical_key(model):
    return digest({key: model[key] for key in (
        "version", "names", "level", "capacity", "initial_energy", "initial_gates",
        "charger", "routes", "switches",
    )})


def _energy_costs(model, result):
    costs = {f"move_{a}_{b}": cost for a, b, cost, _ in model["routes"] if a == 0}
    costs.update({f"switch_{at}": cost for at, _, cost in model["switches"] if at == 0})
    return {action: costs[action] for action in result["first_costs"]}


def strategy_status(model, result):
    """Cheap search diagnostic; the release certificate uses a separate core BFS."""
    costs = _energy_costs(model, result)
    cheapest = [action for action, cost in costs.items() if cost == min(costs.values())]
    winners = result["optimal_first_actions"]
    winner = winners[0] if len(winners) == 1 else None
    viable = bool(cheapest) and all(result["committed_first_costs"].get(a) is not None
                                   for a in cheapest)
    slower = (result["best_steps"] is not None and bool(cheapest)
              and all(result["first_costs"][a] is not None
                      and result["first_costs"][a] > result["best_steps"] for a in cheapest))
    invests = winner is not None and bool(costs) and costs[winner] > min(costs.values())
    return {"holds": viable and slower and invests, "cheapest": cheapest,
            "costs": costs, "viable": viable, "slower": slower, "invests": invests}


def evaluate(model):
    """One model evaluation; every actual domain graph construction is counted."""
    if model is None:
        return {"reason": "shape", "score": (0, 0, 0), "graph_evaluations": 0}
    result = domain.solve(model)
    steps = result["best_steps"]
    conditions = (
        steps is not None and domain.MIN_STEPS[model["level"] - 1] <= steps <= domain.MAX_STEPS,
        len(result["optimal_first_actions"]) == 1,
        result["reachable_locations"] == len(model["names"]),
        sum(c is not None for c in result["committed_first_costs"].values()) >= 2,
        max(result["later_committed_choices"], default=0) >= 2,
    )
    strategy = strategy_status(model, result)
    ablations = {}
    if all(conditions):
        ablations = {key: domain.solve(model, relaxed=key) for key in domain.MECHANICS}
    necessary = [key for key, value in ablations.items()
                 if domain._ablation_signature(value) != domain._ablation_signature(result)]
    reason = ("unsolved" if not conditions[0] else "choice" if not all(conditions)
              else "mechanics" if len(necessary) != len(domain.MECHANICS)
              else "strategy" if not strategy["holds"] else None)
    return {"result": result, "strategy": strategy, "ablations": ablations,
            "necessary": necessary, "reason": reason,
            "score": (sum(conditions), len(necessary),
                      sum(strategy[key] for key in ("viable", "slower", "invests"))),
            "graph_evaluations": 1 + len(ablations)}


def _repairs(model, assessment):
    """Edits carry the failed gate and its solver witness, never a canned solution."""
    result, strategy = assessment["result"], assessment["strategy"]
    edits = []

    def offer(path, value, reason, witness=()):
        old = model
        for part in path:
            old = old[part]
        if (path[0] == "routes" and path[-1] == 3 and old >= 0 and old != value
                and sum(row[3] == old for row in model["routes"]) == 1):
            return  # Both gates must remain represented in the physical schema.
        if old != value:
            edits.append({"path": list(path), "before": old, "after": value,
                          "reason": reason, "witness": list(witness)})

    def route_edits(witness, reason, *, close=False, cheaper=False):
        for action in witness:
            if action.startswith("move_"):
                _, origin, destination = action.split("_")
                index = next(i for i, row in enumerate(model["routes"])
                             if row[:2] == [int(origin), int(destination)])
                route = model["routes"][index]
                if close:
                    for gate, state in enumerate(model["initial_gates"]):
                        if not state:
                            offer(("routes", index, 3), gate, reason, witness)
                elif cheaper:
                    offer(("routes", index, 2), max(1, route[2] - 1), reason, witness)
                else:
                    offer(("routes", index, 2), min(4, route[2] + 1), reason, witness)

    # A counterexample is a successful cheapest first action, or a cheap action
    # whose only continuation undoes the choice. Adjust its cost/effect, or make
    # the actual winning route require an up-front investment.
    if not strategy["holds"]:
        witness = result["solution"]
        for index, (at, _, _) in enumerate(model["switches"]):
            if at == 0:
                offer(("switches", index, 2), 0, "cheapest-first strategy", witness)
                for mask in (1, 2, 3):
                    offer(("switches", index, 1), mask, "cheapest-first strategy", witness)
        if len(result["optimal_first_actions"]) == 1:
            route_edits(result["optimal_first_actions"], "increase initial investment")
        for gate, state in enumerate(model["initial_gates"]):
            offer(("initial_gates", gate), 1 - state, "change initial switch advantage", witness)

    # If relaxing a mechanic leaves the optimum unchanged, its surviving
    # solution is evidence that the current rules can bypass that mechanic.
    for mechanic, variant in assessment["ablations"].items():
        if mechanic in assessment["necessary"]:
            continue
        witness = variant["solution"]
        if mechanic in ("gates", "switches"):
            route_edits(witness, f"require {mechanic}", close=True)
            for gate in range(2):
                offer(("initial_gates", gate), 0, f"require {mechanic}", witness)
        elif mechanic in ("energy", "recharge"):
            offer(("initial_energy",), max(1, model["initial_energy"] - 1),
                  f"require {mechanic}", witness)
            route_edits(witness, f"require {mechanic}")

    if assessment["reason"] == "unsolved":
        if result["best_steps"] is None:
            offer(("initial_energy",), min(model["capacity"], model["initial_energy"] + 1),
                  "restore feasibility")
            offer(("capacity",), min(8, model["capacity"] + 1), "restore feasibility")
        elif result["best_steps"] < domain.MIN_STEPS[model["level"] - 1]:
            route_edits(result["solution"], "remove too-short solution", close=True)
        else:
            route_edits(result["solution"], "shorten overlong solution", cheaper=True)

    # Gate conditions, charging position and non-start route costs are local
    # escape edits when no single failed gate supplies a usable path.
    for index, (a, _b, cost, _gate) in enumerate(model["routes"]):
        if a != 0:
            for value in (max(1, cost - 1), min(4, cost + 1)):
                offer(("routes", index, 2), value, "alternative continuation", result["solution"])
        for value in (-1, 0, 1):
            offer(("routes", index, 3), value, "route availability", result["solution"])
    for at in range(1, len(model["names"]) - 1):
        offer(("charger",), at, "charging access", result["solution"])
    return edits


def apply_edit(model, edit):
    changed = deepcopy(model)
    target = changed
    for part in edit["path"][:-1]:
        target = target[part]
    if target[edit["path"][-1]] != edit["before"]:
        raise ValueError("Repair does not match its parent model")
    target[edit["path"][-1]] = edit["after"]
    return changed


def propose(names, level, rng, *, mode="guided", budget=PROPOSAL_BUDGET):
    domain._validate_names(names)
    if type(level) is not int or level not in (1, 2, 3) or len(names) != level + 3:
        raise ValueError("State planning requires level+3 location names")
    if mode not in ("guided", "restart"):
        raise ValueError("Unknown planning invention mode")
    if type(budget) is not int or not 0 <= budget <= PROPOSAL_BUDGET:
        raise ValueError("Invalid planning invention budget")
    telemetry = {"version": VERSION, "mode": mode, "budget": budget, "model_evaluations": 0,
                 "graph_evaluations": 0, "restarts": 0, "repairs_evaluated": 0,
                 "rejections": dict.fromkeys(("shape", "unsolved", "choice", "mechanics",
                                               "strategy", "duplicate"), 0),
                 "accepted_via": None, "repair_history": []}
    beam, seen = [], set()
    for attempt in range(budget):
        parent, edit, history = None, None, []
        beam = [entry for entry in beam if entry["edits"]]
        if mode == "guided" and beam and attempt % RESTART_INTERVAL:
            parent = rng.choice(beam[:4])
            edit = parent["edits"].pop()
            model = apply_edit(parent["model"], edit)
            history = parent["history"]
            telemetry["repairs_evaluated"] += 1
            try:
                domain._validate(model)
            except ValueError:
                model = None
        else:
            model = domain._sample(names, level, rng)
            telemetry["restarts"] += 1
        telemetry["model_evaluations"] += 1
        key = physical_key(model) if model is not None else None
        if key in seen:
            telemetry["rejections"]["duplicate"] += 1
            continue
        if key is not None:
            seen.add(key)
        assessment = evaluate(model)
        telemetry["graph_evaluations"] += assessment["graph_evaluations"]
        reason = assessment["reason"]
        if parent is not None and model is not None:
            history = [*history, {"parent": physical_key(parent["model"]), "child": key,
                                 "parent_model": deepcopy(parent["model"]),
                                 "child_model": deepcopy(model),
                                 "edit": edit, "before_score": list(parent["assessment"]["score"]),
                                 "after_score": list(assessment["score"])}]
        if reason is None:
            result = assessment["result"]
            options = [f"move_0_{b}" for a, b, _, _ in model["routes"] if a == 0] + ["switch_0"]
            rng.shuffle(options)
            telemetry.update(accepted_via="repair" if parent else "restart",
                             repair_history=history)
            model.update(design_version=VERSION, strategy=STRATEGY, options=options,
                         answer_action=result["optimal_first_actions"][0],
                         best_steps=result["best_steps"], solution=result["solution"],
                         search=deepcopy(telemetry))
            return model
        telemetry["rejections"][reason] += 1
        if (mode == "guided" and model is not None and len(history) < MAX_REPAIR_DEPTH
                and assessment["result"]["best_steps"] is not None
                and (parent is None or assessment["score"] > parent["assessment"]["score"]
                     or len(history) < 2)):
            edits = _repairs(model, assessment)
            rng.shuffle(edits)
            edits.sort(key=lambda e: e["reason"] not in
                       ("alternative continuation", "route availability", "charging access"))
            beam.append({"model": model, "assessment": assessment, "history": history,
                         "key": key, "edits": edits})
            beam.sort(key=lambda item: (item["assessment"]["score"], len(item["edits"])),
                      reverse=True)
            del beam[BEAM_SIZE:]
    raise InventionExhausted(telemetry)
