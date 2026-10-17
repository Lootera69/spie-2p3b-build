"""Corpus discovery, topic fidelity, offline replay and revision-16 compatibility."""

import copy
import json
import socket
from pathlib import Path

import pytest

from spie.forge.corpus import digest
from spie.questions.brainbloom import crossword_corpus as corpus
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.lexicon import WORDNET_SHA256, Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.workshop import candidate, generate


@pytest.fixture(scope="module")
def installed():
    try:
        return corpus.installed_dictionary()
    except ValueError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def fixture_dictionary():
    """A newly indexed topic, deliberately absent from the shipped topic banks."""
    dictionary = Dictionary(coverage=False)
    root = "wn:n:90000000"
    dictionary.source = {"name": "Princeton WordNet 3.0", "sha256": WORDNET_SHA256,
                         "license": "Synthetic test definitions, not corpus content"}
    dictionary.synsets[root] = {"words": ["stonecraft"],
                                "definition": "The craft of architectural masonry",
                                "links": []}
    pairs = [
        ("quoin", "A dressed stone at the corner of a building"),
        ("corbel", "A projection supporting a structure above it"),
        ("cyma", "A molding with a curved profile"),
        ("truss", "A framework that supports a roof"),
        ("lintel", "A horizontal support over a doorway"),
        ("mullion", "A vertical division between window panes"),
        ("architrave", "The lowest horizontal part of an entablature"),
        ("abutment", "A structure supporting the end of a bridge"),
    ]
    for index, (word, definition) in enumerate(pairs, 1):
        sid = f"wn:n:{90000000 + index}"
        dictionary.synsets[root]["links"].append(("~", sid))
        dictionary.synsets[sid] = {"words": [word], "definition": definition,
                                   "links": [("@", root)]}
        dictionary.index[word].append(sid)
    dictionary.index["stonecraft"].append(root)
    return dictionary


def test_a_new_corpus_topic_works_with_all_legacy_answer_banks_disabled(
    fixture_dictionary, monkeypatch,
):
    from spie.questions.brainbloom import crossword_learning_words, crossword_vocabulary, vocabulary

    def forbidden(*args, **kwargs):
        pytest.fail("A new crossword consulted a legacy answer-bank path")

    engine = Generator()
    engine.dictionary = fixture_dictionary
    monkeypatch.setattr(crossword_learning_words, "BANKS", {})
    monkeypatch.setattr(vocabulary, "PACKS", {})
    monkeypatch.setattr(crossword_vocabulary, "prepare_context", forbidden)
    monkeypatch.setattr(crossword_vocabulary, "builtin_vocabulary", forbidden)
    monkeypatch.setattr(Dictionary, "_entries", forbidden)
    report = prepare(Brief(qtype="crossword", subject="stonecraft", difficulty="hard"),
                     fixture_dictionary)
    assert report["ready"], report["message"]
    result = engine.build(Request(**report["request"]))
    assert len(result["items"][0]["crosswordData"]["clues"]) == 7
    assert result["dictionary"] == report["lookup"]["context"]
    assert verify_bundle(result) == 1


def test_new_dictionary_entries_become_available_without_editing_answer_lists(fixture_dictionary):
    before = corpus.lookup(fixture_dictionary, "stonecraft", {}, "puzzles")["context"]
    updated = copy.deepcopy(fixture_dictionary)
    root, sid = "wn:n:90000000", "wn:n:90000100"
    updated.synsets[sid] = {"words": ["spire"], "definition": "A tall tapering church tower",
                            "links": [("@", root)]}
    updated.synsets[root]["links"].append(("~", sid))
    after = corpus.lookup(updated, "stonecraft", {}, "puzzles")["context"]
    assert "SPIRE" not in {e["word"] for e in before["entries"]}
    assert "SPIRE" in {e["word"] for e in after["entries"]}


@pytest.mark.parametrize("word,clue,allowed", [
    ("IBEX", "A mountain goat with long curved horns", True),
    ("XYLEM", "The woody tissue carrying water through a plant", True),
    ("INFORMATION", "Facts communicated about a subject", False),
    ("WATER", "A liquid essential to living organisms", False),
    ("XYZZYWORD", "An invented and unattested string", False),
    ("IBEX", "An ibex is a mountain goat", False),
    ("IBEX", "An obsolete spelling for a goat", False),
    ("LXX", "being ten more than sixty", False),
])
def test_one_familiarity_and_definition_policy_applies_to_every_word(word, clue, allowed):
    assert corpus.eligible(word, clue) is allowed


@pytest.mark.parametrize("definition,allowed", [
    ("A mountain goat with long curved horns", True),
    ("A mountain ibex with long curved horns", False),
    ("A group of wild IBEXES in the mountains", False),
    ("An ibexlike goat with long curved horns", True),
    ("A mountain \u0131bex with long curved horns", False),
])
def test_fast_clue_screen_preserves_word_boundaries_and_unicode(definition, allowed):
    node = {"words": ["ibex"], "definition": definition}
    entries = list(corpus._node_entries(node, "wn:n:90000000", ["wn:n:90000000"]))
    assert bool(entries) is allowed
    if entries:
        assert entries[0]["definition"] == definition


def test_general_wordnet_pool_preserves_all_revision17_candidates(installed):
    if not installed.synsets:
        pytest.skip("Princeton WordNet is needed for the revision-17 pool fingerprint")
    dictionary = copy.copy(installed)
    dictionary.oewn_synsets = {}
    dictionary.oewn_index = {}
    entries = corpus._discover(dictionary, corpus.GENERAL)
    assert len(entries) == 29949
    assert digest(entries) == "c6a1c8c90075f9d34e757510911ea649cc8695afc34755cdf5970a7550172bc2"


@pytest.mark.parametrize("subject", [
    "astronomy", "ocean", "plants", "cricket", "music", "architecture", "geology",
    "neuroscience", "entomology", "heraldry", "dolphin",
])
@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_varied_corpus_topics_produce_connected_learning_crosswords(
    subject, difficulty, installed,
):
    engine = Generator()
    engine.dictionary = installed
    report = prepare(Brief(qtype="crossword", subject=subject, difficulty=difficulty, seed=31),
                     installed)
    assert report["ready"], report["message"]
    result = engine.build(Request(**report["request"]))
    assert result["dictionary"] == report["lookup"]["context"]
    assert verify_bundle(json.loads(json.dumps(result))) == 1
    item, proof = result["items"][0], result["proofs"][0]
    clues = item["crosswordData"]["clues"]
    assert len(clues) == {"easy": 3, "medium": 5, "hard": 7}[difficulty]
    assert proof["grid_checks"]["connected"]
    assert proof["topic_coverage"][0]["used_words"]
    for clue in clues:
        assert corpus.eligible(clue["answer"], clue["clue"])
        assert f"{clue['answer']} — {clue['clue']}" in item["correctExplanation"]
    assert "Vocabulary recap:" not in item["question"] + item["lessonContent"]


@pytest.mark.parametrize("sense,unrelated", [
    ("wn:n:06095022", {"DABBLE"}),
    ("wn:n:00476389", {"TEDIOUS", "IRKSOME"}),
    ("wn:n:06081833", {"ANTECEDENT", "FORERUNNER"}),
    ("wn:n:08500433", {"BEDSIDE", "CAVERN", "FORNIX", "POUCH"}),
    ("wn:n:06072275", {"DOER", "LABORER"}),
])
def test_incidental_examples_and_wrong_senses_do_not_supply_answers(sense, unrelated, installed):
    if sense not in installed.synsets:
        pytest.skip("Princeton WordNet is needed for this corpus regression")
    words = {e["word"] for e in corpus._discover(installed, sense)}
    assert not words & unrelated


def test_biological_and_industrial_plant_meanings_stay_separate(installed):
    if "wn:n:00017222" not in installed.synsets:
        pytest.skip("Princeton WordNet is needed for this corpus regression")
    natural = corpus.lookup(installed, "plants", {}, "puzzles")["context"]
    assert natural["topics"][0]["sense"] == "wn:n:00017222"
    factory = corpus.lookup(installed, "plants", {"plants": "wn:n:03956922"}, "puzzles",
                            strict=True)["context"]
    assert factory["topics"][0]["sense"] == "wn:n:03956922"
    assert "DISTILLERY" not in {e["word"] for e in natural["entries"]}
    assert not {e["word"] for e in factory["entries"]} & {"PHOTOSYNTHESIS", "HORTICULTURE"}
    assert {e["path"][0] for e in factory["entries"]} == {"wn:n:03956922"}


@pytest.mark.parametrize("subject", ["plants", "music", ""])
def test_seed_changes_discovered_vocabulary_as_well_as_layout(subject, installed):
    first = corpus.lookup(installed, subject, {}, "puzzles", seed=7)["context"]
    second = corpus.lookup(installed, subject, {}, "puzzles", seed=19)["context"]
    again = corpus.lookup(installed, subject, {}, "puzzles", seed=7)["context"]
    assert len(first["entries"]) == len(second["entries"]) == 80
    assert {e["word"] for e in first["entries"]} != {e["word"] for e in second["entries"]}
    assert first == again


def test_general_vocabulary_excludes_numerals_and_source_initialisms(installed):
    words = {e["word"] for e in corpus._discover(installed, corpus.GENERAL)}
    assert not words & {"LXX", "XXX", "BPM", "RPM"}
    assert "MIX" not in words or any(e["word"] == "MIX" and "number" not in e["definition"]
                                     for e in corpus._discover(installed, corpus.GENERAL))


def test_oewn_alone_supports_automatic_retrieval_and_offline_replay(installed):
    if not installed.oewn_synsets:
        pytest.skip("Open English WordNet is needed for this corpus regression")
    dictionary = copy.copy(installed)
    dictionary.synsets, dictionary.index, dictionary.wordnet_rank = {}, {}, {}
    dictionary.source = None
    request = Request("dictionary", "crossword", subject="entomology", seed=19)
    context = corpus.resolve(request, dictionary)
    assert all(e["sense"].startswith("oewn2024:") for e in context["entries"])
    assert verify_bundle(generate(request, context=context)) == 1


def test_disabled_oewn_is_not_reenabled_by_crossword_auto_discovery(monkeypatch, tmp_path):
    dictionary = Dictionary(coverage=False)
    dictionary.crossword_allow_oewn = False
    oewn_path = tmp_path / "present.xml.gz"
    oewn_path.write_bytes(b"Must not be read when this source is disabled")
    monkeypatch.setattr(corpus, "DEFAULT_WORDNET", tmp_path / "missing.zip")
    monkeypatch.setattr(corpus.coverage_sources, "DEFAULT_OEWN", oewn_path)
    with pytest.raises(ValueError, match="local dictionary corpus"):
        corpus.resolve(Request("dictionary", "crossword", subject="ocean"), dictionary)


@pytest.mark.parametrize("category", ["logic", "puzzles", "science", "riddles"])
def test_unthemed_builtin_requests_use_general_corpus_vocabulary(category, fixture_dictionary):
    request = Request("crossword", "crossword", category=category)
    context = corpus.resolve(request, fixture_dictionary)
    result = generate(request, context=context)
    assert result["request"]["topic"] == "dictionary"
    assert result["dictionary"]["sense"] == corpus.GENERAL
    assert result["version"] == 3
    assert verify_bundle(result) == 1


def test_narrow_and_unknown_topics_offer_guidance_without_filler(fixture_dictionary):
    root = "wn:n:90000000"
    fixture_dictionary.synsets[root]["links"] = fixture_dictionary.synsets[root]["links"][:2]
    report = prepare(Brief(qtype="crossword", subject="stonecraft"), fixture_dictionary)
    assert not report["ready"]
    assert "broader" in report["message"]
    with pytest.raises(ValueError, match="fewer than four uncommon"):
        corpus.resolve(Request("dictionary", "crossword", subject="stonecraft"),
                       fixture_dictionary)
    unknown = corpus.lookup(fixture_dictionary, "xyzzynonsense", {}, "puzzles")
    assert unknown["status"] == "unknown" and "xyzzynonsense" in unknown["message"]
    assert "context" not in unknown


def test_missing_corpus_explains_installation_and_does_not_use_answer_banks(monkeypatch, tmp_path):
    monkeypatch.setattr(corpus, "DEFAULT_WORDNET", tmp_path / "missing.zip")
    monkeypatch.setattr(corpus.coverage_sources, "DEFAULT_OEWN", tmp_path / "missing.xml.gz")
    report = prepare(Brief(qtype="crossword", subject="space"), Dictionary())
    assert not report["ready"]
    assert "dictionary-install" in report["message"] and "oewn-install" in report["message"]
    assert all(not a["available"] for a in report["activities"])
    with pytest.raises(ValueError, match="local dictionary corpus"):
        generate(Request("crossword", "crossword"))


def test_saved_puzzles_replay_with_dictionary_and_network_access_disabled(
    fixture_dictionary, monkeypatch,
):
    request = Request("dictionary", "crossword", subject="stonecraft", seed=23,
                      topic_mode="combined")
    context = corpus.resolve(request, fixture_dictionary)
    result = generate(request, context=context)

    def forbidden(*args, **kwargs):
        pytest.fail("Saved replay attempted to discover vocabulary again")

    monkeypatch.setattr(corpus, "installed_dictionary", forbidden)
    monkeypatch.setattr(corpus, "_discover", forbidden)
    monkeypatch.setattr(Dictionary, "__init__", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert verify_bundle(json.loads(json.dumps(result))) == 1


@pytest.mark.parametrize("mutation", ["policy", "word", "clue", "source", "seed",
                                       "terminal", "sense", "anchor", "missing"])
def test_changed_snapshots_cannot_replay_as_the_original(mutation, fixture_dictionary):
    request = Request("dictionary", "crossword", subject="stonecraft")
    result = generate(request, context=corpus.resolve(request, fixture_dictionary))
    context = result["dictionary"]
    if mutation == "policy":
        context["crossword_learning"]["zipf_hundredths_range"][1] = 900
    elif mutation == "word":
        context["entries"][0]["word"] = "WATER"
    elif mutation == "clue":
        context["entries"][0]["definition"] = "A changed definition without any provenance"
    elif mutation == "source":
        context["source"]["name"] = "Changed attribution"
    elif mutation == "seed":
        context["crossword_retrieval_seed"] += 1
    elif mutation == "terminal":
        context["entries"][0]["path"][-1] = "definition:wn:n:99999999"
    elif mutation == "sense":
        context["entries"][0]["sense"] = "pack:space"
    elif mutation == "anchor":
        context["crossword_anchor"] = context["entries"][0]["word"]
    else:
        context.pop("crossword_learning")
    with pytest.raises(ValueError):
        verify_bundle(result)


def test_direct_candidates_and_browser_number_round_trips_preserve_replay(fixture_dictionary):
    request = Request("dictionary", "crossword", subject="stonecraft", seed=17)
    context = corpus.resolve(request, fixture_dictionary)
    unchanged = copy.deepcopy(context)
    result = generate(request, context=context)
    assert candidate(request, request.seed, context) == (result["items"][0], result["proofs"][0])
    assert context == unchanged
    browser = json.loads(json.dumps(result), parse_float=lambda value: (
        int(float(value)) if float(value).is_integer() else float(value)))
    assert verify_bundle(browser) == 1
    result["proofs"][0]["learning_vocabulary"]["zipf_hundredths_range"][1] = 999
    assert generate(request, context=context) == browser
    with pytest.raises(ValueError, match="seed does not match"):
        generate(Request("dictionary", "crossword", subject="stonecraft", seed=18),
                 context=context)


REVISION_16 = json.loads((Path(__file__).parent / "fixtures/crosswords_revision16.json")
                         .read_text(encoding="utf-8"))


@pytest.mark.parametrize("record", REVISION_16)
def test_revision_16_outputs_remain_identical(record):
    result = generate(Request(**record["request"]))
    assert digest(result) == record["sha256"]
    assert verify_bundle(result) == 1
