"""Whole-brief compatibility, multi-meaning retention and actual in-puzzle topic coverage."""

import json
from http.client import HTTPConnection
from threading import Thread

import pytest

from spie.forge.corpus import digest
from spie.questions.brainbloom import Request
from spie.questions.brainbloom.__main__ import main
from spie.questions.brainbloom.brief import ACTIVITIES, Brief, prepare
from spie.questions.brainbloom.catalog import CATEGORIES, TOPICS, TYPES
from spie.questions.brainbloom.lexicon import DEFAULT_WORDNET, Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.topics import coverage, lookup_many, resolve_many
from spie.questions.brainbloom.web import LocalHTTPServer, handler_for


class AmbiguousDictionary(Dictionary):
    definitions = {
        "bank": [("river", "Land beside a river"), ("money", "A financial institution")],
        "crane": [("bird", "A long-legged bird"), ("machine", "A lifting machine")],
    }

    def _matches(self, term):
        if term not in self.definitions:
            return super()._matches(term)
        return [{"term": term, "id": f"fixture:{term}:{key}", "definition": definition}
                for key, definition in self.definitions[term]]

    def _entries(self, sense):
        if not sense.startswith("fixture:"):
            return super()._entries(sense)
        _, term, meaning = sense.split(":")
        pack = {"river": "ocean", "money": "puzzles", "bird": "animals", "machine": "science"}
        entries, source = super()._entries("pack:" + pack[meaning])
        root = {"word": term.upper(), "definition": dict(self.definitions[term])[meaning],
                "sense": sense, "path": [sense]}
        return [root, *entries], {**source, "sha256": digest([root, *entries])}


def test_multiword_lookup_covers_each_nonoverlapping_phrase_and_unknown_token():
    dictionary = Dictionary()
    report = lookup_many(dictionary, "Please make puzzles about solar system, ocean and animals")
    assert report["status"] == "ready"
    assert [g["term"] for g in report["groups"]] == ["solar system", "ocean", "animals"]
    assert len(report["context"]["topics"]) == 3
    unknown = lookup_many(dictionary, "space, ocean, unknownxyz, 植物, space123")
    assert unknown["status"] == "unknown"
    assert unknown["unknown_terms"] == ["unknownxyz", "植物", "space123"]
    assert "context" not in unknown
    assert set(unknown["meanings"]) == {"space", "ocean"}


def test_each_ambiguous_word_keeps_its_own_selected_meaning():
    dictionary = AmbiguousDictionary()
    first = lookup_many(dictionary, "bank, crane")
    assert first["status"] == "ready" and len(first["groups"]) == 2
    assert all(group["selection_mode"] == "automatic" for group in first["groups"])
    second = lookup_many(dictionary, "bank, crane", {"bank": "fixture:bank:money"})
    assert second["status"] == "ready"
    assert second["meanings"]["bank"] == "fixture:bank:money"
    assert second["groups"][0]["selection_mode"] == "explicit"
    assert second["groups"][1]["selection_mode"] == "automatic"
    choices = {"bank": "fixture:bank:money", "crane": "fixture:crane:bird"}
    ready = lookup_many(dictionary, "bank, crane", choices)
    assert ready["status"] == "ready"
    assert ready["meanings"] == choices
    assert [t["anchor"] for t in ready["context"]["topics"]] == ["BANK", "CRANE"]
    changed = lookup_many(dictionary, "bank, crane", {**choices, "bank": "fixture:bank:river"})
    assert changed["meanings"]["crane"] == choices["crane"]
    assert changed["context"]["topics"][0]["sense"] == "fixture:bank:river"


def test_meanings_for_removed_topics_are_pruned_only_in_preview():
    dictionary = Dictionary()
    meanings = {"space": "pack:space", "ocean": "pack:ocean"}
    report = lookup_many(dictionary, "space, animals", meanings)
    assert report["meanings"] == {"space": "pack:space", "animals": "pack:animals"}
    with pytest.raises(ValueError, match="no longer belong"):
        resolve_many(dictionary, "space, animals", meanings, "logic")


def test_existing_authored_words_are_available_without_wordnet():
    report = lookup_many(Dictionary(), "clock, mirror")
    assert report["status"] == "ready"
    assert [t["anchor"] for t in report["context"]["topics"]] == ["CLOCK", "MIRROR"]


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("kind", TYPES)
def test_all_formats_and_categories_include_every_requested_topic(category, kind):
    engine = Generator()
    plan = prepare(Brief(category=category, qtype=kind, subject="space, ocean, animals"),
                   engine.dictionary)
    assert plan["ready"], plan["message"]
    result = engine.build(Request(**plan["request"]))
    assert result["version"] == 5
    assert set(result["request"]["meanings"]) == {"space", "ocean", "animals"}
    assert verify_bundle(json.loads(json.dumps(result))) == 1
    item, proof = result["items"][0], result["proofs"][0]
    assert len(proof["topic_coverage"]) == 3
    if "model" in proof:
        used = proof["model"]["names"]
    elif kind == "crossword":
        used = [c["answer"] for c in item["crosswordData"]["clues"]]
    elif kind == "wonder":
        used = proof["words"]
    else:
        used = proof["word_bank"]
    assert coverage(result["dictionary"], used) == proof["topic_coverage"]
    assert all(t["used_words"] for t in proof["topic_coverage"])


@pytest.mark.parametrize("activity", ["deduction", "bayesian", "planning", "anagram",
                                     "missing-letters", "word-order", "crossword", "word-wonder"])
def test_literal_input_words_are_used_in_the_actual_puzzle(activity):
    dictionary = AmbiguousDictionary()
    engine = Generator()
    engine.dictionary = dictionary
    kind = ("crossword" if activity == "crossword"
            else "wonder" if activity == "word-wonder" else "riddle")
    meanings = {"bank": "fixture:bank:money", "crane": "fixture:crane:bird"}
    plan = prepare(Brief(subject="bank, crane", meanings=meanings, activity=activity, qtype=kind),
                   dictionary)
    assert plan["ready"]
    bundle = engine.build(Request(**plan["request"]))
    for row in bundle["proofs"][0]["topic_coverage"]:
        assert row["term"].upper() in row["used_words"]
    assert bundle["request"]["meanings"] == meanings
    assert verify_bundle(bundle) == 1


def test_unknown_words_cannot_be_dropped_to_make_generation_succeed():
    brief = Brief(subject="space, unknownxyz")
    plan = prepare(brief, Dictionary())
    assert not plan["ready"] and plan["request"] is None
    with pytest.raises(ValueError, match="unknownxyz"):
        Generator().build(Request("dictionary", subject=brief.subject, topic_mode="combined"))


def test_input_limit_and_duplicate_words_are_explained():
    assert len(lookup_many(Dictionary(), "space, space, space")["groups"]) == 1
    with pytest.raises(ValueError, match="at most six"):
        lookup_many(Dictionary(), "space, ocean, animals, plants, science, logic, riddles")


def test_number_of_topics_changes_available_activities_and_difficulties():
    subject = "space, ocean, animals, plants, science, logic"
    impossible = prepare(Brief(subject=subject, activity="bayesian"), Dictionary())
    assert not impossible["ready"] and "4 words" in impossible["message"]
    assert all(not d["available"] for d in impossible["difficulty_options"])
    hard = prepare(Brief(subject=subject, activity="deduction", difficulty="hard"), Dictionary())
    assert hard["ready"]
    assert [d["available"] for d in hard["difficulty_options"]] == [False, False, True]
    easy = prepare(Brief(subject=subject, qtype="crossword", difficulty="easy"), Dictionary())
    assert not easy["ready"]
    assert [d["available"] for d in easy["difficulty_options"]] == [False, False, True]


def test_automatic_reasoning_never_routes_six_topics_to_four_card_bayes():
    result = Generator().build(Request(
        "reasoning", difficulty="hard", subject="space, ocean, animals, plants, science, logic",
        topic_mode="combined", count=2, seed=1,
    ))
    assert all(p["reasoning_style"] != "bayesian" for p in result["proofs"])
    assert all(len(p["topic_coverage"]) == 6 for p in result["proofs"])


def test_reflection_limits_are_real_and_cover_all_words():
    plan = prepare(Brief(subject="clock, mirror", qtype="wonder", count=2), Dictionary())
    assert not plan["ready"] and plan["max_count"] == 1
    ready = prepare(Brief(subject="clock, mirror", qtype="wonder"), Dictionary())
    assert ready["ready"] and not ready["difficulty_relevant"]
    result = Generator().build(Request(**ready["request"]))
    proof = result["proofs"][0]
    assert proof["words"] == ["CLOCK", "MIRROR"]
    assert proof["arrangements_per_word"] == [60, 120]
    assert proof["arrangements"] == 7200


def test_irrelevant_controls_do_not_leak_into_unscored_reflections():
    plan = prepare(Brief(subject="clock, mirror", qtype="wonder", difficulty="hard",
                         search_effort="thorough"), Dictionary())
    assert plan["ready"] and not plan["difficulty_relevant"] and not plan["search_relevant"]
    assert plan["request"]["difficulty"] == "medium"
    assert plan["request"]["search_effort"] == "balanced"


def test_preset_cannot_silently_ignore_custom_topics():
    plan = prepare(Brief(category="science", activity="motion", subject="ocean"), Dictionary())
    assert not plan["ready"] and "cannot use custom topics" in plan["message"]
    ready = prepare(Brief(category="science", activity="motion", subject=""), Dictionary())
    assert ready["ready"] and ready["request"]["subject"] == ""
    assert ready["request"]["topic"] == "motion"


@pytest.mark.parametrize("kind", TYPES)
def test_empty_topics_have_a_visible_compatible_default(kind):
    plan = prepare(Brief(qtype=kind), Dictionary())
    assert plan["ready"]
    if plan["uses_topics"]:
        assert plan["lookup"]["using_category"]
    else:
        assert "built-in" in plan["message"]


@pytest.mark.parametrize("mutation", ["meaning", "remove-topic", "anchor", "coverage", "licence"])
def test_v5_replay_rejects_lost_topics_meanings_and_provenance(mutation):
    plan = prepare(Brief(subject="space, ocean"), Dictionary())
    result = Generator().build(Request(**plan["request"]))
    if mutation == "meaning":
        result["request"]["meanings"].pop("ocean")
    elif mutation == "remove-topic":
        result["dictionary"]["topics"].pop()
    elif mutation == "anchor":
        result["dictionary"]["topics"][0]["anchor"] = "BOGUS"
    elif mutation == "coverage":
        result["proofs"][0]["topic_coverage"].pop()
    else:
        result["dictionary"]["sources"][0]["license"] = "altered"
    with pytest.raises(ValueError):
        verify_bundle(result)


def test_combined_bundles_cannot_be_downgraded_to_old_single_topic_versions():
    result = Generator().build(Request("reasoning", subject="space, ocean", topic_mode="combined"))
    result.update(version=4, generator="brainbloom-reasoning-v4")
    with pytest.raises(ValueError, match="version 5"):
        verify_bundle(result)


def test_all_activity_labels_have_real_supported_engine_routes():
    for activity in ACTIVITIES.values():
        assert activity.label and activity.description
        for kind in activity.types:
            Request(activity.family, kind, category=(
                "logic" if activity.uses_topics else
                TOPICS[activity.family].categories[0]
            ), variation=activity.variation)


def test_real_wordnet_preserves_both_meanings_and_all_licenses():
    if not DEFAULT_WORDNET.exists():
        pytest.skip("Optional pinned dictionary is not installed")
    dictionary = Dictionary(DEFAULT_WORDNET)
    report = lookup_many(dictionary, "bank, crane")
    bank, crane = report["groups"]
    meanings = {
        "bank": next(c["id"] for c in bank["choices"]
                     if "financial institution" in c["definition"]),
        "crane": next(c["id"] for c in crane["choices"] if "wading" in c["definition"]),
    }
    plan = prepare(Brief(subject="bank, crane", meanings=meanings), dictionary)
    assert plan["ready"]
    engine = Generator()
    engine.dictionary = dictionary
    result = engine.build(Request(**plan["request"]))
    assert result["request"]["meanings"] == meanings
    assert "WordNet 3.0 Copyright" in result["dictionary"]["source"]["license"]
    assert verify_bundle(result) == 1


def test_cli_combines_all_supplied_topics_by_default(tmp_path):
    path = tmp_path / "combined.json"
    assert main(["generate", "--subject", "space, ocean", "--out", str(path)]) == 0
    result = json.loads(path.read_text())
    assert result["version"] == 5 and len(result["request"]["meanings"]) == 2
    assert main(["check", str(path)]) == 0


def test_http_prepare_then_generate_preserves_every_selected_topic():
    server = LocalHTTPServer(("127.0.0.1", 0), handler_for(Generator()))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(path, data):
        connection = HTTPConnection(*server.server_address, timeout=20)
        try:
            connection.request("POST", path, json.dumps(data), {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
    try:
        status, plan = post("/api/prepare", {"subject": "space, ocean", "activity": "planning"})
        assert status == 200 and plan["ready"]
        status, bundle = post("/api/generate", plan["request"])
        assert status == 200 and verify_bundle(bundle) == 1
        assert len(bundle["proofs"][0]["topic_coverage"]) == 2
        assert post("/api/prepare", {"meanings": []})[0] == 400
        assert post("/api/prepare", {"count": True})[0] == 400
        assert post("/api/prepare", {"unknown": "field"})[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
