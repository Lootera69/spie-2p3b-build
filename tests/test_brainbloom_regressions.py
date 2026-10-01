"""Behavioral regressions from the ground-reality audit, including frozen old exports."""

import copy
import json
import random
from pathlib import Path

import pytest

from spie.questions.brainbloom import patterns, routes
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.grid_quality import assess
from spie.questions.brainbloom.logic_grid import check, parse
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.structural import grid_key


@pytest.mark.parametrize("bundle", json.loads(
    (Path(__file__).parent / "fixtures/workshop_revision1.json").read_text(encoding="utf-8")
))
def test_saved_revision_one_drafts_still_replay(bundle):
    assert verify_bundle(bundle) == 1


def test_twenty_easy_contradictions_are_replayable_and_structurally_distinct():
    bundle = Generator().build(Request("activities", difficulty="easy", variation="contradiction",
                                       subject="space, ocean", count=20, seed=0))
    assert bundle["summary"]["complete"]
    assert len({p["structural_key"] for p in bundle["proofs"]}) == 20
    assert verify_bundle(bundle) == 20


@pytest.mark.parametrize("qtype", ["type-answer", "riddle"])
@pytest.mark.parametrize("level", ["easy", "medium", "hard"])
def test_typed_contradiction_accepts_the_requested_letter_and_reports_actual_support(qtype, level):
    result = Generator().build(Request("activities", qtype, variation="contradiction",
                                       difficulty=level, subject="space, ocean", seed=7))
    item, proof = result["items"][0], result["proofs"][0]
    letter = item["correctAnswer"][-1]
    normalized = {a.casefold().strip() for a in item["acceptedAnswers"]}
    assert letter.casefold() in normalized
    assert len(normalized & set("abcd")) == 1
    assert proof["quality"]["minimum_supporting_clues"] == proof["model"]["required_chain_length"]


@pytest.mark.parametrize("level", [1, 2, 3])
def test_discovered_rule_and_predicted_answer_are_independently_checked(level):
    names = [f"Card{i}" for i in range(level + 3)]
    model = patterns.propose(names, level, random.Random(level))
    proof = patterns.check(model)
    assert proof["agree"]
    matches = [i for i, (a, b, c) in enumerate(model["rules"])
               if all(a * x**2 + b * x + c == y for x, y in model["examples"])]
    assert matches == [model["answer_index"]]
    model["answer"] += 1
    with pytest.raises(RuntimeError):
        patterns.check(model)


@pytest.mark.parametrize("level", [1, 2, 3])
def test_route_puzzle_asks_for_real_travel_and_checks_every_first_stop(level):
    names = [f"Place{i}" for i in range(level + 4)]
    model = routes.propose(names, level, random.Random(level))
    draft = routes.render(model)
    assert "one-way" in draft["stem"]
    assert len(draft["distractors"]) == 3
    if level > 1:
        cheapest_leg = min((w, b) for a, b, w in model["edges"] if a == 0)[1]
        assert model["answer"] != cheapest_leg
    model["options"][0]["cost"] += 1
    with pytest.raises(RuntimeError):
        routes.check(model)


def test_grid_key_ignores_labels_and_reflection_but_includes_actual_clues():
    model = parse({"groups": "Animal: Tiger, Lion, Owl\nColour: Red, Blue, Green",
                   "rules": "Tiger is in position 1. Lion is in position 2. "
                            "Red is paired with Tiger. Blue is paired with Lion."})
    rows = check(model, model["rules"])
    solution = rows[0]
    original = grid_key(model, model["rules"], solution, 0, 1)
    renamed = copy.deepcopy(model)
    renamed["names"] = [f"Name{i}" for i in range(6)]
    for i, group in enumerate(renamed["groups"]):
        group["name"] = f"Group{i}"
        group["values"] = [renamed["names"][j] for j in group["indices"]]
    assert grid_key(renamed, list(reversed(model["rules"])), solution, 0, 1) == original
    reflected = copy.deepcopy(model["rules"])
    for rule in reflected:
        if rule["kind"] == "at":
            rule["n"] = 4 - rule["n"]
    assert grid_key(model, reflected, [4 - x for x in solution], 0, 1) == original
    extra = [*model["rules"], {"kind": "before", "a": 0, "b": 1, "text": "Tiger before Lion"}]
    assert grid_key(model, extra, solution, 0, 1) != original


def test_teaching_deductions_preserve_every_solution_and_name_their_reasons():
    model = parse({"groups": "Animal: Tiger, Lion, Owl",
                   "rules": "Tiger is before Lion. Owl cannot be next to Tiger."})
    solution = check(model, model["rules"])[0]
    report = assess(model, model["rules"], solution)
    assert report["propagation_complete"]
    assert report["remaining_domains"] == [[x] for x in solution]
    assert all(solution[d["variable"]] in d["after"] for d in report["deductions"])
    assert any("Clue" in hint and "position" in hint for hint in report["hints"])
    assert "score" not in report


def test_grid_key_ignores_group_and_value_order():
    original = parse({"groups": "Animal: Tiger, Lion, Owl\nColour: Red, Blue, Green",
                      "rules": "Tiger is in position 1. Lion is in position 2. "
                               "Red is paired with Tiger. Blue is paired with Lion."})
    reordered = parse({"groups": "Colour: Green, Red, Blue\nAnimal: Owl, Lion, Tiger",
                       "rules": "Tiger is in position 1. Lion is in position 2. "
                                "Tiger is paired with Red. Lion is paired with Blue."})
    def key(model):
        solution = check(model, model["rules"])[0]
        target = model["names"].index("Tiger")
        answer_group = next(i for i, group in enumerate(model["groups"])
                            if group["name"] == "Colour")
        return grid_key(model, model["rules"], solution, target, answer_group)
    assert key(original) == key(reordered)


def test_persistent_history_avoids_renamed_repeats_without_breaking_replay(tmp_path):
    history = tmp_path / "drafts.sqlite3"
    request = Request("autopilot", subject="space, ocean", seed=7)
    first = Generator(history=history).build(request)
    second = Generator(history=history).build(request)
    assert first["proofs"][0]["structural_key"] != second["proofs"][0]["structural_key"]
    assert second["provenance"]["history"]["compared"] == 1
    assert verify_bundle(first) == verify_bundle(second) == 1


@pytest.mark.parametrize("topic", ["black hole", "climate change", "photosynthesis",
                                  "quantum computing"])
def test_previously_limited_topics_have_explicit_authored_vocabulary(topic):
    engine = Generator()
    prepared = prepare(Brief(activity="autopilot", subject=topic, difficulty="hard"),
                       engine.dictionary)
    assert prepared["ready"], prepared["message"]
    bundle = engine.build(Request(**prepared["request"]))
    assert bundle["dictionary"]["source"]["license"] == "Project-authored definitions"
    assert verify_bundle(bundle) == 1
