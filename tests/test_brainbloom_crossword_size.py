"""Exact platform boards, vocabulary-aware recommendations and legacy replay."""

import copy
import random

import pytest

from spie.questions.brainbloom import Request
from spie.questions.brainbloom.__main__ import main
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.crossword import construct, recommend_size, validate_grid
from spie.questions.brainbloom.service import Generator, verify_bundle

WORDS = [(w, f"Clue for {w}") for w in ("CAT", "CAR", "ART", "RAT", "TAR")]


@pytest.mark.parametrize("size", range(5, 16))
def test_every_platform_size_is_exact_and_independently_reconstructed(size):
    data, proof = construct("logic", 3, random.Random(7), WORDS, board_size=size)
    assert data["size"] == len(data["grid"]) == size
    assert all(len(row) == size for row in data["grid"])
    assert validate_grid(data) == proof
    assert proof["entries"] == 3 and proof["connected"]


def test_recommendation_is_compact_and_ignores_optional_long_dictionary_entries():
    small = recommend_size(WORDS, 3)
    assert small["recommended"] == 5
    optional_long = recommend_size([*WORDS, ("PHOTOSYNTHESIS", "A process")], 3)
    assert optional_long["recommended"] == 5
    assert len(small["options"]) == 11
    assert all(o["available"] for o in small["options"])
    data, _ = construct("logic", 3, random.Random(7), WORDS, board_size=15)
    assert data["size"] == 15


def test_required_long_word_and_topic_never_silently_disappear():
    vocab = [*WORDS, ("CATERPILLAR", "A larva")]
    report = recommend_size(vocab, 3, ["CATERPILLAR"], [["CATERPILLAR"]])
    assert report["recommended"] >= 11
    assert not next(o for o in report["options"] if o["id"] == 5)["available"]
    with pytest.raises(ValueError, match="CATERPILLAR"):
        construct("logic", 3, random.Random(7), vocab,
                  [["CATERPILLAR"]], ["CATERPILLAR"], board_size=5)
    with pytest.raises(ValueError, match="selected topic"):
        construct("logic", 3, random.Random(7), vocab, [["CATERPILLAR"]], board_size=5)


@pytest.mark.parametrize("size", [5, 7, 10, 15])
def test_creator_choice_survives_preparation_generation_and_replay(size):
    engine = Generator()
    plan = prepare(Brief(qtype="crossword", subject="space, ocean", difficulty="easy",
                         crossword_size=size), engine.dictionary)
    assert plan["ready"], plan["message"]
    assert plan["request"]["crossword_size"] == size
    bundle = engine.build(Request(**plan["request"]))
    assert bundle["items"][0]["crosswordData"]["size"] == size
    assert len(bundle["proofs"][0]["topic_coverage"]) == 2
    assert verify_bundle(bundle) == 1
    changed = copy.deepcopy(bundle)
    changed["request"]["crossword_size"] = 14 if size == 15 else 15
    with pytest.raises(ValueError):
        verify_bundle(changed)


def test_automatic_choice_matches_recommendation_and_keeps_all_topics():
    engine = Generator()
    plan = prepare(Brief(qtype="crossword", subject="space, ocean"), engine.dictionary)
    assert plan["ready"]
    assert plan["request"]["crossword_size"] == plan["crossword_recommendation"]["recommended"]
    assert 5 <= plan["request"]["crossword_size"] <= 15


def test_compact_recommendation_has_same_size_fallback_for_different_variation():
    engine = Generator()
    plan = prepare(Brief(qtype="crossword", subject="plants and animals", seed=7),
                   engine.dictionary)
    assert plan["ready"]
    bundle = engine.build(Request(**plan["request"]))
    assert bundle["items"][0]["crosswordData"]["size"] == plan["request"]["crossword_size"]
    assert verify_bundle(bundle) == 1


@pytest.mark.parametrize("size", [True, False, 4, 16, "7", 7.0, [], {}])
def test_size_is_a_strict_platform_integer(size):
    with pytest.raises(ValueError, match="size"):
        Request("crossword", "crossword", crossword_size=size)
    with pytest.raises(ValueError, match="size"):
        Brief(qtype="crossword", crossword_size=size)


def test_other_formats_reject_crossword_setting():
    with pytest.raises(ValueError, match="only to Crossword"):
        Request(crossword_size=7)


def test_legacy_unsized_exports_replay_and_builtin_explicit_size_is_respected():
    engine = Generator()
    legacy = engine.build(Request("dictionary", "crossword", subject="space"))
    legacy["request"].pop("crossword_size")
    assert verify_bundle(legacy) == 1
    sized = engine.build(Request("crossword", "crossword", crossword_size=15))
    assert sized["items"][0]["crosswordData"]["size"] == 15
    assert verify_bundle(sized) == 1


def test_unconnectable_words_do_not_trigger_implicit_resize_or_dropped_words():
    vocab = [(w, w) for w in ("AAA", "BBB", "CCC")]
    assert recommend_size(vocab, 3)["recommended"] is None
    with pytest.raises(ValueError, match="selected size was not changed"):
        construct("logic", 3, random.Random(7), vocab, board_size=15)


def test_cli_size_and_preview_required_word_error(tmp_path):
    import json

    path = tmp_path / "sized.json"
    assert main(["generate", "--type", "crossword", "--subject", "space",
                 "--crossword-size", "15", "--out", str(path)]) == 0
    assert json.loads(path.read_text())["items"][0]["crosswordData"]["size"] == 15
    assert main(["check", str(path)]) == 0
    engine = Generator()
    plan = prepare(Brief(qtype="crossword", subject="dolphin", crossword_size=5),
                   engine.dictionary)
    assert not plan["ready"] and "DOLPHIN" in plan["message"]
    assert plan["crossword_recommendation"]["recommended"] >= 7
