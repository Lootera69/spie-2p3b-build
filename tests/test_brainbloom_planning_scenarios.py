"""Story variation preserves the physical game and revision-11 replay exactly."""

from __future__ import annotations

import copy
from collections import deque

import pytest
from tools.benchmark_state_planning import domain_graph, initial, shortest

from spie.forge.corpus import digest
from spie.questions.brainbloom import planning_episode, planning_scenarios


def model(seed=None, version="planning-experience-v2"):
    return {
        "version": "state-planning-v1",
        "experience_version": version,
        "names": ["Mercury" if seed is None else f"Mercury {seed}", "Venus", "Earth", "Mars"],
        "level": 1, "capacity": 4, "initial_energy": 3, "initial_gates": [0, 0],
        "charger": 2,
        "routes": [[0, 1, 1, -1], [0, 2, 1, -1], [0, 3, 4, 0], [1, 3, 1, 0],
                   [2, 3, 1, 1], [1, 0, 1, -1], [2, 0, 1, -1]],
        "switches": [[0, 3, 0]],
    }


# These cases come from development seeds 101–120, not the reserved evaluation set.
@pytest.fixture(params=[
    (101, "farewell-recording", "Pip", "Mira", "recording"),
    (102, "opening-night-invitation", "Dot", "Asha", "invitation"),
    (110, "radio-repair-notes", "Relay", "Dev", "notes"),
])
def premise(request):
    seed, identifier, robot, recipient, delivery = request.param
    physical = model(seed)
    return physical, planning_episode.create(physical), identifier, robot, recipient, delivery


def paths(physical):
    graph = domain_graph(physical)
    found, queue = {initial(physical): []}, deque([initial(physical)])
    while queue:
        state = queue.popleft()
        for action, target in graph[state].items():
            if target not in found:
                found[target] = [*found[state], action]
                queue.append(target)
    return graph, found


def state_tuple(public):
    return (public["location"], public["energy"], *public["gates"], int(public["recharged"]))


def test_three_distinct_concise_goals_and_stable_relationships(premise):
    physical, scenario, identifier, robot, recipient, delivery = premise
    assert scenario["version"] == planning_scenarios.VERSION
    assert scenario["premise"] == identifier
    assert scenario["characters"]["robot"]["name"] == robot
    assert scenario["characters"]["caretaker"]["name"] == recipient
    assert all(name in scenario["introduction"] for name in (robot, recipient))
    assert delivery in scenario["introduction"].lower()
    assert delivery in scenario["resolution"]["outcome"].lower()
    assert scenario["resolution"]["heading"]
    assert scenario["resolution"]["destination"] == scenario["rooms"][-1]["role"]
    assert physical["names"][-1] in scenario["objective"]
    assert "Every legal arrival succeeds" in scenario["objective"]
    legacy = planning_episode.create({**physical, "experience_version": "planning-experience-v1"})
    def words(value):
        return len((value["introduction"] + " " + value["objective"]).split())

    assert words(scenario) <= 0.65 * words(legacy)
    assert scenario["source_facts"] == legacy["source_facts"]
    assert scenario["resolution"]["goal_location"] == len(physical["names"]) - 1
    assert planning_episode.create(copy.deepcopy(physical)) == scenario
    poisoned = {**physical, "answer_action": "teleport", "solution": ["teleport"],
                "best_steps": -999, "inventory": ["a forged requirement"]}
    assert planning_episode.create(poisoned) == scenario


def test_every_reachable_state_keeps_the_same_public_mechanics(premise):
    physical, scenario, *_ = premise
    graph, transcripts = paths(physical)
    legacy = {**physical, "experience_version": "planning-experience-v1"}
    legacy_scenario = planning_episode.create(legacy)
    for current, actions in transcripts.items():
        view = planning_episode.replay(physical, scenario, actions)
        old = planning_episode.replay(legacy, legacy_scenario, actions)
        assert state_tuple(view["state"]) == current
        for field in ("state", "legal_actions", "goal_reached", "status", "can_append"):
            assert view[field] == old[field]
        for new_action, old_action in zip(view["local_actions"], old["local_actions"], strict=True):
            for field in ("id", "legal", "next_state", "reasons", "fact_ids"):
                assert new_action[field] == old_action[field]
        facts = {fact["id"]: fact for fact in view["facts"]}
        assert len(facts) == len(view["facts"])
        assert {key: fact["value"] for key, fact in facts.items()} == {
            fact["id"]: fact["value"] for fact in old["facts"]
        }
        assert set(view["legal_actions"]) == set(graph[current])


def test_actual_events_drive_dialogue_without_repeating_a_move_quip(premise):
    physical, scenario, _, robot, *_ = premise
    actions = ["move_0_2", "recharge", "move_2_0", "switch_0", "move_0_1",
               "move_1_0", "switch_0"]
    view = planning_episode.replay(physical, scenario, actions)
    events = view["history"]
    assert "2 to 4 energy" in events[1]["dialogue"]["text"]
    assert "Opened A, B" in events[3]["dialogue"]["text"]
    assert "Closed A, B" in events[6]["dialogue"]["text"]
    assert "visit 2" in events[2]["dialogue"]["text"]
    assert "visit 3" in events[5]["dialogue"]["text"]
    moved = [event for event in events if event["action"].startswith("move_")]
    assert len({event["dialogue"]["text"] for event in moved}) == len(moved)
    for event in events:
        assert event["dialogue"]["speaker"] == robot
        assert event["dialogue"]["kind"] == "expressive; not mechanical evidence"
        assert f"state.{event['step']}" in event["fact_ids"]
    for event in moved:
        assert event["after"]["location_name"] in event["dialogue"]["text"]
    zero = planning_episode.replay(physical, scenario, ["move_0_2", "move_2_0", "move_0_1"])
    assert zero["state"]["energy"] == 0
    text = zero["history"][-1]["dialogue"]["text"].lower()
    assert any(phrase in text for phrase in ("no energy", "zero energy"))


def test_six_room_journey_does_not_cycle_through_the_same_move_lines():
    physical = model(101)
    physical.update({
        "names": ["Dispatch 101", "Room 102", "Room 103", "Room 104", "Room 105", "Hall 106"],
        "level": 3, "capacity": 8, "initial_energy": 8, "initial_gates": [1, 1],
        "routes": [[0, 1, 1, -1], [0, 2, 1, -1], [0, 3, 1, -1], [1, 2, 1, 0],
                   [2, 3, 1, 0], [3, 4, 1, 1], [4, 5, 1, 1], [3, 1, 1, -1], [1, 0, 1, -1]],
    })
    actions = ["move_0_1", "move_1_2", "move_2_3", "move_3_4", "move_4_5"]
    view = planning_episode.replay(physical, planning_episode.create(physical), actions)
    remarks = [event["dialogue"]["text"].split(". ", 1)[1] for event in view["history"]]
    assert len(set(remarks)) == len(remarks)
    assert view["goal_reached"]


def test_slow_and_fast_arrivals_resolve_the_same_goal_with_truthful_summaries(premise):
    physical, scenario, _, robot, recipient, delivery = premise
    fast = ["switch_0", "move_0_1", "move_1_3"]
    slow = ["move_0_2", "recharge", "move_2_0", "switch_0", "move_0_1", "move_1_3"]
    long = ["switch_0"] * 125 + ["move_0_1", "move_1_3"]
    endings = []
    for actions in (fast, slow, long):
        view = planning_episode.replay(physical, scenario, actions)
        assert view["status"] == "complete" and view["goal_reached"]
        assert not view["can_append"] and not view["local_actions"]
        ending = view["resolution"]
        endings.append(ending)
        assert all(name in ending["text"] for name in (robot, recipient))
        assert delivery in ending["text"].lower()
        assert ending["dialogue"]["speaker"] == robot
        assert f"{len(actions)} actions" in ending["replay_summary"]
        assert f"{actions.count('recharge')} recharges" in ending["replay_summary"]
        assert f"Energy remaining: {view['state']['energy']}" in ending["replay_summary"]
        assert f"state.{len(actions)}" in ending["fact_ids"]
    assert len({ending["text"] for ending in endings}) == 1
    assert len({ending["replay_summary"] for ending in endings}) == 3


def test_short_hints_keep_evidence_and_do_not_select_an_action_early():
    physical = model(101)
    scenario = planning_episode.create(physical)
    graph, transcripts = paths(physical)
    old_model = {**physical, "experience_version": "planning-experience-v1"}
    old_scenario = planning_episode.create(old_model)
    for current, actions in transcripts.items():
        best, _, _ = shortest(physical, graph, current)
        for level in (1, 2, 3):
            view = planning_episode.replay(physical, scenario, actions, hint_level=level)
            old = planning_episode.replay(old_model, old_scenario, actions, hint_level=level)
            hint = view["hint"]
            assert hint["fact_ids"] == old["hint"]["fact_ids"]
            assert len(hint["text"].split()) < len(old["hint"]["text"].split())
            facts = {fact["id"]: fact for fact in view["facts"]}
            for fact in facts.values():
                assert set(fact.get("depends_on", [])) <= facts.keys()
            if level < 3:
                assert "action" not in hint and "hint.next" not in facts
                assert "shortest" not in hint["text"]
                assert not any(action in hint["text"] for action in graph[current] if "_" in action)
                assert not any(action["label"] in hint["text"] for action in view["local_actions"])
            elif best not in (0, None):
                assert hint["action"] in graph[current]
                assert shortest(physical, graph, graph[current][hint["action"]])[0] == best - 1


# Digests captured from the untouched revision-11 implementation before this edit.
# Unlike self-generated snapshots these fail on any altered legacy story, hint,
# source fact, dialogue, consequence or replay field, including key/value types.
_LEGACY = (
    ([], (
        "963e85b34c4f16ee709f2d03fd50a2d95ba2e1a28af5a1229401cd5f51bbdc35",
        "831b1262f138b56e5f4e5a187e936d4f815747d4bb208a51749c2a8a15339083",
        "07e9bf84cf1c3aa9c5d32532fe3966eb4c6d47116e05875d296e57dc0d367d0f",
        "1431635d7b994d0a0eeb92793cadb266d80c66ee11a62e5565dfbd0616115796",
    )),
    (["switch_0"], (
        "46d6c29b45149fec59b6feb8b18ad61643ec2bf1c66581c4d46cfc8b13c723e4",
        "87175ae69cc9af17a3c93462050b687e2ef5fb34a10af752f382fb24901045da",
        "3c1d585c8b9bb6975bd9e35b53330817e399f9586769e9fadc561d6757410a5e",
        "2d0e76baa10a7e1de1a7ed717c314009bfc93e8d79123f108f15c1a6270d6a7c",
    )),
    (["move_0_2", "recharge", "move_2_0", "switch_0", "move_0_1", "move_1_3"], (
        "09020550e045d1a02bad5f3842afcd88c907badab865c59e9ab8fee2835a09df",
        "781641e1697c6bd55b7e174d6003c11aa41a7cc5b4b819ba49168470d7f543f0",
        "c1cfad0f5b1df1b753c6dd4ce3a0c3c76904d59ce4de53c48698b335f8c6296b",
        "928fdf68458b591c7639a66dcaa0bff663bdc1608a1b49201049160247da821b",
    )),
)


@pytest.mark.parametrize("actions,expected", _LEGACY)
def test_revision11_full_replay_retains_exact_frozen_output(actions, expected):
    physical = model(version="planning-experience-v1")
    scenario = planning_episode.create(physical)
    assert planning_episode.VERSION == "planning-episode-v1"
    assert digest(scenario) == "a5f6b6daba5c2a8237c5b873874f8035ca1a02aabdb9fd36a7a5ab7438995d84"
    for level, fingerprint in enumerate(expected):
        view = planning_episode.replay(physical, scenario, actions, hint_level=level)
        assert digest(view) == fingerprint
    del physical["experience_version"]
    assert planning_episode.create(physical) == scenario


def test_scenarios_cannot_be_transplanted_between_revisions_or_forged():
    modern, old = model(), model(version="planning-experience-v1")
    for physical, scenario in ((modern, planning_episode.create(old)),
                               (old, planning_episode.create(modern))):
        with pytest.raises(ValueError, match="canonical episode"):
            planning_episode.replay(physical, scenario, [])
    scenario = planning_episode.create(modern)
    scenario["characters"]["robot"]["name"] = "Imposter"
    with pytest.raises(ValueError, match="canonical episode"):
        planning_episode.replay(modern, scenario, [])
