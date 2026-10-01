"""Additional beginner activities are real generator routes, not menu-only labels."""

import json

import pytest

from spie.questions.brainbloom import Request
from spie.questions.brainbloom.brief import ACTIVITIES, Brief, prepare
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle


@pytest.mark.parametrize("activity,variation,phrase", [
    ("pattern", "pattern", "Discover a number rule."),
    ("contradiction", "contradiction", "Find the impossible clue."),
    ("most-likely", "most-likely", "Choose the most likely explanation."),
    ("best-move", "best-move", "Plan the best next move."),
])
def test_beginner_activity_has_plain_language_route_and_replay(activity, variation, phrase):
    report = prepare(Brief(activity=activity, subject="animals, space"), Dictionary())
    assert report["ready"], report["message"]
    assert report["request"]["topic"] == "activities"
    assert report["request"]["variation"] == variation
    result = Generator().build(Request(**report["request"]))
    assert result["version"] == 8
    assert result["proofs"][0]["word_bank"]
    assert verify_bundle(json.loads(json.dumps(result))) == 1


def test_impossible_clue_has_exactly_one_false_option_and_a_reasoning_proof():
    result = Generator().build(Request("activities", variation="contradiction",
                                      subject="animals, space", topic_mode="combined"))
    proof = result["proofs"][0]
    assert proof["option_model_counts"].count(0) == 1
    assert proof["method"] == "z3-and-exhaustive-option-consistency"
    assert proof["steps"]
    assert len(result["items"][0]["choices"]) == 4


def test_pattern_activity_infers_a_finite_rule_even_with_science_category():
    result = Generator().build(Request("activities", "multiple-choice", category="science",
                                      variation="pattern", subject="space, ocean",
                                      topic_mode="combined"))
    assert result["items"][0]["category"] == "science"
    assert result["proofs"][0]["method"] == "finite-rule-enumeration-and-z3"
    assert "exactly one of these four rules" in result["items"][0]["question"]
    assert verify_bundle(result) == 1


def test_activity_names_are_understood_by_the_written_instruction_parser():
    for key in ("pattern", "contradiction", "most-likely", "best-move"):
        module = __import__("spie.questions.brainbloom.instructions", fromlist=["interpret"])
        report = module.interpret(ACTIVITIES[key].label)
        assert report["status"] == "supported"
        assert report["fields"]["activity"] == key


def test_activity_topic_meanings_and_unknown_words_are_not_ignored():
    engine = Generator()
    report = prepare(Brief(activity="most-likely", subject="space, unknownxyz"), engine.dictionary)
    assert not report["ready"] and "unknownxyz" in report["message"]
