"""Creator collections constrain recommendations without invalidating saved activity IDs."""

from dataclasses import replace

import pytest

from spie.questions.brainbloom.activity_policy import PATTERN_TRUE_FALSE_UNAVAILABLE, POLICIES
from spie.questions.brainbloom.brief import ACTIVITIES, Brief, configuration, prepare
from spie.questions.brainbloom.catalog import CATEGORIES, QUIZ, TOPICS, Request
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle


def test_every_legacy_activity_has_a_collection_and_only_four_are_core():
    inventory = configuration()["activities"]
    assert set(POLICIES) == set(ACTIVITIES)
    assert {key for key, row in inventory.items() if row["collection"] == "core"} == {
        "deduction", "autopilot", "logic-grid", "crossword",
    }
    assert not inventory["most-likely"]["visible"]
    assert inventory["most-likely"]["canonical_id"] == "bayesian"
    assert all(not row["automatic"] for row in inventory.values()
               if row["collection"] in ("practice", "experimental"))


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("qtype", (*QUIZ, "riddle"))
def test_scored_auto_uses_the_core_in_every_platform_category(category, qtype):
    report = prepare(Brief(category=category, qtype=qtype, subject="space, ocean"), Dictionary())
    assert report["ready"], report["message"]
    assert report["selected_activity"] in {"deduction", "autopilot"}
    assert report["selected_collection"] == "core"


@pytest.mark.parametrize("activity", ACTIVITIES)
def test_explicit_legacy_ids_remain_deliberate_choices_with_truthful_collection(activity):
    spec = ACTIVITIES[activity]
    brief = Brief(activity=activity, category=TOPICS[spec.family].categories[0],
                  qtype=spec.types[0], subject="space, ocean" if spec.uses_topics else "")
    report = prepare(brief, Dictionary())
    assert report["ready"], report["message"]
    expected = "bayesian" if activity == "most-likely" else activity
    assert report["selected_activity"] == expected
    assert report["selected_collection"] == POLICIES[expected].collection
    assert report["policy_notice"]


@pytest.mark.parametrize("collection", ["practice", "experimental"])
def test_optional_scored_collections_require_an_explicit_activity(collection):
    report = prepare(Brief(collection=collection), Dictionary())
    assert not report["ready"]
    assert report["selected_activity"] == ""
    assert "Choose an activity" in report["message"]


def test_wonder_format_itself_deliberately_selects_unscored_explore():
    report = prepare(Brief(qtype="wonder", subject="space, ocean"), Dictionary())
    assert report["ready"] and report["selected_activity"] == "word-wonder"
    assert report["selected_collection"] == "explore"
    assert "Unscored" in report["policy_notice"]
    assert not report["difficulty_relevant"]


@pytest.mark.parametrize("text,activity,collection", [
    ("Choose the most likely explanation.", "bayesian", "experimental"),
    ("Plan the best next move.", "best-move", "practice"),
    ("Find the impossible clue.", "contradiction", "experimental"),
])
def test_explicit_written_choices_expose_the_resolved_collection(text, activity, collection):
    report = prepare(Brief(activity="custom", instructions=text, subject="space, ocean"),
                     Dictionary())
    assert report["ready"], report["message"]
    assert report["selected_activity"] == report["instruction"]["resolved_activity"] == activity
    assert report["selected_collection"] == collection
    assert report["instruction"]["resolved_collection"] == collection


def test_evidence_alias_uses_one_new_generator_and_preserves_old_written_replay():
    text = "Choose the most likely explanation."
    report = prepare(Brief(activity="custom", instructions=text, subject="space, ocean"),
                     Dictionary())
    new = Request(**report["request"])
    assert (new.topic, new.variation) == ("reasoning", "bayesian")
    old = replace(new, topic="activities", variation="most-likely", engine_revision=8)
    engine = Generator()
    assert verify_bundle(engine.build(old)) == 1
    assert verify_bundle(engine.build(new)) == 1


@pytest.mark.parametrize("collection", [None, [], "hidden"])
def test_invalid_collection_is_rejected_at_the_creator_boundary(collection):
    with pytest.raises(ValueError, match="Core puzzles"):
        Brief(collection=collection)


@pytest.mark.parametrize("difficulty", ("easy", "medium", "hard"))
def test_number_rule_true_false_is_withheld_from_creator_choices(difficulty):
    report = prepare(Brief(activity="pattern", qtype="true-false", difficulty=difficulty),
                     Dictionary())
    assert not report["ready"] and report["request"] is None
    assert report["message"] == PATTERN_TRUE_FALSE_UNAVAILABLE
    assert report["selected_collection"] == "experimental"
    assert "pattern" not in {row["id"] for row in report["activities"]}


@pytest.mark.parametrize("qtype", ("multiple-choice", "type-answer", "riddle"))
def test_number_rule_keeps_its_supported_prediction_formats(qtype):
    assert configuration()["activities"]["pattern"]["types"] == (
        "multiple-choice", "type-answer", "riddle",
    )
    report = prepare(Brief(activity="pattern", qtype=qtype, subject="space, ocean"),
                     Dictionary())
    assert report["ready"], report["message"]
    assert report["request"]["qtype"] == qtype
    assert report["request"]["variation"] == "pattern"
