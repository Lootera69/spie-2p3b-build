"""Autonomous invention, topic coverage, multi-clue questions and saved replay."""

import copy
import json
import socket
import subprocess
from itertools import combinations

import pytest

from spie.questions.brainbloom import Request
from spie.questions.brainbloom.autopilot import BUDGET
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.logic_grid import holds, worlds
from spie.questions.brainbloom.service import Generator, verify_bundle
from test_brainbloom_flow import AmbiguousDictionary


@pytest.mark.parametrize("difficulty,groups", [("easy", 1), ("medium", 2), ("hard", 3)])
@pytest.mark.parametrize("kind", ["multiple-choice", "true-false", "type-answer", "riddle"])
def test_topics_alone_invent_verified_groups_rules_and_questions(difficulty, groups, kind):
    engine = Generator()
    plan = prepare(Brief(activity="autopilot", subject="animals, space", difficulty=difficulty,
                         qtype=kind), engine.dictionary)
    assert plan["ready"] and plan["request"]["grid"] is None
    bundle = engine.build(Request(**plan["request"]))
    proof = bundle["proofs"][0]
    assert bundle["version"] == 7
    assert len(proof["model"]["groups"]) == groups
    assert proof["authored_rules"] == [] and proof["added_rules"]
    assert proof["solution_count"] == 1
    assert {row["term"] for row in proof["topic_coverage"]} == {"animals", "space"}
    assert proof["autopilot"]["minimum_supporting_clues"] >= 2
    assert proof["search"]["budget"] == BUDGET
    assert proof["search"]["selected_score"] >= proof["search"]["first_qualified_score"]
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1


def test_minimum_support_means_no_smaller_subset_forces_the_actual_answer():
    bundle = Generator().build(Request("autopilot", subject="animals", difficulty="hard"))
    proof = bundle["proofs"][0]
    target = proof["query"]["target"]
    group = proof["query"]["answer_group"]
    solution = proof["solution_positions"]
    partner = next(i for i in proof["model"]["groups"][group]["indices"]
                   if solution[i] == solution[target])
    wrong = [row for row in worlds(3, 3) if row[target] != row[partner]]
    rules = proof["added_rules"]
    for size in range(proof["autopilot"]["minimum_supporting_clues"]):
        for subset in combinations(rules, size):
            assert any(all(holds(rule, row) for rule in subset) for row in wrong)
    support = [rules[i - 1] for i in proof["autopilot"]["supporting_clues"]]
    assert not any(all(holds(rule, row) for rule in support) for row in wrong)


def test_six_topics_fit_medium_but_cannot_silently_overflow_easy():
    engine = Generator()
    subject = "space, ocean, animals, plants, science, logic"
    plan = prepare(Brief(activity="autopilot", subject=subject, difficulty="easy"),
                   engine.dictionary)
    assert not plan["ready"]
    assert [option["available"] for option in plan["difficulty_options"]] == [False, True, True]
    bundle = engine.build(Request("autopilot", subject=subject, difficulty="medium"))
    assert len(bundle["proofs"][0]["topic_coverage"]) == 6
    with pytest.raises(ValueError, match="room for 3"):
        engine.build(Request("autopilot", subject=subject, difficulty="easy"))


def test_ambiguous_topics_resolve_automatically_and_keep_explicit_overrides():
    engine = Generator()
    engine.dictionary = AmbiguousDictionary()
    plan = prepare(Brief(activity="autopilot", subject="bank, crane"), engine.dictionary)
    assert plan["ready"]
    assert all(group["selection_mode"] == "automatic" for group in plan["lookup"]["groups"])
    assert all(len(group["choices"]) == 2 for group in plan["lookup"]["groups"])
    automatic = engine.build(Request(**plan["request"]))
    assert automatic["request"]["meanings"] == plan["lookup"]["meanings"]
    assert {"BANK", "CRANE"} <= set(automatic["proofs"][0]["model"]["names"])
    assert verify_bundle(automatic) == 1
    meanings = {"bank": "fixture:bank:river", "crane": "fixture:crane:machine"}
    assert meanings != automatic["request"]["meanings"]
    bundle = engine.build(Request("autopilot", subject="bank, crane", meanings=meanings))
    assert bundle["request"]["meanings"] == meanings
    assert {"BANK", "CRANE"} <= set(bundle["proofs"][0]["model"]["names"])
    assert verify_bundle(bundle) == 1


def test_unknown_topics_block_autopilot_preparation_and_generation():
    engine = Generator()
    plan = prepare(Brief(activity="autopilot", subject="animals, unknownxyz"), engine.dictionary)
    assert not plan["ready"] and plan["request"] is None
    assert plan["lookup"]["unknown_terms"] == ["unknownxyz"]
    with pytest.raises(ValueError, match="unknownxyz"):
        engine.build(Request("autopilot", subject="animals, unknownxyz"))


@pytest.mark.parametrize("mutation", ["version", "meaning", "clues", "support", "score"])
def test_replay_rejects_changes_to_autonomous_design(mutation):
    bundle = Generator().build(Request("autopilot", subject="animals"))
    if mutation == "version":
        bundle.update(version=5, generator="brainbloom-topics-v5")
    elif mutation == "meaning":
        bundle["request"]["meanings"] = {}
    elif mutation == "clues":
        bundle["proofs"][0]["added_rules"].pop()
    elif mutation == "support":
        bundle["proofs"][0]["autopilot"]["minimum_supporting_clues"] = 99
    else:
        bundle["proofs"][0]["search"]["selected_score"] = [99, 99, 99]
    with pytest.raises(ValueError):
        verify_bundle(bundle)


def test_batch_is_offline_deterministic_and_distinct(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Autopilot attempted an external model or network call")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    request = Request("autopilot", subject="animals", count=3)
    engine = Generator()
    bundle = engine.build(request)
    assert bundle == engine.build(copy.deepcopy(request))
    assert len({p["structural_key"] for p in bundle["proofs"]}) == 3
    assert verify_bundle(bundle) == 3


def test_written_instruction_and_blank_topics_can_use_autopilot():
    engine = Generator()
    plan = prepare(Brief(activity="custom", instructions="Design a clue puzzle for me."),
                   engine.dictionary)
    assert plan["ready"] and plan["lookup"]["using_category"]
    assert verify_bundle(engine.build(Request(**plan["request"]))) == 1
