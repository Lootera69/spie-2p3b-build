"""An explicit strategy claim must survive independent graph search, including ties."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest
from tools.benchmark_state_planning import domain_graph, initial, oracle, shortest

from spie import search
from spie.interpreter import run
from spie.questions.brainbloom import planning_strategy, state_planning


@pytest.fixture
def investment():
    # The two one-energy options both work in six actions. Spending two energy
    # immediately reaches the charger sooner and permits a five-action plan.
    return {"version": state_planning.VERSION,
            "names": ["Start", "Charge", "Detour", "Goal"], "level": 1,
            "capacity": 7, "initial_energy": 3, "initial_gates": [0, 1], "charger": 1,
            "routes": [[0, 1, 2, 1], [0, 2, 1, -1], [0, 3, 4, -1],
                       [1, 0, 2, 0], [2, 0, 3, -1], [2, 1, 1, -1], [2, 3, 3, -1]],
            "switches": [[0, 3, 1], [1, 3, 1]]}


def test_all_cheapest_ties_are_successful_but_strictly_slower(investment):
    certificate = planning_strategy.certify(investment)
    assert certificate["optimal_first_action"] == "move_0_1"
    assert certificate["best_steps"] == 5
    assert certificate["optimal_immediate_energy"] == 2
    assert certificate["minimum_immediate_energy"] == 1
    assert certificate["minimum_extra_steps"] == 1
    assert certificate["cheapest_first_actions"] == ["move_0_2", "switch_0"]
    assert set(certificate["first_action_results"]) == {"move_0_1", "move_0_2", "switch_0"}
    for action in certificate["cheapest_first_actions"]:
        row = certificate["first_action_results"][action]
        assert row["unrestricted"]["best_steps"] == row["committed"]["best_steps"] == 6
        assert row["extra_steps"] == 1


def test_certificate_matches_separate_raw_domain_oracle_and_witness_replay(investment):
    certificate = planning_strategy.certify(investment)
    expected = oracle(investment)
    assert expected["optimal_first_actions"] == [certificate["optimal_first_action"]]
    assert expected["best_steps"] == certificate["best_steps"]
    assert expected["reachable_states"] == certificate["reachable_states"]
    assert expected["optimal_plan_count"] == 2  # The entire plan need not be unique.
    graph, start = domain_graph(investment), initial(investment)
    dominated = {state for state in graph if state[0] == start[0] and state[2:4] == start[2:4]
                 and state[1] <= start[1] and state[4] >= start[4]}
    puzzle = state_planning.compile_model(investment)
    for action, row in certificate["first_action_results"].items():
        assert row["unrestricted"]["best_steps"] == expected["first_costs"][action]
        assert row["committed"]["best_steps"] == expected["committed_first_costs"][action]
        assert row["immediate_energy"] == start[1] - graph[start][action][1]
        for field, forbidden in (("unrestricted", frozenset()), ("committed", dominated)):
            cost, _, witness = shortest(investment, graph, graph[start][action], forbidden)
            assert row[field]["best_steps"] == cost + 1
            assert row[field]["solution"] == [action, *witness]
            replay = run(puzzle, row[field]["solution"])
            assert replay.reached_goal
            assert row[field]["solution_states"] == [
                [state[var.key] for var in puzzle.variables] for state in replay.states]


def test_authored_answers_diagnostics_and_certificates_are_never_trusted(investment, monkeypatch):
    expected = planning_strategy.certify(investment)
    investment.update(answer_action="switch_0", best_steps=1, solution=["switch_0"],
                      search={"accepted": True}, strategy_certificate={"best_steps": 1})
    before = copy.deepcopy(investment)

    def forbidden(*args, **kwargs):
        pytest.fail("Independent strategy certification called the proposal/domain solver")

    for function in ("solve", "_graph", "_analyse_graph", "_successors", "propose"):
        monkeypatch.setattr(state_planning, function, forbidden)
    assert planning_strategy.certify(investment) == expected
    assert investment == before
    assert json.loads(json.dumps(expected)) == expected


def test_a_single_dead_end_among_cheapest_ties_rejects_the_strategy(investment):
    # After the cheap switch and detour, there is not enough energy for the
    # charger. The other cheapest action still succeeds, so checking one tie
    # would incorrectly accept this model.
    investment["routes"][5][2] = 2
    expected = oracle(investment)
    assert expected["first_costs"]["move_0_2"] == 6
    assert expected["first_costs"]["switch_0"] is None
    with pytest.raises(ValueError, match="Every cheapest.*committed"):
        planning_strategy.certify(investment)


def test_a_cheapest_move_that_only_undoes_itself_is_not_a_tradeoff(investment):
    investment["switches"][0] = [0, 2, 0]
    investment["routes"][1][3] = 1
    expected = oracle(investment)
    assert expected["first_costs"]["switch_0"] == 7
    assert expected["committed_first_costs"]["switch_0"] is None
    with pytest.raises(ValueError, match="Every cheapest.*committed"):
        planning_strategy.certify(investment)


def test_a_cheapest_tie_containing_the_winner_is_not_a_strategy_failure(investment):
    investment["routes"][0][2] = 1
    assert oracle(investment)["optimal_first_actions"] == ["move_0_1"]
    with pytest.raises(ValueError, match="invest more"):
        planning_strategy.certify(investment)


def test_nonunique_best_first_action_is_rejected(investment):
    investment.update(initial_gates=[1, 1],
                      routes=[[0, 1, 1, -1], [0, 2, 1, -1], [0, 3, 4, 0],
                              [1, 3, 1, 0], [2, 3, 1, 1]])
    assert oracle(investment)["optimal_first_actions"] == ["move_0_1", "move_0_2"]
    with pytest.raises(ValueError, match="unique optimal first"):
        planning_strategy.certify(investment)


@pytest.mark.parametrize("strategy", [None, "", "unknown", "INVEST-ENERGY", True])
def test_only_explicit_supported_strategy_identifiers_are_accepted(investment, strategy):
    with pytest.raises(ValueError, match="Unknown planning strategy"):
        planning_strategy.certify(investment, strategy)


def test_invalid_core_rules_are_not_an_unmet_strategy(investment):
    investment["capacity"] = 0
    with pytest.raises(RuntimeError, match="Invalid state-planning rules"):
        planning_strategy.certify(investment)


def test_partial_core_graph_fails_closed(investment, monkeypatch):
    original = search.explore

    def truncated(*args, **kwargs):
        return replace(original(*args, **kwargs), truncated=True)

    monkeypatch.setattr(search, "explore", truncated)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        planning_strategy.certify(investment)


def test_nonunit_compiled_action_costs_fail_closed(investment, monkeypatch):
    original = state_planning.compile_model

    def corrupt(*args, **kwargs):
        puzzle = original(*args, **kwargs)
        return replace(puzzle, actions=tuple(replace(action, cost=2) for action in puzzle.actions))

    monkeypatch.setattr(state_planning, "compile_model", corrupt)
    with pytest.raises(RuntimeError, match="unit-action costs"):
        planning_strategy.certify(investment)


def test_strategy_costs_are_derived_from_compiled_energy_changes(investment, monkeypatch):
    from spie.expr import Assign, Const, Sub, Var

    # Changing the first compiled transition to spend only one energy makes the
    # winner a cheapest tie. Raw route metadata still says it spends two.
    original = state_planning.compile_model

    def cheaper(*args, **kwargs):
        puzzle = original(*args, **kwargs)
        actions = []
        for action in puzzle.actions:
            if action.name == "move_0_1":
                effects = tuple(Assign("energy", Sub(Var("energy"), Const(1)))
                                if effect.key == "energy" else effect for effect in action.effects)
                action = replace(action, effects=effects)
            actions.append(action)
        return replace(puzzle, actions=tuple(actions))

    monkeypatch.setattr(state_planning, "compile_model", cheaper)
    with pytest.raises(ValueError, match="invest more"):
        planning_strategy.certify(investment)
