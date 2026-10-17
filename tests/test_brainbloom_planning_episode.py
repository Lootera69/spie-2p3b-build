"""Played episodes agree with raw-model transitions, not just a saved witness."""

from __future__ import annotations

import copy
import json
import random
from collections import deque
from dataclasses import replace

import pytest
from tools.benchmark_state_planning import domain_graph, initial, shortest, successors

from spie.expr import Const
from spie.forge.corpus import digest
from spie.questions.brainbloom import planning_episode, state_planning


@pytest.fixture
def model():
    # Two tied continuations after the first switch; recharge/returns allow
    # longer successful paths, and a zero-energy switch permits bounded loops.
    return {
        "version": state_planning.VERSION,
        "names": ["Mercury", "Venus", "Earth", "Mars"],
        "level": 1,
        "capacity": 4,
        "initial_energy": 3,
        "initial_gates": [0, 0],
        "charger": 2,
        "routes": [
            [0, 1, 1, -1],
            [0, 2, 1, -1],
            [0, 3, 4, 0],
            [1, 3, 1, 0],
            [2, 3, 1, 1],
            [1, 0, 1, -1],
            [2, 0, 1, -1],
        ],
        "switches": [[0, 3, 0]],
    }


def _paths(model, graph):
    start = initial(model)
    paths, queue = {start: []}, deque([start])
    while queue:
        state = queue.popleft()
        for action, target in graph[state].items():
            if target not in paths:
                paths[target] = [*paths[state], action]
                queue.append(target)
    return paths


def _tuple(public):
    return (public["location"], public["energy"], *public["gates"], int(public["recharged"]))


def _assert_dependencies(view):
    facts = {fact["id"]: fact for fact in view["facts"]}
    assert len(facts) == len(view["facts"])
    for fact in facts.values():
        assert set(fact.get("depends_on", [])) <= facts.keys(), fact
    for row in [*view["history"], *view["local_actions"]]:
        assert set(row["fact_ids"]) <= facts.keys(), row
    if view["hint"]:
        assert set(view["hint"]["fact_ids"]) <= facts.keys()
    if view["resolution"]:
        assert set(view["resolution"]["fact_ids"]) <= facts.keys()
    return facts


def test_scenario_is_deterministic_bound_to_labels_and_ignores_quiz_metadata(model):
    original = copy.deepcopy(model)
    scenario = planning_episode.create(model)
    assert model == original
    assert json.loads(json.dumps(scenario)) == scenario
    assert planning_episode.create(model) == scenario
    poisoned = {
        **model,
        "best_steps": -1,
        "answer_action": "made_up",
        "solution": ["teleport"],
        "states": ["not a state"],
        "title": "An emergency",
    }
    assert planning_episode.create(poisoned) == scenario
    assert planning_episode.replay(poisoned, scenario, []) == planning_episode.replay(
        model, scenario, []
    )
    assert [row["name"] for row in scenario["rooms"]] == model["names"]
    assert scenario["rooms"][0]["role"] == "dispatch room"
    assert scenario["rooms"][-1]["role"] == "farewell hall"
    assert scenario["rooms"][model["charger"]]["role"] == "charging alcove"
    assert "topic labels" in scenario["introduction"]
    assert model["names"][0] in scenario["objective"]
    assert model["names"][-1] in scenario["objective"]
    assert "Every legal arrival" in scenario["objective"]
    assert scenario["characters"]["robot"]["name"] in scenario["introduction"]
    assert scenario["characters"]["caretaker"]["name"] in scenario["introduction"]
    assert scenario["dialogue"]["kind"] == "expressive; not mechanical evidence"
    facts = {row["id"]: row for row in scenario["source_facts"]}
    assert facts["goal"]["value"] == len(model["names"]) - 1
    assert facts["charger"]["value"] == model["charger"]
    for origin, destination, cost, gate in model["routes"]:
        assert facts[f"route.{origin}.{destination}"]["value"] == {
            "origin": origin,
            "destination": destination,
            "energy": cost,
            "gate": gate,
        }
    for location, mask, cost in model["switches"]:
        assert facts[f"switch.{location}"]["value"] == {
            "location": location,
            "gate_mask": mask,
            "energy": cost,
        }


def test_every_reachable_public_state_and_local_action_matches_raw_oracle(model):
    graph = domain_graph(model)
    scenario = planning_episode.create(model)
    for state, actions in _paths(model, graph).items():
        view = planning_episode.replay(model, scenario, actions)
        assert _tuple(view["state"]) == state
        assert view["state"]["steps"] == len(actions)
        assert set(view["legal_actions"]) == set(successors(model, state))
        assert view["goal_reached"] == (state[0] == len(model["names"]) - 1)
        best, _, _ = shortest(model, graph, state)
        expected = "complete" if best == 0 else "dead_end" if best is None else "in_progress"
        assert view["status"] == expected
        assert view["hint"] is None
        for row in view["local_actions"]:
            assert row["legal"] == (row["id"] in graph[state])
            assert bool(row["reasons"]) != row["legal"]
            if row["legal"]:
                assert _tuple(row["next_state"]) == graph[state][row["id"]]
            else:
                assert row["next_state"] is None
        facts = _assert_dependencies(view)
        current = initial(model)
        for step, action in enumerate(actions, start=1):
            previous = current
            current = graph[current][action]
            event = view["history"][step - 1]
            assert event["action"] == action
            assert _tuple(event["before"]) == previous
            assert _tuple(event["after"]) == current
            assert _tuple(facts[f"state.{step}"]["value"]) == current


def test_every_viable_choice_can_complete_including_later_ties_and_slower_arrivals(model):
    graph, scenario = domain_graph(model), planning_episode.create(model)
    paths = _paths(model, graph)
    optimal_length = shortest(model, graph, initial(model))[0]
    lengths, witnessed_choices = set(), set()
    for state, prefix in paths.items():
        for action, target in graph[state].items():
            remaining, _, suffix = shortest(model, graph, target)
            if remaining is None:
                continue
            actions = [*prefix, action, *suffix]
            view = planning_episode.replay(model, scenario, actions)
            assert view["status"] == "complete"
            assert view["resolution"] is not None
            assert not view["legal_actions"]
            assert not view["local_actions"]
            assert not view["can_append"]
            assert "farewell has arrived" in view["resolution"]["text"]
            lengths.add(len(actions))
            witnessed_choices.add((state, action))
    assert min(lengths) == optimal_length
    assert max(lengths) > optimal_length
    switched = graph[initial(model)]["switch_0"]
    assert (switched, "move_0_1") in witnessed_choices
    assert (switched, "move_0_2") in witnessed_choices


@pytest.mark.parametrize(
    "actions", [None, (), "switch_0", {}, [None], [1], [True], [""], ["a" * 41], ["switch_0"] * 129]
)
def test_malformed_and_oversized_transcripts_fail_before_evaluation(model, actions, monkeypatch):
    scenario = planning_episode.create(model)
    monkeypatch.setattr(state_planning, "_crosscheck", lambda *_: pytest.fail("compiled bad input"))
    with pytest.raises(ValueError, match="Actions must"):
        planning_episode.replay(model, scenario, actions)


@pytest.mark.parametrize("level", [None, True, False, -1, 4, 1.0, "1", [], {}])
def test_malformed_hint_levels_are_rejected(model, level):
    with pytest.raises(ValueError, match="Hint level"):
        planning_episode.replay(model, planning_episode.create(model), [], hint_level=level)


@pytest.mark.parametrize(
    "actions",
    [
        ["teleport"],
        ["move_0_3"],
        ["recharge"],
        ["switch_0", "move_0_1", "move_0_2"],
        ["move_0_2", "recharge", "recharge"],
        ["switch_0", "move_0_1", "move_1_3", "switch_0"],
    ],
)
def test_unknown_illegal_and_post_goal_actions_are_rejected(model, actions):
    with pytest.raises(ValueError, match="unknown or illegal|already completed"):
        planning_episode.replay(model, planning_episode.create(model), actions)


def test_altered_scenarios_are_rejected_without_trusting_content_or_state(model):
    original = planning_episode.create(model)
    alterations = []
    for key, value in (
        ("title", "Urgent emergency"),
        ("id", "forged"),
        ("state", {"location": 3}),
        ("variant", False),
    ):
        altered = copy.deepcopy(original)
        altered[key] = value
        alterations.append(altered)
    altered = copy.deepcopy(original)
    altered["source_facts"][0]["value"] = True  # bool must not equal integer one.
    alterations.append(altered)
    alterations.extend([None, [], {"scenario": original}])
    for scenario in alterations:
        with pytest.raises(ValueError, match="Scenario does not match"):
            planning_episode.replay(model, scenario, [])
    renamed = copy.deepcopy(model)
    renamed["names"][-1] = "Jupiter"
    with pytest.raises(ValueError, match="Scenario does not match"):
        planning_episode.replay(renamed, original, [])


def test_bounded_loops_are_not_a_fictional_loss_or_optimality_requirement(model):
    scenario = planning_episode.create(model)
    view = planning_episode.replay(model, scenario, ["switch_0"] * 128)
    assert view["status"] == "in_progress"
    assert view["history_limit"] == 128
    assert not view["can_append"]
    assert view["resolution"] is None
    slow = ["switch_0"] * 125 + ["move_0_1", "move_1_3"]
    complete = planning_episode.replay(model, scenario, slow)
    assert complete["status"] == "complete"
    assert "125 times" in complete["resolution"]["replay_summary"]
    assert "127 actions" in complete["resolution"]["replay_summary"]


def test_hint_ladder_uses_current_public_facts_and_only_explicit_step_help_names_action(model):
    scenario, graph = planning_episode.create(model), domain_graph(model)
    level_one_texts, level_two_texts = set(), set()
    for current, actions in _paths(model, graph).items():
        best, _, _ = shortest(model, graph, current)
        for level in (1, 2, 3):
            view = planning_episode.replay(model, scenario, actions, hint_level=level)
            hint = view["hint"]
            facts = _assert_dependencies(view)
            assert hint["level"] == level
            assert f"state.{len(actions)}" in hint["fact_ids"]
            if level <= 2:
                assert "action" not in hint
                assert "hint.next" not in facts
                assert "shortest" not in hint["text"]
                assert "remaining actions" not in hint["text"]
                assert not any(action in hint["text"] for action in graph[current] if "_" in action)
                assert not any(
                    state_planning.action_label(model, action) in hint["text"]
                    for action in graph[current]
                )
                if best not in (None, 0):
                    (level_one_texts if level == 1 else level_two_texts).add(hint["text"])
                    assert all(
                        facts[ref]["kind"] in ("source", "replay") for ref in hint["fact_ids"]
                    )
            elif best not in (None, 0):
                assert hint["action"] in graph[current]
                remaining = shortest(model, graph, graph[current][hint["action"]])[0]
                assert remaining == best - 1
                assert facts["hint.next"]["value"]["action"] == hint["action"]
            else:
                assert "action" not in hint
    assert len(level_one_texts) >= 4
    assert len(level_two_texts) >= 4


@pytest.mark.parametrize("version", ("planning-experience-v1", "planning-experience-v4"))
def test_default_payload_and_early_help_do_not_expose_saved_or_computed_witness(model, version):
    model = {**model, "experience_version": version}
    forbidden = {
        "solution",
        "solution_states",
        "answer_action",
        "best_steps",
        "first_costs",
        "optimal_first_actions",
        "committed_first_costs",
        "begins_shortest_continuation",
    }

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    for hint_level in (0, 1, 2):
        view = planning_episode.replay(
            model, planning_episode.create(model), [], hint_level=hint_level
        )
        assert not forbidden & keys(view)
        assert view["resolution"] is None


def test_recharge_and_gate_state_persist_across_returns(model):
    actions = ["move_0_2", "recharge", "move_2_0", "switch_0", "move_0_2"]
    view = planning_episode.replay(model, planning_episode.create(model), actions)
    assert _tuple(view["state"]) == (2, 2, 1, 1, 1)
    recharge = next(row for row in view["local_actions"] if row["id"] == "recharge")
    assert not recharge["legal"]
    assert recharge["reasons"] == ["The single recharge has already been used."]
    assert "single recharge is now used" in view["history"][1]["text"]


def test_core_transition_and_goal_faults_fail_closed(model, monkeypatch):
    compiler = state_planning.compile_model

    def corrupt(model, *, relaxed=None):
        puzzle = compiler(model, relaxed=relaxed)
        return replace(puzzle, objective=replace(puzzle.objective, goal=Const(0)))

    monkeypatch.setattr(state_planning, "compile_model", corrupt)
    with pytest.raises(RuntimeError, match="goals disagreed"):
        planning_episode.replay(model, planning_episode.create(model), [])


@pytest.mark.parametrize("level", [1, 2, 3])
def test_scenario_and_runtime_cover_other_valid_physical_layouts(level):
    rng = random.Random(17)
    names = [f"Topic {i}" for i in range(level + 3)]
    model = None
    while model is None:
        model = state_planning._sample(names, level, rng)
    graph = domain_graph(model)
    scenario = planning_episode.create(model)
    for current, actions in list(_paths(model, graph).items())[:: max(1, len(graph) // 8)]:
        view = planning_episode.replay(model, scenario, actions, hint_level=2)
        assert _tuple(view["state"]) == current
        assert set(view["legal_actions"]) == set(graph[current])
        _assert_dependencies(view)


# Captured from the untouched revision-12 episode implementation before adding
# revision 13. These fixed outputs protect story, hints and replay metadata.
_REVISION12 = (
    ([], (
        "88053d5360cd7365edfb1f6b11e19d421d6cd3cabe96bea3d5957d6ceff6cc44",
        "e899d67e602a7c03aa9fd3251edc8951edf9ca0d3ee35f1b7b6fd6dc1de48e40",
        "51579448c92ba7d468db73cca61680cf4fa20c926d1c20e487daaa256533f39d",
        "74940f147a4e21146489f1fb0a44b5b0ef196c1f7e932428e45bda361efb4c54",
    )),
    (["switch_0"], (
        "59885eabd11880ffffd6f076fec1e5ef3077b20c2a23ef1e39b271afcfb88a15",
        "4774745871975194e6a5ed8d6403ecd86f384a185e247994a07a0e28f404ca69",
        "c906e8d242c6e54ec02ad9e8e347c2cf33756c9d3fb3434207a968e532e2ffc4",
        "0275458a384e9601af8da7d76f7545534c774a1d5e89044bd7ebd7335c2e8bc7",
    )),
    (["move_0_2", "recharge", "move_2_0", "switch_0", "move_0_1", "move_1_3"], (
        "435579402ae661d49b2bd43a1864813298597b604918879844ab56df95600fdd",
        "2fe8f91bb1b8eabc6dd6adbfeb4c4e58227441eddf17f1787c2eaca00e241e8c",
        "354e339cc03cd0536a4f6e46e812ce24e82f069e83c726862e1f6973915aa75f",
        "064a01f867d2f70f075f4c392103eda2af989a5841a5c6b84115bad1441e5ea6",
    )),
)


@pytest.mark.parametrize("actions,expected", _REVISION12)
def test_revision12_full_replay_keeps_its_frozen_output(model, actions, expected):
    physical = {**model, "experience_version": "planning-experience-v2"}
    scenario = planning_episode.create(physical)
    assert digest(scenario) == "625a6bc2a822bb63c7d90bddbe496766d8fb2adef5c40943a81f0dd2f5b60394"
    for level, fingerprint in enumerate(expected):
        assert digest(planning_episode.replay(
            physical, scenario, actions, hint_level=level,
        )) == fingerprint


# Captured from artifacts/engine-capability-v14/2026-10-15/baseline/src,
# before changing revision dispatch, objective wording, or scenario identity.
_REVISION13 = (
    ([], (
        "768c2c3ed940a7fa2133b5c414a229b5b2fa14a4190c408812c4bc27ee08555a",
        "a7bce5777cc9b181fda9d068cfa7d1ff6c8cea3e968e6edca1a043a3269a2894",
        "da028dfa9c13aa3b8beda632995c529195a8c4e8b261b57a0dd7e4b7e7ad79bf",
        "3025ef285eeeb1569951464f4770099d2a6af99fd92f8828ac6b2d6ce9829d8f",
    )),
    (["switch_0"], (
        "bbc724651c4130fa5dc075e34bd266ecc3d662a83993d69d72e5cc0f520d757a",
        "94b28cf8024ff3a40da0a7c38be1c87597b5f6c57f58d48ca78df74e42e550ca",
        "5ddfd02dea9211c991b12947832aed6474f8bee11c844478638f6ae6523fbac1",
        "83445b240ff62e245b4a476d1e9881fdf29195fa75e808b9dc0e9c73629a7a7f",
    )),
    (["move_0_2", "recharge", "move_2_0", "switch_0", "move_0_1", "move_1_3"], (
        "0ba6a8d31fd11912a35823bb3b980789d0752b7fa6b1203f40fa6e5cef334552",
        "3f511a859306f377a95798dfe74d0a65507bd5cdb4ca131bd4bc0c4136e9c6f9",
        "f8a4b419b9a029656ed535411514aa162ce9687ea387da79f9b645cfb6be61b4",
        "4a8869dd3a925b2739f7c54c810d170d318c0b6e888ddf94f72effe67cb36a72",
    )),
)


@pytest.mark.parametrize("actions,expected", _REVISION13)
def test_revision13_full_replay_keeps_its_frozen_output(model, actions, expected):
    physical = {**model, "experience_version": "planning-experience-v3"}
    scenario = planning_episode.create(physical)
    assert digest(scenario) == "f4ab5a5d348f89eb21f00d5e99e803906ccabf2b8f0da13fa9265ea7f40895e9"
    for level, fingerprint in enumerate(expected):
        assert digest(planning_episode.replay(
            physical, scenario, actions, hint_level=level,
        )) == fingerprint


@pytest.mark.parametrize("version", ("planning-experience-v6", "unknown", None, 4))
def test_unknown_experience_versions_cannot_fall_back_to_an_old_episode(model, version):
    scenario = planning_episode.create(model)
    physical = {**model, "experience_version": version}
    with pytest.raises(ValueError, match="Unsupported planning experience version"):
        planning_episode.create(physical)
    with pytest.raises(ValueError, match="Unsupported planning experience version"):
        planning_episode.replay(physical, scenario, [])
    with pytest.raises(ValueError, match="Unsupported planning experience version"):
        state_planning.check(physical)


def test_revision14_efficiency_is_optional_and_every_viable_arrival_still_succeeds(model):
    physical = {**model, "experience_version": "planning-experience-v4", "initial_energy": 2}
    graph, scenario = domain_graph(physical), planning_episode.create(physical)
    previous = planning_episode.create({**physical, "experience_version": "planning-experience-v3"})
    assert "Every legal arrival succeeds" in scenario["objective"]
    assert "Optional challenge: use fewer actions" in scenario["objective"]
    assert len(scenario["objective"].split()) <= len(previous["objective"].split())
    assert physical["names"][-1] in scenario["objective"]
    assert scenario["source_facts"] == previous["source_facts"]
    lengths, energies, outcomes = set(), set(), set()
    for state, prefix in _paths(physical, graph).items():
        for action, target in graph[state].items():
            remaining, _, suffix = shortest(physical, graph, target)
            if remaining is None:
                continue
            actions = [*prefix, action, *suffix]
            view = planning_episode.replay(physical, scenario, actions, hint_level=3)
            assert view["status"] == "complete" and view["goal_reached"]
            assert not view["can_append"] and not view["local_actions"]
            assert view["hint"]["text"] == "Delivery complete."
            assert view["history"][-1]["dialogue"] == {
                "speaker": scenario["characters"]["robot"]["name"],
                "text": f"At {physical['names'][-1]}. {view['resolution']['dialogue']['text']}",
                "kind": "expressive; not mechanical evidence",
            }
            lengths.add(len(actions))
            energies.add(view["state"]["energy"])
            outcomes.add(view["resolution"]["text"])
    assert 0 in energies
    assert max(lengths) > min(lengths)
    assert outcomes == {f"At {physical['names'][-1]}, {scenario['resolution']['outcome']}"}


def test_revision14_long_play_and_empty_battery_do_not_introduce_a_deadline_or_arrival_loss(model):
    physical = {**model, "experience_version": "planning-experience-v4", "initial_energy": 2}
    scenario = planning_episode.create(physical)
    bounded = planning_episode.replay(physical, scenario, ["switch_0"] * 128)
    assert bounded["status"] == "in_progress" and not bounded["can_append"]
    assert bounded["resolution"] is None
    actions = ["switch_0"] * 125 + ["move_0_1", "move_1_3"]
    complete = planning_episode.replay(physical, scenario, actions)
    assert complete["status"] == "complete" and complete["state"]["energy"] == 0
    assert "127 actions" in complete["resolution"]["replay_summary"]
    assert "125 switch uses" in complete["resolution"]["replay_summary"]
    assert "Energy remaining: 0." in complete["resolution"]["replay_summary"]
    with pytest.raises(ValueError, match="already completed"):
        planning_episode.replay(physical, scenario, [*actions, "switch_0"])


def test_each_revision_binds_the_concise_story_identity_to_the_actual_model_version(model):
    versions = (
        "planning-experience-v1", "planning-experience-v2", "planning-experience-v3",
        "planning-experience-v4", "planning-experience-v5",
    )
    physical = [{**model, "experience_version": version} for version in versions]
    scenarios = [planning_episode.create(value) for value in physical]
    assert [scenario["version"] for scenario in scenarios] == [
        "planning-episode-v1", "planning-episode-v2", "planning-episode-v2", "planning-episode-v3",
        "planning-episode-v4",
    ]
    assert len({scenario["id"] for scenario in scenarios}) == 5
    assert scenarios[2]["source_facts"] == scenarios[1]["source_facts"]
    assert len(scenarios[2]["introduction"].split()) < len(scenarios[0]["introduction"].split())
    for index, value in enumerate(physical):
        for other, scenario in enumerate(scenarios):
            if index != other:
                with pytest.raises(ValueError, match="canonical episode"):
                    planning_episode.replay(value, scenario, [])


@pytest.mark.parametrize("version", ("planning-experience-v3", "planning-experience-v4", "planning-experience-v5"))
def test_every_revision13_and14_state_and_hint_preserves_the_public_mechanics(model, version):
    physical = {**model, "experience_version": version}
    scenario, graph = planning_episode.create(physical), domain_graph(physical)
    for current, actions in _paths(physical, graph).items():
        for level in (0, 1, 2, 3):
            view = planning_episode.replay(physical, scenario, actions, hint_level=level)
            assert _tuple(view["state"]) == current
            assert view["state"]["steps"] == len(actions)
            assert set(view["legal_actions"]) == set(graph[current])
            assert view["goal_reached"] == (current[0] == len(model["names"]) - 1)
            facts = _assert_dependencies(view)
            if level in (1, 2):
                assert "action" not in view["hint"] and "hint.next" not in facts
                assert "shortest" not in view["hint"]["text"]
            elif level == 3:
                best = shortest(physical, graph, current)[0]
                if best not in (None, 0):
                    action = view["hint"]["action"]
                    assert shortest(physical, graph, graph[current][action])[0] == best - 1
            if view["goal_reached"]:
                assert view["resolution"]["text"] == (
                    f"At {model['names'][-1]}, {scenario['resolution']['outcome']}"
                )
                assert not view["can_append"] and not view["local_actions"]
