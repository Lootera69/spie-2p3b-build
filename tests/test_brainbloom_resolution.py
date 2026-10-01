"""Automatic meaning choice remains deterministic, attributable and overridable."""

import json

import pytest

from spie.questions.brainbloom import coverage_sources
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.lexicon import DEFAULT_WORDNET, Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.topics import lookup_many


@pytest.mark.parametrize("topic", [
    "machine learning", "cybersecurity", "renewable energy", "robotics",
    "plate tectonics", "genetics", "cricket", "neuroscience", "ransomware",
])
def test_single_and_combined_choose_latest_authored_identity_and_keep_old_override(topic):
    dictionary = Dictionary()
    single = dictionary.lookup(topic)
    combined = lookup_many(dictionary, topic)
    assert single["status"] == combined["status"] == "ready"
    selected = single["context"]["sense"]
    assert selected.startswith("coverage-v2:")
    assert combined["meanings"] == {topic: selected}
    assert combined["groups"][0]["selection_mode"] == "automatic"
    assert "latest authored" in combined["groups"][0]["selection_reason"]
    old = selected.replace("coverage-v2:", "coverage-v1:")
    assert old in {row["id"] for row in single["choices"]}
    explicit = dictionary.lookup(topic, old)
    explicit_many = lookup_many(dictionary, topic, {topic: old}, strict=True)
    assert explicit["context"]["sense"] == explicit_many["meanings"][topic] == old
    assert explicit_many["groups"][0]["selection_mode"] == "explicit"
    assert explicit["context"]["source"]["snapshot_sha256"] == coverage_sources.PACKS_SHA256
    assert single["context"]["source"]["snapshot_sha256"] == coverage_sources.PACKS_V2_SHA256


@pytest.mark.parametrize("term", [
    "space123", "spacé", "space中", "ſpace", "ſtar", "space\U0001f4a5", "space\u200b",
    "space_123", "space@unknown",
])
def test_unsupported_input_is_preserved_instead_of_becoming_an_exact_topic(term):
    dictionary = Dictionary()
    assert dictionary._matches(term) == []
    assert dictionary.lookup(term)["status"] == "unknown"
    report = lookup_many(dictionary, "ocean, " + term)
    assert report["status"] == "unknown"
    assert report["unknown_terms"] == [term]
    assert report["meanings"] == {"ocean": "pack:ocean"}
    assert "context" not in report


def test_a_hyphenated_compound_has_explicit_normalization_provenance():
    report = Dictionary().lookup("black-hole")
    assert report["context"]["sense"] == "pack:black hole"
    chosen = next(c for c in report["choices"] if c["id"] == report["context"]["sense"])
    assert chosen["normalization"] == "compound"
    assert chosen["provenance"] == "separator-compound"


@pytest.mark.parametrize("term,normalized", [("gal-axy", "galaxy"), ("gal axy", "galaxy")])
def test_authored_word_compounds_are_not_reported_as_exact_input(term, normalized):
    dictionary = Dictionary()
    single, combined = dictionary.lookup(term), lookup_many(dictionary, term)
    for choices in (single["choices"], combined["groups"][0]["choices"]):
        choice = next(c for c in choices if c["id"] == "word:space:GALAXY")
        assert choice["normalization"] == "compound"
        assert choice["normalized_term"] == normalized


def test_supported_prose_punctuation_and_ascii_case_still_resolve():
    dictionary = Dictionary()
    text = 'Please create puzzles about "SPACE", (OCEAN)!'
    single = dictionary.lookup(text)
    assert single["status"] == "ready" and single["unmatched_terms"] == []
    combined = lookup_many(dictionary, text)
    assert combined["status"] == "ready" and combined["unknown_terms"] == []
    assert combined["meanings"] == {"space": "pack:space", "ocean": "pack:ocean"}


def fixture_dictionary():
    dictionary = Dictionary()
    dictionary.source = {
        "name": "Fixture lexical source", "sha256": "fixture", "license": "Fixture"
    }
    for sid, words, definition in [
        ("wn:n:1", ["bank", "lender", "credit", "money", "loan", "fund", "cash", "debt"],
         "A financial institution lending money"),
        ("wn:n:2", ["bank", "shore", "river", "water", "stream", "sand", "coast", "land"],
         "Land beside a river"),
        ("wn:n:3", ["bank"], "A very narrow meaning with no puzzle vocabulary"),
    ]:
        dictionary.synsets[sid] = {"words": words, "definition": definition, "links": []}
    dictionary.index["bank"] = ["wn:n:3", "wn:n:2", "wn:n:1"]
    return dictionary


def test_lexical_selection_uses_context_and_capacity_without_erasing_ambiguity():
    dictionary = fixture_dictionary()
    choices = dictionary._matches("bank")
    chosen, selection = dictionary.select(choices, context="bank, river")
    assert chosen["id"] == "wn:n:2"
    assert selection["context_matches"] == ["river"]
    chosen, selection = dictionary.select(choices, context="bank, money")
    assert chosen["id"] == "wn:n:1"
    assert selection["context_matches"] == ["money"]
    assert selection["alternatives"] == 2
    assert dictionary.select(choices) == dictionary.select(list(reversed(choices)))
    assert dictionary.select(choices)[0]["id"] != "wn:n:3"
    forced, selection = dictionary.select(choices, "wn:n:2", context="bank, money")
    assert forced["id"] == "wn:n:2" and selection["mode"] == "explicit"


def test_authored_pack_and_alias_win_with_real_corpora_without_hiding_lexical_choices():
    if not DEFAULT_WORDNET.exists() or not coverage_sources.DEFAULT_OEWN.exists():
        pytest.skip("Optional pinned lexical corpora are not installed")
    dictionary = Dictionary(DEFAULT_WORDNET, oewn=coverage_sources.DEFAULT_OEWN)
    for topic, sense in [("space", "pack:space"), ("solar system", "pack:space"),
                         ("photosynthesis", "pack:photosynthesis"),
                         ("machine learning", "coverage-v2:machine-learning")]:
        single = dictionary.lookup(topic)
        combined = lookup_many(dictionary, topic)
        assert single["status"] == combined["status"] == "ready"
        assert single["context"]["sense"] == combined["meanings"][topic] == sense
        assert any(c["id"].startswith(("wn:", "oewn2024:")) for c in single["choices"])
    bank = dictionary.lookup("bank")
    assert bank["status"] == "ready" and len(bank["context"]["entries"]) >= 8
    assert "financial institution" in bank["context"]["definition"]
    assert lookup_many(dictionary, "bank, crane")["status"] == "ready"


def test_automatic_bundle_replays_from_embedded_vocabulary_without_resolving_again(monkeypatch):
    bundle = Generator().build(Request("dictionary", "type-answer", subject="machine learning",
                                       topic_mode="combined", seed=31))
    assert bundle["request"]["meanings"] == {"machine learning": "coverage-v2:machine-learning"}
    monkeypatch.setattr(Dictionary, "select",
                        lambda *_a, **_k: pytest.fail("Replay selected a live meaning"))
    monkeypatch.setattr(Dictionary, "__init__",
                        lambda *_a, **_k: pytest.fail("Replay loaded a live dictionary"))
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1
