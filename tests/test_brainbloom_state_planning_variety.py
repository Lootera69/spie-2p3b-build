"""Raw-rule oracle regressions for the revision-10 opening mechanisms."""

from __future__ import annotations

import copy
import random
from collections import deque

import pytest
from tools.benchmark_state_planning import initial, oracle

from spie.questions.brainbloom import state_planning as domain
from spie.questions.brainbloom import state_planning_variety as variety


def all_optimal_plans(model, graph):
    """Enumerate shortest paths from the independent audit interpreter's graph."""
    goals = [s for s in graph if s[0] == len(model["names"]) - 1]
    reverse = {s: [] for s in graph}
    for source, edges in graph.items():
        for target in edges.values():
            reverse[target].append(source)
    remaining, queue = dict.fromkeys(goals, 0), deque(goals)
    while queue:
        state = queue.popleft()
        for previous in reverse[state]:
            if previous not in remaining:
                remaining[previous] = remaining[state] + 1
                queue.append(previous)

    def visit(state, actions):
        if remaining[state] == 0:
            yield actions
        else:
            for action, target in graph[state].items():
                if remaining.get(target) == remaining[state] - 1:
                    yield from visit(target, (*actions, action))

    return list(visit(initial(model), ()))


@pytest.mark.parametrize("level", (1, 2, 3))
@pytest.mark.parametrize("profile", variety.PROFILES)
def test_profiles_keep_physics_all_ablations_and_all_optimal_ordering(level, profile):
    model = variety.propose(
        list("ABCDEF")[: level + 3], level, random.Random(4500 + level), requested_profile=profile
    )
    expected = oracle(model)
    certificate = variety.certify(model)
    proof = domain.check(model)
    assert proof["strategy"] == certificate
    assert proof["smt"]["different_first_action"] == "unsat"
    assert certificate["best_steps"] == expected["best_steps"]
    assert certificate["optimal_first_action"] == expected["optimal_first_actions"][0]
    assert model["strategy"] == model["search"]["requested_profile"] == profile
    assert model["search"]["model_evaluations"] == variety.PROPOSAL_BUDGET
    assert 1 <= model["search"]["graph_evaluations"] <= 5 * variety.PROPOSAL_BUDGET + 3
    assert sum(c is not None for c in expected["committed_first_costs"].values()) >= 2
    assert max(expected["later_committed_choices"]) >= 2
    assert expected["reachable_locations"] == level + 3
    for action, row in certificate["first_action_results"].items():
        assert row["unrestricted"]["best_steps"] == expected["first_costs"][action]
        assert row["committed"]["best_steps"] == expected["committed_first_costs"][action]
    for mechanic in domain.MECHANICS:
        variant = oracle(model, relaxed=mechanic)
        assert (variant["best_steps"], variant["optimal_first_actions"]) != (
            expected["best_steps"],
            expected["optimal_first_actions"],
        )

    paths = all_optimal_plans(model, expected["graph"])
    assert len(paths) == expected["optimal_plan_count"]
    assert all("recharge" in path and any(a.startswith("switch_") for a in path) for path in paths)
    winner = expected["optimal_first_actions"][0]
    if profile == "switch-first":
        assert winner == "switch_0"
    elif profile == "recharge-first":
        assert winner == f"move_0_{model['charger']}"
        for path in paths:
            state = initial(model)
            for number, action in enumerate(path):
                if state[0] == model["charger"] and action.startswith("move_"):
                    assert path.index("recharge") < number
                    break
                state = expected["graph"][state][action]
    elif profile == "remote-switch-first":
        assert winner.startswith("move_")
        remote = int(winner.split("_")[-1])
        assert remote != model["charger"]
        assert all(path.index(f"switch_{remote}") < path.index("recharge") for path in paths)
    else:
        relaxed = oracle(model, relaxed="energy")
        energy = {f"move_{a}_{b}": cost for a, b, cost, _ in model["routes"]}
        rivals = [
            action
            for action in relaxed["optimal_first_actions"]
            if action.startswith("move_")
            and expected["committed_first_costs"].get(action) is not None
            and energy[action] > energy[winner]
        ]
        assert rivals
        assert sorted(rivals) == certificate["evidence"]["higher_energy_committed_rivals"]


@pytest.mark.parametrize("level", (1, 2, 3))
def test_profile_is_selected_before_solving_and_generation_replays(level):
    for seed in range(8):
        expected = random.Random(seed).choice(variety.PROFILES)
        names = [f"Room {i}" for i in range(level + 3)]
        first = variety.propose(names, level, random.Random(seed), budget=12)
        second = variety.propose(names, level, random.Random(seed), budget=12)
        assert first == second
        assert first["strategy"] == expected
        assert first["search"]["profile_selection"] == "uniform-before-synthesis"


def test_selected_profile_failure_is_explicit_and_never_substituted(monkeypatch):
    physical = variety.propose(
        list("ABCD"), 1, random.Random(12), requested_profile="recharge-first", budget=1
    )
    physical["strategy"] = "switch-first"
    monkeypatch.setattr(variety, "_foundation", lambda *args: (copy.deepcopy(physical), 0))
    with pytest.raises(variety.VarietyExhausted) as failure:
        variety.propose(list("ABCD"), 1, random.Random(12), requested_profile="switch-first")
    assert failure.value.search["requested_profile"] == "switch-first"
    assert failure.value.search["model_evaluations"] == 1
    assert failure.value.search["rejections"]["profile"] == 1


def test_certificate_ignores_authored_answers_and_search_but_checker_rejects_them():
    model = variety.propose(list("ABCD"), 1, random.Random(95))
    expected = variety.certify(model)
    broken = copy.deepcopy(model)
    broken.update(
        answer_action="invented",
        best_steps=999,
        solution=["invented"],
        search={"claimed_success": True},
    )
    assert variety.certify(broken) == expected
    with pytest.raises(RuntimeError, match="answer, optimum or witness"):
        domain.check(broken)


@pytest.mark.parametrize("profile", variety.PROFILES)
def test_zero_budget_records_selected_mechanism(profile):
    with pytest.raises(variety.VarietyExhausted) as failure:
        variety.propose(list("ABCD"), 1, random.Random(2), requested_profile=profile, budget=0)
    assert isinstance(failure.value, domain.ProposalExhausted)
    assert failure.value.search["requested_profile"] == profile
    assert failure.value.search["model_evaluations"] == 0


@pytest.mark.parametrize("level", (1, 2, 3))
def test_switch_at_charger_does_not_identify_the_winning_opening(level):
    """Both visible charger/switch arrangements support opposing decisions."""
    names = [f"Room {i}" for i in range(level + 3)]
    seen = {False: set(), True: set()}
    for profile in ("switch-first", "recharge-first"):
        for seed in range(12):
            model = variety.propose(
                names, level, random.Random(seed), requested_profile=profile, budget=1
            )
            at_charger = any(at == model["charger"] for at, _, _ in model["switches"])
            expected = oracle(model)
            role = "switch" if expected["optimal_first_actions"] == ["switch_0"] else "charger"
            seen[at_charger].add(role)
    assert seen == {False: {"switch", "charger"}, True: {"switch", "charger"}}


def test_strategy_certificate_rejects_mismatched_compiler_goals(monkeypatch):
    from dataclasses import replace

    from spie.expr import Const

    model = variety.propose(list("ABCD"), 1, random.Random(97), budget=1)
    original = domain.compile_model

    def broken(*args, **kwargs):
        puzzle = original(*args, **kwargs)
        return replace(puzzle, objective=replace(puzzle.objective, goal=Const(True)))

    monkeypatch.setattr(domain, "compile_model", broken)
    with pytest.raises(RuntimeError, match="initial state or goals"):
        variety.certify(model)


def test_three_legal_moves_and_single_switch_do_not_identify_medium_answer():
    cases = {"three_legal_moves": set(), "single_switch": set()}
    for profile in ("switch-first", "recharge-first"):
        for seed in range(24):
            model = variety.propose(
                list("ABCDE"), 2, random.Random(seed), requested_profile=profile, budget=1
            )
            expected = oracle(model)
            winner = expected["optimal_first_actions"][0]
            role = "switch" if winner == "switch_0" else "charger"
            if sum(a.startswith("move_") for a in expected["first_costs"]) == 3:
                cases["three_legal_moves"].add(role)
            if len(model["switches"]) == 1:
                cases["single_switch"].add(role)
    assert cases["three_legal_moves"] == {"switch", "charger"}
    # A lone start switch cannot be taken as evidence that it should be used now.
    assert "charger" in cases["single_switch"]


@pytest.mark.parametrize(
    "level,profile,index",
    [
        (level, profile, index)
        for (level, profile), layouts in variety._FOUNDATIONS.items()
        for index in range(len(layouts))
    ],
)
def test_every_physical_starting_layout_meets_its_requested_contract(level, profile, index):
    capacity, energy, gates, charger, routes, switches = copy.deepcopy(
        variety._FOUNDATIONS[level, profile][index]
    )
    model = {
        "version": domain.VERSION,
        "design_version": variety.VERSION,
        "strategy": profile,
        "names": list("ABCDEF")[: level + 3],
        "level": level,
        "capacity": capacity,
        "initial_energy": energy,
        "initial_gates": gates,
        "charger": charger,
        "routes": routes,
        "switches": switches,
    }
    expected = oracle(model)
    certificate = variety.certify(model)
    assert domain.MIN_STEPS[level - 1] <= expected["best_steps"] <= domain.MAX_STEPS
    assert len(expected["optimal_first_actions"]) == 1
    assert certificate["optimal_first_action"] == expected["optimal_first_actions"][0]
    assert sum(c is not None for c in expected["committed_first_costs"].values()) >= 2
    assert max(expected["later_committed_choices"]) >= 2
    assert expected["reachable_locations"] == level + 3
    for mechanic in domain.MECHANICS:
        variant = oracle(model, relaxed=mechanic)
        assert (variant["best_steps"], variant["optimal_first_actions"]) != (
            expected["best_steps"],
            expected["optimal_first_actions"],
        )


@pytest.mark.parametrize(
    "kwargs", ({"requested_profile": "detour"}, {"budget": -1}, {"budget": 49}, {"budget": True})
)
def test_invalid_requests_are_not_converted_to_other_profiles(kwargs):
    with pytest.raises(ValueError):
        variety.propose(list("ABCD"), 1, random.Random(1), **kwargs)
