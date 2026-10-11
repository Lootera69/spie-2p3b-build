"""State resources, alternative plans and compiler agreement are audited separately."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import pytest
from tools.benchmark_state_planning import (
    audit_model,
    domain_graph,
    initial,
    measure,
    oracle,
    shortest,
    successors,
)

from spie import solver
from spie.expr import Const
from spie.questions.brainbloom import state_planning


@pytest.fixture
def branching_model():
    # One optimal first action, followed by two equally short complete plans.
    # Consuming the recharge alone is a state change, but need not improve a plan.
    return {"version": state_planning.VERSION, "names": ["Start", "Left", "Right", "Goal"],
            "level": 1, "capacity": 4, "initial_energy": 3, "initial_gates": [0, 0],
            "charger": 2, "routes": [[0, 1, 1, -1], [0, 2, 1, -1], [0, 3, 4, 0],
                                     [1, 3, 1, 0], [2, 3, 1, 1],
                                     [1, 0, 1, -1], [2, 0, 1, -1]],
            "switches": [[0, 3, 0]]}


@pytest.fixture(scope="module", params=[1, 2, 3])
def generated_model(request):
    level = request.param
    return state_planning.propose([f"Place {i}" for i in range(level + 3)], level, random.Random(0))


def test_independent_oracle_counts_shortest_paths_that_merge(branching_model):
    start, left, right, goal = [(location, 0, 0, 0, 0) for location in range(4)]
    graph = {start: {"left": left, "right": right}, left: {"finish_left": goal},
             right: {"finish_right": goal}, goal: {}}
    assert shortest(branching_model, graph, start) == (2, 2, ["left", "finish_left"])


def test_benchmark_propagates_faults_instead_of_reporting_proposal_exhaustion(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("Unexpected domain or compiler fault")

    monkeypatch.setattr(state_planning, "propose", broken)
    with pytest.raises(RuntimeError, match="Unexpected domain or compiler fault"):
        measure(1, 0)


def test_benchmark_records_expected_proposal_exhaustion(monkeypatch):
    monkeypatch.setattr(state_planning, "PROPOSAL_BUDGET", 0)
    row = measure(1, 0)
    assert row["status"] == "rejected"
    assert "bounded search" in row["reason"]


def test_first_action_uniqueness_is_distinct_from_full_plan_uniqueness(branching_model):
    expected = oracle(branching_model)
    assert expected["best_steps"] == 3
    assert expected["optimal_first_actions"] == ["switch_0"]
    assert expected["optimal_plan_count"] == 2
    puzzle = state_planning.compile_model(branching_model)
    solution = solver.solve(puzzle)
    assert solution.solvable and solution.horizon == 3
    assert not solver.check_uniqueness(puzzle, solution).unique
    assert not puzzle.objective.requires_unique
    audit_model(branching_model)


def test_recharge_and_gate_changes_survive_returns_to_the_same_location(branching_model):
    graph = domain_graph(branching_model)
    state = initial(branching_model)
    state = graph[state]["move_0_2"]
    assert state == (2, 2, 0, 0, 0)
    state = graph[state]["recharge"]
    assert state == (2, 4, 0, 0, 1)
    state = graph[state]["move_2_0"]
    assert state == (0, 3, 0, 0, 1)
    state = graph[state]["switch_0"]
    assert state == (0, 3, 1, 1, 1)
    state = graph[state]["move_0_2"]
    assert "recharge" not in graph[state]
    expected = oracle(branching_model)
    assert expected["committed_first_costs"]["move_0_2"] is None
    assert expected["committed_first_costs"]["move_0_1"] is None
    assert expected["first_costs"]["move_0_1"] is not None
    # A larger recharge leaves a net energy gain after returning, so it is a
    # meaningful alternative: charge, return, flip the gates, take the direct exit.
    improved = copy.deepcopy(branching_model)
    improved["capacity"] = 5
    assert oracle(improved)["committed_first_costs"]["move_0_2"] == 5
    audit_model(improved)


def test_recharge_is_optional_single_use_and_cannot_exceed_capacity(branching_model):
    assert "recharge" in successors(branching_model, (2, 0, 0, 0, 0))
    assert "recharge" not in successors(branching_model, (2, 4, 0, 0, 0))
    assert "recharge" not in successors(branching_model, (2, 0, 0, 0, 1))
    assert not successors(branching_model, (3, 3, 1, 1, 0))
    audit_model(branching_model)


@pytest.mark.parametrize("seed", [2, 17, 53])
def test_compiler_matches_whole_raw_graph_across_varied_samples(seed):
    rng = random.Random(seed)
    for level in (1, 2, 3):
        model = state_planning._sample([f"Node {i}" for i in range(level + 3)], level, rng)
        if model is not None:
            audit_model(model)


def test_generated_models_have_exact_answers_and_nontrivial_committed_choices(generated_model):
    reports = audit_model(generated_model)
    expected = reports["baseline"]
    assert expected["optimal_first_actions"] == [generated_model["answer_action"]]
    assert expected["best_steps"] == generated_model["best_steps"]
    assert (state_planning.MIN_STEPS[generated_model["level"] - 1]
            <= expected["best_steps"] <= state_planning.MAX_STEPS)
    committed = expected["committed_first_costs"]
    assert sum(cost is not None for cost in committed.values()) >= 2
    assert max(expected["later_committed_choices"], default=0) >= 2
    assert all(cost is None or cost > expected["best_steps"]
               for action, cost in committed.items() if action != generated_model["answer_action"])
    signature = expected["best_steps"], expected["optimal_first_actions"]
    for mechanic in state_planning.MECHANICS:
        assert (reports[mechanic]["best_steps"], reports[mechanic]["optimal_first_actions"]
                ) != signature
    proof = state_planning.check(generated_model)
    assert proof["agree"]
    assert proof == state_planning.check(copy.deepcopy(generated_model))
    assert state_planning.render(generated_model)["proof"] == proof


def test_generation_is_reproducible_and_structure_ignores_labels(generated_model):
    replay = state_planning.propose(generated_model["names"], generated_model["level"],
                                    random.Random(0))
    assert replay == generated_model
    renamed = copy.deepcopy(generated_model)
    renamed["names"] = [f"Label {i}" for i in range(len(renamed["names"]))]
    assert state_planning.structural_key(renamed) == state_planning.structural_key(generated_model)


def test_structure_ignores_interior_numbering_and_gate_names(branching_model):
    mapped = copy.deepcopy(branching_model)
    remap = {0: 0, 1: 2, 2: 1, 3: 3}
    mapped["charger"] = remap[mapped["charger"]]
    mapped["initial_gates"] = list(reversed(mapped["initial_gates"]))
    mapped["routes"] = [[remap[a], remap[b], cost, (1 - gate if gate >= 0 else -1)]
                        for a, b, cost, gate in mapped["routes"]]
    mapped["switches"] = [[remap[at], {1: 2, 2: 1, 3: 3}[mask], cost]
                          for at, mask, cost in mapped["switches"]]
    assert state_planning.structural_key(branching_model) == state_planning.structural_key(mapped)
    assert oracle(mapped)["best_steps"] == oracle(branching_model)["best_steps"]
    mapped["routes"][0][2] += 1
    assert state_planning.structural_key(branching_model) != state_planning.structural_key(mapped)


@pytest.mark.parametrize("field,value", [
    ("version", "future"), ("capacity", True), ("capacity", 9), ("initial_energy", 0),
    ("initial_energy", 5), ("initial_gates", [True, 0]), ("initial_gates", [0, 2]),
    ("charger", 0), ("charger", 3), ("level", True), ("names", ["A", "a", "B", "C"]),
    ("names", ["Start", " Start", "Other", "Goal"]),
    ("names", ["Start", "Left\nRight", "Other", "Goal"]),
])
def test_bounded_model_schema_rejects_invalid_values(branching_model, field, value):
    branching_model[field] = value
    with pytest.raises(ValueError):
        state_planning.solve(branching_model)
    with pytest.raises(ValueError):
        state_planning.compile_model(branching_model)


@pytest.mark.parametrize("names", [None, "abcd", ["A", "a", "B", "C"],
                                  ["Start", "Left", "Other", "Goal\t"]])
def test_invalid_proposal_names_fail_before_the_bounded_search(names, monkeypatch):
    monkeypatch.setattr(state_planning, "PROPOSAL_BUDGET", 0)
    with pytest.raises(ValueError, match="location names"):
        state_planning.propose(names, 1, random.Random(0))


@pytest.mark.parametrize("alter", [
    lambda model: model["routes"].append(model["routes"][0][:]),
    lambda model: model["routes"][0].__setitem__(2, 0),
    lambda model: model["routes"][0].__setitem__(3, 2),
    lambda model: model["switches"][0].__setitem__(1, 0),
    lambda model: model["switches"][0].__setitem__(2, 2),
])
def test_invalid_route_and_switch_shapes_fail_closed(branching_model, alter):
    alter(branching_model)
    with pytest.raises(ValueError):
        state_planning.solve(branching_model)


@pytest.mark.parametrize("field", ["best_steps", "answer_action", "solution", "options"])
def test_saved_answer_and_witness_are_recomputed(generated_model, field):
    broken = copy.deepcopy(generated_model)
    if field == "best_steps":
        broken[field] += 1
    elif field == "answer_action":
        broken[field] = next(option for option in broken["options"] if option != broken[field])
    elif field == "solution":
        broken[field] = ["not_an_action", *broken[field][1:]]
    else:
        broken[field] = [broken[field][0]] * 4
    with pytest.raises((RuntimeError, ValueError)):
        state_planning.check(broken)


def test_state_and_proposal_limits_reject_uncertified_results(branching_model, monkeypatch):
    monkeypatch.setattr(state_planning, "MAX_STATES", 1)
    with pytest.raises(RuntimeError, match="budget"):
        state_planning.solve(branching_model)
    monkeypatch.setattr(state_planning, "PROPOSAL_BUDGET", 0)
    with pytest.raises(state_planning.ProposalExhausted, match="bounded search"):
        state_planning.propose(branching_model["names"], 1, random.Random(0))


def test_symbolic_check_proves_shorter_horizons_and_exact_first_action(branching_model):
    puzzle = state_planning.compile_model(branching_model)
    expected = state_planning.solve(branching_model)
    assert state_planning._smt_check(puzzle, expected)["different_first_action"] == "unsat"
    for wrong_length in (expected["best_steps"] - 1, expected["best_steps"] + 1):
        with pytest.raises(RuntimeError, match="optimality disagreed"):
            state_planning._smt_check(puzzle, {**expected, "best_steps": wrong_length})
    with pytest.raises(RuntimeError, match="optimality disagreed"):
        state_planning._smt_check(puzzle, {**expected, "optimal_first_actions": ["move_0_1"]})


def test_symbolic_work_limit_fails_closed(branching_model, monkeypatch):
    monkeypatch.setattr(state_planning, "SMT_RESOURCE_LIMIT", 1)
    puzzle = state_planning.compile_model(branching_model)
    with pytest.raises(RuntimeError, match="bounded work"):
        state_planning._smt_check(puzzle, state_planning.solve(branching_model))


def test_incomplete_core_graph_is_not_a_certificate(branching_model, monkeypatch):
    from spie import search

    original = search.explore

    def truncate(*args, **kwargs):
        return replace(original(*args, **kwargs), truncated=True)

    monkeypatch.setattr(search, "explore", truncate)
    with pytest.raises(RuntimeError, match="budget"):
        state_planning._crosscheck(branching_model)


def test_compiler_goal_disagreement_is_not_a_certificate(branching_model, monkeypatch):
    original = state_planning.compile_model

    def corrupt(model, *, relaxed=None):
        puzzle = original(model, relaxed=relaxed)
        return replace(puzzle, objective=replace(puzzle.objective, goal=Const(0)))

    monkeypatch.setattr(state_planning, "compile_model", corrupt)
    with pytest.raises(RuntimeError, match="goals disagreed"):
        state_planning._crosscheck(branching_model)


def test_compiler_transition_disagreement_is_rejected(generated_model, monkeypatch):
    original = state_planning.compile_model

    def corrupt(model, *, relaxed=None):
        puzzle = original(model, relaxed=relaxed)
        target = model["answer_action"]
        actions = tuple(replace(action, precondition=Const(0)) if action.name == target else action
                        for action in puzzle.actions)
        return replace(puzzle, actions=actions)

    monkeypatch.setattr(state_planning, "compile_model", corrupt)
    with pytest.raises(RuntimeError):
        state_planning.check(generated_model)
