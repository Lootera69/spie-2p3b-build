"""Revision-16 learning vocabulary remains reproducible for saved crosswords."""

import copy
import json
import re
import socket
import subprocess
from pathlib import Path

import pytest

from spie.forge.corpus import digest
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.crossword_learning_words import BANKS
from spie.questions.brainbloom.crossword_vocabulary import (
    builtin_vocabulary,
    eligible,
    prepare_context,
)
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.topics import resolve_many
from spie.questions.brainbloom.workshop import candidate, generate

EVERYDAY = {"CAT", "DOG", "SUN", "MOON", "STAR", "WATER", "BOOK", "TREE", "HOUSE",
            "FOOD", "CAR", "HAPPY", "SCHOOL", "PEOPLE", "IMPORTANT", "INFORMATION"}


@pytest.mark.parametrize("topic", BANKS)
@pytest.mark.parametrize("level", ("easy", "medium", "hard"))
def test_topic_crosswords_teach_words_at_every_level_and_vary(topic, level):
    bundle = generate(Request("dictionary", "crossword", level, count=3,
                              subject=topic, topic_mode="combined", seed=40, engine_revision=16))
    assert verify_bundle(json.loads(json.dumps(bundle))) == 3
    used = set()
    for item, proof in zip(bundle["items"], bundle["proofs"], strict=True):
        words = {c["answer"] for c in item["crosswordData"]["clues"]}
        used.update(words)
        assert not words & EVERYDAY
        assert len(words) == {"easy": 3, "medium": 5, "hard": 7}[level]
        assert all(eligible(c["answer"], c["clue"]) for c in item["crosswordData"]["clues"])
        assert proof["topic_coverage"][0]["used_words"]
        assert "Vocabulary recap:" in item["correctExplanation"]
        assert "Vocabulary recap:" not in item["question"]
        assert "Vocabulary recap:" not in item["lessonContent"]
        for clue in item["crosswordData"]["clues"]:
            assert f"{clue['answer']} — {clue['clue']}" in item["correctExplanation"]
    assert len(used) > len(words), "Seeds should vary the vocabulary as well as layout"


@pytest.mark.parametrize("category", ("logic", "puzzles", "science", "riddles"))
@pytest.mark.parametrize("level", ("easy", "medium", "hard"))
def test_builtin_crosswords_use_learning_vocabulary(category, level):
    bundle = generate(Request("crossword", "crossword", level, category=category,
                              engine_revision=16))
    allowed = {w for w, _ in builtin_vocabulary(category)}
    assert {c["answer"] for c in bundle["items"][0]["crosswordData"]["clues"]} <= allowed
    assert "learning_vocabulary" in bundle["proofs"][0]
    assert verify_bundle(bundle) == 1


def test_familiarity_is_not_a_length_test_and_curated_rare_words_are_supported():
    assert eligible("IBEX", dict(BANKS["animals"])["IBEX"])
    assert eligible("XYLEM", dict(BANKS["plants"])["XYLEM"])
    assert eligible("NONOGRAM", dict(BANKS["puzzles"])["NONOGRAM"])
    assert not eligible("INFORMATION", "Facts communicated about a subject")
    assert not eligible("WATER", "A liquid essential to living organisms")
    assert not eligible("XYZZYWORD", "An invented and unattested string")
    assert not eligible("IBEX", "An ibex is a mountain goat")
    assert not eligible("IBEX", "A [entry] found in mountains")
    assert not eligible("IBEX", "An obsolete spelling of another word")


def test_authored_definitions_are_spelled_for_the_grid_and_do_not_leak_answers():
    for bank in BANKS.values():
        assert len({w for w, _ in bank}) == len(bank)
        for word, clue in bank:
            assert re.fullmatch(r"[A-Z]{3,15}", word)
            assert word.lower() not in re.findall(r"[a-z]+", clue.lower())
            assert "[entry]" not in clue


def test_single_context_and_direct_candidates_use_the_same_prepared_pool():
    request = Request("dictionary", "crossword", subject="ocean", engine_revision=16)
    original = Dictionary().resolve("ocean", "", "puzzles")
    original_copy = copy.deepcopy(original)
    bundle = generate(request, context=original)
    assert candidate(request, request.seed, original) == (bundle["items"][0], bundle["proofs"][0])
    assert original == original_copy
    assert verify_bundle(bundle) == 1
    assert prepare_context(bundle["dictionary"]) == bundle["dictionary"]


def test_focal_common_word_does_not_silently_become_a_broad_topic():
    dictionary = Dictionary()
    context = resolve_many(dictionary, "dolphin", {}, "puzzles")
    with pytest.raises(ValueError, match="DOLPHIN.*learning-vocabulary"):
        prepare_context(context)


def test_narrow_unrecognized_meaning_never_gets_authored_broad_fillers():
    context = Dictionary().resolve("space", "", "puzzles")
    context["sense"] = "fixture:narrow-astronomy"
    context["entries"] = [{"word": w, "definition": c, "sense": "fixture:" + w,
                           "path": ["fixture:narrow-astronomy"]}
                          for w, c in BANKS["space"][:4]]
    prepared = prepare_context(context)
    assert {e["word"] for e in prepared["entries"]} == {e["word"] for e in context["entries"]}
    with pytest.raises(ValueError, match="at least 7 words"):
        generate(Request("dictionary", "crossword", "hard", subject="space", engine_revision=16),
                 context=prepared)


@pytest.mark.parametrize("mutation", ("policy", "word", "clue", "source", "missing", "anchor"))
def test_learning_snapshot_tampering_is_rejected(mutation):
    bundle = generate(Request("dictionary", "crossword", subject="plants", engine_revision=16))
    context = bundle["dictionary"]
    if mutation == "policy":
        context["crossword_learning"]["curated_max_zipf"] = 9
    elif mutation == "word":
        context["entries"][0]["word"] = "WATER"
    elif mutation == "clue":
        context["entries"][0]["definition"] = "A changed and unsupported definition"
    elif mutation == "source":
        context["source"]["name"] = "Changed attribution"
    elif mutation == "missing":
        context.pop("crossword_learning")
    else:
        context["crossword_anchor"] = "WATER"
    with pytest.raises(ValueError):
        verify_bundle(bundle)


def test_replay_uses_embedded_vocabulary_without_network_or_dictionary_lookup(monkeypatch):
    bundle = generate(Request("dictionary", "crossword", subject="space", engine_revision=16))
    def forbidden(*args, **kwargs):
        pytest.fail("Offline replay attempted external lookup")
    monkeypatch.setattr(Dictionary, "resolve", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert verify_bundle(bundle) == 1


def test_preview_recommends_a_board_for_the_exact_generation_vocabulary():
    dictionary = Dictionary()
    report = prepare(Brief(qtype="crossword", subject="plants, animals", seed=19), dictionary)
    assert report["ready"], report["message"]
    bundle = Generator().build(Request(**report["request"]))
    assert report["lookup"]["context"] == bundle["dictionary"]
    for group, topic in zip(report["lookup"]["groups"],
                            bundle["dictionary"]["topics"], strict=True):
        assert group["word_count"] == len(topic["words"])
    recommended = report["crossword_recommendation"]["recommended"]
    assert bundle["items"][0]["crosswordData"]["size"] == recommended
    assert verify_bundle(bundle) == 1


def test_mutating_an_export_cannot_change_the_policy_of_future_puzzles():
    request = Request("crossword", "crossword", engine_revision=16)
    bundle = generate(request)
    expected = copy.deepcopy(bundle)
    bundle["proofs"][0]["learning_vocabulary"]["dictionary_zipf_range"][1] = 9
    assert generate(request) == expected


@pytest.mark.parametrize("topic", ("crossword", "dictionary"))
def test_javascript_number_round_trip_retains_exact_replay(topic):
    request = Request(topic, "crossword", subject="space" if topic == "dictionary" else "",
                      engine_revision=16)
    bundle = generate(request)
    # JSON.stringify writes whole-valued floats as integers (4.0 becomes 4).
    # Browser saves and /api/verify-saved must survive that representation change.
    def js_number(text):
        number = float(text)
        return int(number) if number.is_integer() else number
    browser_bundle = json.loads(json.dumps(bundle), parse_float=js_number)
    assert verify_bundle(browser_bundle) == 1


HISTORICAL = json.loads((Path(__file__).parent / "fixtures/crosswords_revisions_1_to_15.json")
                        .read_text(encoding="utf-8"))


@pytest.mark.parametrize("record", HISTORICAL)
def test_historical_crosswords_remain_byte_identical(record):
    bundle = generate(Request(**record["request"]))
    assert digest(bundle) == record["sha256"]
    assert verify_bundle(bundle) == 1
