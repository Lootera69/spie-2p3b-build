"""Whole-episode claims checked against the separate raw-rule audit oracle."""

from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from random import Random

import pytest
from tools.benchmark_state_planning import committed_costs, domain_graph, initial, oracle, shortest

from spie.expr import Const
from spie.forge.corpus import compact
from spie.questions.brainbloom import planning_experience as experience
from spie.questions.brainbloom import state_planning as domain
from spie.questions.brainbloom import state_planning_variety as variety


def replay_raw(graph, start, actions):
    state, states = tuple(start), [list(start)]
    for action in actions:
        state = graph[state][action]
        states.append(list(state))
    return states


def raw_optimal_actions(model, graph, state):
    best, _, _ = shortest(model, graph, state)
    return sorted(
        action
        for action, target in graph[state].items()
        if (cost := shortest(model, graph, target)[0]) is not None and cost + 1 == best
    )


def raw_decision_range(model, graph):
    """Enumerate shortest full episodes without using production graph helpers."""
    remaining = {state: shortest(model, graph, state)[0] for state in graph}
    counts = []

    def visit(state, count):
        if remaining[state] == 0:
            counts.append(count)
            return
        costs = [
            value for value in committed_costs(model, graph, state).values() if value is not None
        ]
        count += len(costs) >= 2 and len(set(costs)) >= 2
        for target in graph[state].values():
            if remaining[target] == remaining[state] - 1:
                visit(target, count)

    visit(initial(model), 0)
    return min(counts), max(counts)


@pytest.mark.parametrize("level", (1, 2, 3))
@pytest.mark.parametrize("profile", variety.PROFILES)
def test_every_profile_preserves_gates_and_whole_episode_target(level, profile):
    model = experience.propose(
        list("ABCDEF")[: level + 3], level, Random(17), requested_profile=profile
    )
    report = experience.certify(model)
    expected = oracle(model)
    assert model["version"] == domain.VERSION
    assert model["design_version"] == variety.VERSION
    assert model["experience_version"] == experience.VERSION
    assert model["strategy"] == profile
    assert model["best_steps"] == report["dimensions"]["solution_steps"] == expected["best_steps"]
    assert model["answer_action"] == expected["optimal_first_actions"][0]
    assert model["solution"] == expected["solution"]
    assert report["meets_target"]
    assert raw_decision_range(model, expected["graph"]) == (
        report["dimensions"]["minimum_meaningful_decisions"],
        report["dimensions"]["maximum_meaningful_decisions"],
    )
    for mechanic in domain.MECHANICS:
        variant = oracle(model, relaxed=mechanic)
        assert (variant["best_steps"], variant["optimal_first_actions"]) != (
            expected["best_steps"],
            expected["optimal_first_actions"],
        )
        assert report["ablations"][mechanic] == {
            "best_steps": variant["best_steps"],
            "optimal_first_actions": variant["optimal_first_actions"],
        }
    for decision in report["decisions"]:
        state = tuple(decision["state"])
        assert decision["optimal_actions"] == raw_optimal_actions(model, expected["graph"], state)
        costs = committed_costs(model, expected["graph"], state)
        for action in decision["actions"]:
            assert action["committed_steps"] == costs[action["action"]]
            if action["committed_steps"] is not None:
                states = replay_raw(expected["graph"], state, action["committed_solution"])
                assert states == action["committed_states"]
                assert states[-1][0] == level + 2
                assert len(states) == action["committed_steps"] + 1
    assert report["causal_links"]
    for link in report["causal_links"]:
        source = tuple(link["earlier_state"])
        actual = replay_raw(expected["graph"], source, link["chosen_prefix"])
        rival = replay_raw(expected["graph"], source, link["alternative_prefix"])
        assert actual == link["chosen_prefix_states"]
        assert rival == link["alternative_prefix_states"]
        assert actual[-1] == link["later_state"]
        assert rival[-1] == link["alternative_later_state"]
        assert actual[-1][0] == rival[-1][0]
        assert actual[-1] != rival[-1]
        assert link["chosen_action"] != link["alternative_action"]
        assert (
            raw_optimal_actions(model, expected["graph"], tuple(actual[-1]))
            == (link["later_optimal_actions"])
        )
        assert (
            raw_optimal_actions(model, expected["graph"], tuple(rival[-1]))
            == (link["alternative_later_optimal_actions"])
        )
        assert link["later_optimal_actions"] != link["alternative_later_optimal_actions"]
        for label, prefix in (("chosen", actual), ("alternative", rival)):
            completion = replay_raw(expected["graph"], prefix[-1], link[f"{label}_completion"])
            assert completion == link[f"{label}_completion_states"]
            assert completion[-1][0] == level + 2
        # The rival prefix/completion really is a shortest committed continuation.
        costs = committed_costs(model, expected["graph"], source)
        assert (
            len(link["alternative_prefix"]) + len(link["alternative_completion"])
            == (costs[link["alternative_action"]])
        )


def test_search_retains_best_compared_candidate_and_does_not_reward_longer_traps():
    model = experience.propose(list("ABCDE"), 2, Random(29), requested_profile="switch-first")
    diagnostic = model["experience_search"]
    comparisons = diagnostic["comparisons"]
    assert diagnostic["model_evaluations"] == experience.PROPOSAL_BUDGET
    assert diagnostic["best_rank"] == max(row["rank"] for row in comparisons)
    selected = next(row for row in comparisons if row["attempt"] == diagnostic["selected_attempt"])
    assert selected["rank"] == diagnostic["best_rank"]
    assert diagnostic["rejections"]["not_better"] > 0
    assert diagnostic["selected_attempt"] < comparisons[-1]["attempt"]
    assert diagnostic["best_rank"][2:] == [
        -diagnostic["best_dimensions"][key]
        for key in (
            "trap_choices_on_optimal_episodes",
            "maximum_forced_steps",
            "rule_rows",
            "solution_steps",
        )
    ]


def test_profile_selected_uniformly_before_synthesis_and_replay_is_deterministic():
    for seed in (11, 17, 29):
        expected = Random(seed).choice(variety.PROFILES)
        first = experience.propose(list("ABCD"), 1, Random(seed))
        second = experience.propose(list("ABCD"), 1, Random(seed))
        assert first == second
        assert first["strategy"] == expected
        assert first["experience_search"]["profile_selection"] == "uniform-before-synthesis"


def test_certificate_ignores_claimed_quality_answers_and_search():
    model = experience.propose(list("ABCD"), 1, Random(11))
    expected = experience.certify(model)
    altered = deepcopy(model)
    altered.update(
        answer_action="invented",
        best_steps=999,
        solution=["invented"],
        experience_search={"quality": "perfect", "best_dimensions": {"causal_links": 999}},
    )
    assert experience.certify(altered) == expected
    with pytest.raises(RuntimeError, match="answer, optimum or witness"):
        domain.check(altered)
    assert domain.check(model)["smt"]["different_first_action"] == "unsat"


def test_compiler_mismatch_is_rejected(monkeypatch):
    model = experience.propose(list("ABCD"), 1, Random(17))
    compile_original = domain.compile_model

    def altered_compiler(*args, **kwargs):
        puzzle = compile_original(*args, **kwargs)
        return replace(puzzle, objective=replace(puzzle.objective, goal=Const(True)))

    monkeypatch.setattr(domain, "compile_model", altered_compiler)
    with pytest.raises(RuntimeError, match="initial state or goals"):
        experience.certify(model)


def test_certification_does_not_reuse_the_proposal_interpreter(monkeypatch):
    model = experience.propose(list("ABCD"), 1, Random(11))
    expected = experience.certify(model)

    def forbidden(*args, **kwargs):
        raise AssertionError("Independent certification reused the proposal interpreter")

    for name in ("_graph", "_analyse_graph", "_successors", "solve"):
        monkeypatch.setattr(domain, name, forbidden)
    assert experience.certify(model) == expected


def test_causal_claim_cannot_be_inferred_from_state_difference_alone():
    template, _ = variety._foundation(list("ABCDE"), 2, "remote-switch-first", Random(17))
    model = experience._foundation_at(template, 1)
    report = experience.evaluate(model)
    assert report["dimensions"]["minimum_meaningful_decisions"] >= 2
    assert report["causal_links"] == []
    model["experience_version"] = experience.VERSION
    with pytest.raises(ValueError, match="episode decision target"):
        experience.certify(model)


@pytest.mark.parametrize("profile", variety.PROFILES)
def test_zero_budget_exhaustion_keeps_requested_profile(profile):
    with pytest.raises(experience.ExperienceExhausted) as failure:
        experience.propose(list("ABCD"), 1, Random(17), requested_profile=profile, budget=0)
    assert isinstance(failure.value, domain.ProposalExhausted)
    assert failure.value.search["requested_profile"] == profile
    assert failure.value.search["model_evaluations"] == 0


def test_exhaustion_never_weakens_quality_or_changes_profile(monkeypatch):
    monkeypatch.setattr(variety, "_assess", lambda model: (None, "profile", 5))
    with pytest.raises(experience.ExperienceExhausted) as failure:
        experience.propose(list("ABCD"), 1, Random(17), requested_profile="switch-first", budget=7)
    assert failure.value.search["requested_profile"] == "switch-first"
    assert failure.value.search["model_evaluations"] == 7
    assert failure.value.search["rejections"]["profile"] > 0


def test_policies_report_ties_failures_and_replayable_complete_episode_traces():
    model = experience.propose(list("ABCD"), 1, Random(29))
    graph = domain_graph(model)
    report = experience.certify(model)
    assert {row["policy"] for row in report["policy_checks"]} == set(experience.POLICIES)
    for row in report["policy_checks"]:
        assert row["probability_encoding"] == "exact-rational-string"
        assert Fraction(row["optimal_probability"]) <= Fraction(row["success_probability"])
        assert (
            sum(
                Fraction(row[key])
                for key in ("success_probability", "dead_end_probability", "step_limit_probability")
            )
            == 1
        )
        assert replay_raw(graph, initial(model), row["example_actions"]) == row["example_states"]
        assert len(row["example_actions"]) <= experience.POLICY_STEPS
    assert any(row["tied_states"] for row in report["policy_checks"])
    assert any(Fraction(row["step_limit_probability"]) for row in report["policy_checks"])


def test_policy_probabilities_preserve_tiny_possible_outcomes_exactly():
    start, goal = (0, 2, 0, 0, 0), (3, 2, 0, 0, 0)
    model = {"names": list("ABCD"), "routes": [[0, 3, 1, -1]]}
    graph = {start: [("wait", start), ("move_0_3", goal)], goal: []}
    row = next(
        row
        for row in experience._policies(model, graph, start, 1)
        if row["policy"] == "minimum-immediate-energy"
    )
    # Each step independently chooses wait or finish with probability one half.
    survival = Fraction(1, 2**experience.POLICY_STEPS)
    assert Fraction(row["step_limit_probability"]) == survival
    assert Fraction(row["success_probability"]) == 1 - survival
    assert row["optimal_probability"] == "1/2"
    assert row["dead_end_probability"] == "0"
    assert Fraction(row["mean_successful_steps"]) == (
        sum(Fraction(step, 2**step) for step in range(1, experience.POLICY_STEPS + 1))
        / (1 - survival)
    )


def test_certificate_survives_actual_javascript_json_roundtrip():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser serialization regression")
    model = experience.propose(list("ABCD"), 1, Random(11))
    expected = {"model": model, "certificate": experience.certify(model)}
    script = (
        "let s='';process.stdin.on('data',c=>s+=c);"
        "process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))));"
    )
    result = subprocess.run(
        [node, "-e", script],
        input=compact(expected),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        timeout=20,
    )
    assert compact(json.loads(result.stdout)) == compact(expected)


@pytest.mark.parametrize("budget", (-1, True, 49, 1.5))
def test_invalid_budgets_are_rejected(budget):
    with pytest.raises(ValueError, match="budget"):
        experience.propose(list("ABCD"), 1, Random(1), budget=budget)
