"""Topic grounding, independent answer checks, offline replay, and actual WordNet."""

import io
import json
import math
import socket
import subprocess
from collections import Counter
from http.client import HTTPConnection
from itertools import permutations
from threading import Thread

import pytest

from spie.forge.corpus import compact
from spie.questions.brainbloom import Request
from spie.questions.brainbloom.__main__ import main
from spie.questions.brainbloom.catalog import TYPES
from spie.questions.brainbloom.lexicon import DEFAULT_WORDNET, Dictionary, install_wordnet
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.web import LocalHTTPServer, handler_for
from spie.questions.brainbloom.workshop import generate


def test_topic_phrase_matching_and_automatic_selection_with_explicit_override():
    dictionary = Dictionary()
    report = dictionary.lookup("Please create puzzles about ocean")
    assert report["status"] == "ready"
    assert report["context"]["sense"] == "pack:ocean"
    assert report["unmatched_terms"] == []
    automatic = dictionary.lookup("ocean and space")
    assert automatic["status"] == "ready"
    assert automatic["selection_mode"] == "automatic"
    chosen = dictionary.lookup("ocean and space", "pack:space")
    assert chosen["context"]["sense"] == "pack:space"
    assert dictionary.lookup("quantumxyz ocean")["unmatched_terms"] == ["quantumxyz"]
    with pytest.raises(ValueError, match="no longer matches"):
        dictionary.lookup("animals", "pack:space")


def test_unknown_input_never_falls_back_to_unrelated_questions():
    dictionary = Dictionary()
    assert dictionary.lookup("xyzzynonsense")["status"] == "unknown"
    with pytest.raises(ValueError, match="No dictionary topic"):
        Generator().build(Request("dictionary", subject="xyzzynonsense"))


@pytest.mark.parametrize("subject", ["space", "animals", "plants", "ocean"])
@pytest.mark.parametrize("kind", TYPES)
def test_topics_drive_content_and_exports(subject, kind):
    request = Request("dictionary", kind, subject=subject, count=2, seed=15)
    result = Generator().build(request)
    words = {e["word"] for e in result["dictionary"]["entries"]}
    assert subject in result["items"][0]["question"]
    assert verify_bundle(json.loads(compact(result))) == 2
    assert compact(result) == compact(Generator().build(request))
    for item, proof in zip(result["items"], result["proofs"], strict=True):
        if kind == "crossword":
            assert {c["answer"] for c in item["crosswordData"]["clues"]} <= words
        elif kind == "wonder":
            assert proof["arrangements"] == proof["independent_count"]
        else:
            assert set(proof["word_bank"]) <= words
            assert len(proof["survivors"]) == 1
            assert proof["survivors"] == proof["independent_survivors"]


@pytest.mark.parametrize("variation", ["anagram", "missing-letters", "word-order"])
@pytest.mark.parametrize("kind", ["multiple-choice", "true-false", "type-answer", "riddle"])
def test_answer_matches_constraints_independently(variation, kind):
    result = generate(Request("dictionary", kind, count=4, subject="space", variation=variation))
    for item, proof in zip(result["items"], result["proofs"], strict=True):
        rule = proof["constraints"]
        bank = proof["word_bank"]
        if variation == "anagram":
            valid = [word for word in bank if Counter(word) == Counter(rule["letters"])
                     and word.startswith(rule["prefix"])]
        elif variation == "missing-letters":
            valid = [word for word in bank if len(word) == len(rule["pattern"])
                     and all(char == "_" or word[i] == char
                             for i, char in enumerate(rule["pattern"]))]
        else:
            valid = [sorted(bank)[rule["position"] - 1]]
        assert len(valid) == 1
        if kind == "true-false":
            assert item["correctAnswer"] == str(proof["claim"] in valid)
        else:
            assert item["correctAnswer"] == valid[0]
        if kind == "multiple-choice":
            assert sum(choice in valid for choice in item["choices"]) == 1


def test_anagram_collisions_are_disambiguated_by_explicit_prefix():
    context = Dictionary().resolve("space", "", "logic")
    context["entries"] = [
        {"word": word, "definition": "Fixture meaning", "sense": "fixture", "path": ["fixture"]}
        for word in ("EAST", "SEAT", "TEAS", "EATS")
    ]
    result = generate(Request("dictionary", subject="space", variation="anagram"), context=context)
    proof = result["proofs"][0]
    assert proof["constraints"]["prefix"]
    assert len(proof["survivors"]) == 1
    assert "starts with" in result["items"][0]["question"]


def test_wonder_repeated_letters_agree_with_exhaustive_permutations():
    context = Dictionary().resolve("space", "", "logic")
    context["entries"] = [
        {"word": word, "definition": "Fixture meaning", "sense": "fixture", "path": ["fixture"]}
        for word in ("EEL", "EGG", "EYE", "TOOT")
    ]
    result = generate(Request("dictionary", "wonder", subject="space"), context=context)
    proof = result["proofs"][0]
    letters = "".join(c * n for c, n in proof["counts"].items())
    assert proof["arrangements"] == len(set(permutations(letters)))
    assert proof["arrangements"] < math.factorial(len(letters))


@pytest.mark.parametrize(
    "mutation", ["definition", "source", "word", "sense", "subject", "missing"]
)
def test_dictionary_replay_rejects_tampering(mutation):
    result = generate(Request("dictionary", subject="space"))
    if mutation == "definition":
        result["dictionary"]["entries"][0]["definition"] = "Changed meaning"
    elif mutation == "source":
        result["dictionary"]["source"]["name"] = "Changed source"
    elif mutation == "word":
        result["dictionary"]["entries"][0]["word"] = "123"
    elif mutation == "missing":
        result.pop("dictionary")
    else:
        result["dictionary"][mutation] = "changed"
    with pytest.raises(ValueError):
        verify_bundle(result)


def test_dictionary_generation_and_replay_never_use_network_or_models(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Generation attempted network or a model subprocess")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    for kind in TYPES:
        result = Generator().build(Request("dictionary", kind, subject="ocean"))
        assert verify_bundle(result) == 1


def test_too_narrow_vocabulary_and_oversized_batch_have_actionable_errors():
    context = Dictionary().resolve("space", "", "logic")
    context["entries"] = context["entries"][:4]
    with pytest.raises(ValueError, match="at least 7 words"):
        generate(Request("dictionary", "crossword", "hard", subject="space"), context=context)
    with pytest.raises(ValueError, match="No partial batch exported"):
        generate(Request("dictionary", "wonder", count=20, subject="space"))


@pytest.mark.parametrize("kwargs", [
    {"subject": None}, {"subject": "x" * 201}, {"sense": []}, {"variation": "LLM"},
    {"topic": "motion", "category": "science", "subject": "space"},
    {"qtype": "wonder", "variation": "anagram"},
])
def test_invalid_topic_controls_are_not_silently_ignored(kwargs):
    with pytest.raises(ValueError):
        Request(**{"topic": "dictionary", **kwargs})


def test_installer_rejects_corrupt_download_and_preserves_existing(monkeypatch, tmp_path):
    import spie.questions.brainbloom.lexicon as lexicon
    monkeypatch.setattr(lexicon.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"invalid"))
    target = tmp_path / "wordnet.zip"
    with pytest.raises(ValueError, match="SHA256"):
        install_wordnet(target)
    assert not target.exists()
    target.write_bytes(b"existing")
    with pytest.raises(ValueError, match="already exists"):
        install_wordnet(target)
    assert target.read_bytes() == b"existing"


@pytest.fixture(scope="module")
def wordnet_dictionary():
    if not DEFAULT_WORDNET.exists():
        pytest.skip("Optional pinned WordNet corpus is not installed")
    return Dictionary(DEFAULT_WORDNET)


def test_real_wordnet_senses_stay_separate_and_attributed(wordnet_dictionary):
    dictionary = wordnet_dictionary
    assert dictionary.configuration()["indexed_terms"] > 140_000
    report = dictionary.lookup("bank")
    assert report["status"] == "ready" and report["selection_mode"] == "automatic"
    assert len(report["context"]["entries"]) >= 8
    choices = dictionary.lookup("bank")["choices"]
    river = next(row for row in choices if "sloping land" in row["definition"])
    money = next(row for row in choices if "financial institution" in row["definition"])
    river_context = dictionary.resolve("bank", river["id"], "puzzles")
    money_context = dictionary.resolve("bank", money["id"], "puzzles")
    assert river_context["entries"] != money_context["entries"]
    assert "WordNet 3.0 Copyright" in river_context["source"]["license"]
    assert all(e["path"][0] == river["id"] for e in river_context["entries"])
    assert not any(e["sense"] == money["id"] for e in river_context["entries"])


@pytest.mark.parametrize("kind", TYPES)
def test_wordnet_bundles_replay_without_the_dictionary_file(wordnet_dictionary, monkeypatch, kind):
    dictionary = wordnet_dictionary
    report = dictionary.lookup("vehicle")
    sense = next(c["id"] for c in report["choices"] if "conveyance" in c["definition"])
    request = Request("dictionary", kind, subject="vehicle", sense=sense)
    context = dictionary.resolve(request.subject, sense, request.category)
    result = generate(request, context=context)
    monkeypatch.setattr(
        Dictionary, "_load_wordnet", lambda *_: pytest.fail("Replay loaded a corpus")
    )
    assert verify_bundle(result) == 1


def test_wordnet_compounds_are_usable_without_spaces(wordnet_dictionary):
    sense = wordnet_dictionary.index["photosynthesis"][0]
    entries, source = wordnet_dictionary._entries(sense)
    assert "LIGHTREACTION" in {entry["word"] for entry in entries}
    assert len(entries) >= 4
    assert source["name"] == "Princeton WordNet 3.0"


def test_cli_topic_input_and_replay(tmp_path, capsys):
    out = tmp_path / "topic.json"
    assert main(["generate", "--subject", "animals", "--type", "riddle", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["request"]["topic"] == "dictionary"
    assert main(["check", str(out)]) == 0
    assert main(["topics", "ocean"]) == 0
    assert "pack:ocean" in capsys.readouterr().out


def test_http_topic_resolution_and_generation():
    server = LocalHTTPServer(("127.0.0.1", 0), handler_for(Generator()))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def post(path, data):
        conn = HTTPConnection(*server.server_address, timeout=10)
        try:
            conn.request("POST", path, json.dumps(data), {"Content-Type": "application/json"})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()
    try:
        status, report = post("/api/topics", {"subject": "ocean"})
        assert status == 200 and report["status"] == "ready"
        status, bundle = post("/api/generate", {
            "topic": "dictionary", "subject": "ocean", "sense": report["context"]["sense"],
            "qtype": "riddle", "variation": "anagram",
        })
        assert status == 200 and verify_bundle(bundle) == 1
        assert post("/api/topics", {"subject": []})[0] == 400
        assert post("/api/topics", {"subject": "space", "category": []})[0] == 400
        assert post("/api/topics", {"subject": "space", "filename": "x"})[0] == 400
        assert post("/api/generate", {"topic": "dictionary", "subject": "xyzzynonsense"})[0] == 422
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
