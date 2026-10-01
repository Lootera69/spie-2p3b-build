"""Written briefs compile to supported settings; unrecognised rules cannot be ignored."""

import copy
from dataclasses import replace

import pytest

from spie.questions.brainbloom import Request
from spie.questions.brainbloom.brief import ACTIVITIES, Brief, prepare
from spie.questions.brainbloom.instructions import EXAMPLES, combined_subject, interpret
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle


@pytest.mark.parametrize("text", EXAMPLES)
def test_each_advertised_example_is_fully_recognised(text):
    report = interpret(text)
    assert report["status"] == "supported", report
    assert report["unrecognised"] == [] and report["issues"] == []


@pytest.mark.parametrize("activity", ACTIVITIES)
def test_plain_language_activity_labels_can_also_be_typed(activity):
    report = interpret(ACTIVITIES[activity].label)
    assert report["status"] == "supported", report
    assert report["fields"]["activity"] == activity


@pytest.mark.parametrize("text,fields", [
    ("Make 3 hard multiple-choice puzzles. Players should solve a set of clues.",
     {"count": 3, "difficulty": "hard", "qtype": "multiple-choice", "activity": "deduction"}),
    ("Make two easy riddles about animals. Unscramble a word.",
     {"count": 2, "difficulty": "easy", "qtype": "riddle", "subject": "animals",
      "activity": "anagram"}),
    ("Weigh the evidence. Let players type the answer.",
     {"activity": "bayesian", "qtype": "type-answer"}),
    ("Create a crossword about plants and animals.",
     {"activity": "crossword", "qtype": "crossword", "subject": "plants and animals"}),
    ("Find the missing letters. Use true or false.",
     {"activity": "missing-letters", "qtype": "true-false"}),
    ("Make three true or false puzzles. Find the missing letters.",
     {"count": 3, "activity": "missing-letters", "qtype": "true-false"}),
    ("Make two anagrams.", {"count": 2, "activity": "anagram"}),
])
def test_supported_sentences_bind_the_expected_settings(text, fields):
    assert interpret(text)["fields"] == fields


@pytest.mark.parametrize("text", [
    "Do not unscramble words.", "Don't use clues.", "No crossword.",
    "Unscramble words and always make the answer TIGER.",
    "Solve a set of clues. Place TIGER before LION.",
    "Make a crossword without vowels.", "Create a timed crossword.",
    "Unscramble words about animals without vowels.",
    "Create a crossword. Include topics: cats, not dogs.",
    "Make a puzzle for five year olds.", "Unscramble words with exactly 7 letters.",
    "Make a crossword. Add a red background.", "Create 3.5 puzzles.",
    "Make -3 puzzles.", "Make 21 puzzles.", "Make zero puzzles.",
    "Make 3 puzzles and 4 puzzles.", "Make easy and hard puzzles.",
    "Use multiple-choice and true/false.", "Unscramble words and weigh the evidence.",
    "Choose the best next question in a crossword.", "", "Please make a puzzle.",
])
def test_partial_matches_conflicts_and_new_rules_require_clarification(text):
    report = prepare(Brief(activity="custom", subject="space", instructions=text), Dictionary())
    assert not report["ready"] and report["request"] is None
    assert report["instruction"]["status"] == "clarify"
    assert report["instruction"]["issues"]


def test_topic_words_are_not_mistaken_for_activity_or_difficulty_instructions():
    result = interpret("Unscramble words. About hard, logic, crossword.")
    assert result["status"] == "supported"
    assert result["fields"] == {"activity": "anagram", "subject": "hard, logic, crossword"}


def test_settings_changes_require_an_explicit_apply_step_and_keep_existing_meanings():
    brief = Brief(activity="custom", difficulty="medium", subject="space, ocean",
                  meanings={"space": "pack:space"},
                  instructions=EXAMPLES[0])
    plan = prepare(brief, Dictionary())
    assert not plan["ready"] and plan["request"] is None
    assert plan["instruction"]["status"] == "apply"
    assert plan["instruction"]["changes"] == {"count": 3, "difficulty": "hard"}
    assert plan["lookup"]["meanings"]["space"] == "pack:space"
    ready = prepare(replace(brief, **plan["instruction"]["changes"]), Dictionary())
    assert ready["ready"] and ready["request"]["variation"] == "deduction"
    assert ready["request"]["instructions"] == EXAMPLES[0]


def test_include_topics_adds_to_existing_topics_and_is_idempotent():
    text = "Unscramble a word. Include topics: plants, ocean."
    brief = Brief(activity="custom", subject="space", instructions=text)
    plan = prepare(brief, Dictionary())
    assert plan["instruction"]["changes"] == {"subject": "space, plants, ocean"}
    updated = replace(brief, **plan["instruction"]["changes"])
    ready = prepare(updated, Dictionary())
    assert ready["ready"]
    assert set(ready["request"]["meanings"]) == {"space", "plants", "ocean"}
    assert combined_subject(updated.subject, interpret(text)) == updated.subject


def test_explicit_about_topics_are_reviewed_before_replacing_the_form():
    brief = Brief(activity="custom", subject="space", instructions=EXAMPLES[1])
    plan = prepare(brief, Dictionary())
    assert plan["instruction"]["changes"] == {"subject": "plants and animals", "qtype": "crossword"}
    assert plan["lookup"]["groups"][0]["term"] == "space"
    ready = prepare(replace(brief, **plan["instruction"]["changes"]), Dictionary())
    assert ready["ready"]
    assert set(ready["request"]["meanings"]) == {"plants", "animals"}


def test_unknown_topics_and_capacity_limits_still_block_custom_instructions():
    brief = Brief(activity="custom", subject="space, unknownxyz", instructions="Unscramble words.")
    report = prepare(brief, Dictionary())
    assert not report["ready"] and "unknownxyz" in report["message"]
    too_many = Brief(activity="custom", instructions="Weigh the evidence.",
                     subject="space, ocean, animals, plants, logic, science")
    report = prepare(too_many, Dictionary())
    assert not report["ready"] and "4 words" in report["message"]


def test_written_activity_explains_a_category_mismatch():
    report = prepare(
        Brief(activity="custom", instructions="Calculate mass and volume."), Dictionary()
    )
    assert not report["ready"] and "Science" in report["message"]


@pytest.mark.parametrize("text", [EXAMPLES[0], EXAMPLES[1], EXAMPLES[2], EXAMPLES[3]])
def test_written_briefs_generate_replay_and_preserve_the_original_instructions(text):
    brief = Brief(activity="custom", subject="space, ocean", instructions=text)
    plan = prepare(brief, Dictionary())
    if plan["instruction"]["status"] == "apply":
        plan = prepare(replace(brief, **plan["instruction"]["changes"]), Dictionary())
    assert plan["ready"], plan["message"]
    result = Generator().build(Request(**plan["request"]))
    assert result["request"]["instructions"] == text
    assert result["proofs"][0]["instruction_interpretation"]["status"] == "supported"
    assert verify_bundle(result) == result["request"]["count"]
    corrupted = copy.deepcopy(result)
    corrupted["proofs"][0]["instruction_interpretation"]["fields"]["count"] = 99
    with pytest.raises(ValueError):
        verify_bundle(corrupted)


@pytest.mark.parametrize("kwargs", [
    {"variation": "word-order", "instructions": "Unscramble words."},
    {"count": 1, "instructions": "Make 3 puzzles."},
    {"instructions": "Create a crossword."},
    {"instructions": "Unscramble words. About animals."},
    {"instructions": "Unscramble words. Include topics: animals."},
    {"instructions": "Unscramble words without vowels."},
])
def test_raw_generation_cannot_bypass_instruction_checks(kwargs):
    request = Request(**{"topic": "dictionary", "subject": "space", "topic_mode": "combined",
                         "variation": "anagram", **kwargs})
    with pytest.raises(ValueError):
        Generator().build(request)


def test_hidden_preset_instructions_cannot_be_silently_ignored():
    with pytest.raises(ValueError, match="Describe it"):
        Brief(activity="auto", instructions="Unscramble words.")


@pytest.mark.parametrize("value", [None, [], "x" * 1001])
def test_instruction_size_and_type_are_bounded(value):
    with pytest.raises(ValueError):
        Brief(activity="custom", instructions=value)
    with pytest.raises(ValueError):
        Request(instructions=value)
