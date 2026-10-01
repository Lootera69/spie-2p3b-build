"""All product formats, exact checks, native contracts, and v1 replay compatibility."""

import copy
import json
import socket
import subprocess

import pytest

from spie.forge.corpus import compact, digest
from spie.questions import prover
from spie.questions.brainbloom import CATEGORIES, DIFFICULTIES, TOPICS, TYPES, Request, generate
from spie.questions.brainbloom.__main__ import main
from spie.questions.brainbloom.contract import issues
from spie.questions.brainbloom.crossword import validate_grid
from spie.questions.brainbloom.service import Generator, verify_bundle

COMBINATIONS = [
    (topic, category, kind, difficulty)
    for topic, spec in TOPICS.items()
    for category in spec.categories
    for kind in spec.types
    for difficulty in DIFFICULTIES
]


@pytest.mark.parametrize("topic,category,kind,difficulty", COMBINATIONS)
def test_every_supported_combination_generates_and_replays(topic, category, kind, difficulty):
    request = Request(topic, kind, difficulty, seed=7, category=category)
    result = Generator().build(request)
    item, proof = result["items"][0], result["proofs"][0]
    assert issues(item) == []
    assert item["type"] == kind and item["category"] == category
    assert result["generator"] == (
        "brainbloom-activities-v8" if topic == "activities"
        else "brainbloom-autopilot-v7" if topic == "autopilot"
        else "brainbloom-logic-grid-v6" if topic == "logic-grid"
        else "brainbloom-reasoning-v4" if topic == "reasoning"
        else "brainbloom-dictionary-v3" if topic == "dictionary" else "brainbloom-symbolic-v2"
    )
    assert not result["provenance"]["learned_model_used"]
    assert not result["intendedImport"]["published"]
    assert proof["item_sha256"] == digest(item)
    assert proof["scope"] and proof["steps"]
    assert verify_bundle(json.loads(compact(result))) == 1
    if kind in ("type-answer", "riddle"):
        assert item["correctAnswer"] in item["acceptedAnswers"]
        assert len(set(item["acceptedAnswers"])) >= 3
        assert item["choices"] == []
    if kind == "wonder":
        assert item["xpReward"] == 0 and item["sharePrompt"]
        assert item["lessonContent"] == item["correctExplanation"]
    if kind == "crossword":
        assert validate_grid(item["crosswordData"])["entries"] == 2 * DIFFICULTIES[difficulty] + 1


def test_all_requested_types_and_categories_have_a_generator():
    assert {kind for _, _, kind, _ in COMBINATIONS} == set(TYPES)
    assert {category for _, category, _, _ in COMBINATIONS} == set(CATEGORIES)
    assert len(COMBINATIONS) == 483


@pytest.mark.parametrize(
    "topic,category,kind",
    [
        ("arithmetic", "puzzles", "type-answer"),
        ("ordering", "logic", "multiple-choice"),
        ("number-riddles", "riddles", "riddle"),
        ("motion", "science", "true-false"),
        ("crossword", "science", "crossword"),
        ("growth", "wonders", "wonder"),
    ],
)
def test_batches_are_deterministic_and_not_identical_copies(topic, category, kind):
    request = Request(topic, kind, count=3, seed=71, category=category)
    a, b = generate(request), generate(request)
    assert compact(a) == compact(b)
    assert len({digest(item) for item in a["items"]}) == 3
    assert len({digest(item.get("crosswordData", item["question"])) for item in a["items"]}) == 3
    assert verify_bundle(a) == 3


@pytest.mark.parametrize("mutation", ["letter", "clue", "number", "direction", "unclued"])
def test_crossword_checker_rejects_broken_puzzles(mutation):
    bundle = generate(Request("crossword", "crossword", "hard", category="science"))
    data = copy.deepcopy(bundle["items"][0]["crosswordData"])
    clue = data["clues"][0]
    if mutation == "letter":
        data["grid"][clue["startRow"]][clue["startCol"]] = "Z" if clue["answer"][0] != "Z" else "Q"
    elif mutation == "clue":
        clue["answer"] = "WRONG"
    elif mutation == "number":
        clue["number"] = 100
    elif mutation == "direction":
        clue["direction"] = "up"
    else:
        data["clues"].pop()
    with pytest.raises(ValueError):
        validate_grid(data)


@pytest.mark.parametrize(
    "topic", ["arithmetic", "sequences", "number-riddles", "ordering", "motion"]
)
def test_bad_solver_verdict_blocks_math_families(monkeypatch, topic):
    spec = TOPICS[topic]
    monkeypatch.setattr(prover, "decide", lambda _: (False, None))
    with pytest.raises(RuntimeError):
        generate(Request(topic, category=spec.categories[0]))


def test_generation_uses_no_network_or_external_model(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Generation attempted a network or subprocess call")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    for kind in TYPES:
        topic, spec = next((t, s) for t, s in TOPICS.items() if kind in s.types)
        assert Generator().build(Request(topic, kind, category=spec.categories[0]))["items"]


@pytest.mark.parametrize("kind", ["crossword", "wonder"])
def test_quiz_only_studio_verifier_is_not_misrepresented(monkeypatch, tmp_path, kind):
    from spie.questions.brainbloom import service

    verifier = tmp_path / "verify.ts"
    verifier.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        service, "check_platform", lambda *args: pytest.fail("Unsupported quiz gate")
    )
    topic = "crossword" if kind == "crossword" else "growth"
    category = "puzzles" if kind == "crossword" else "wonders"
    result = Generator(verifier=verifier).build(Request(topic, kind, category=category))
    assert result["checks"]["platform_verifier"]["status"] == "not-supported-for-type"


@pytest.mark.parametrize("kind", TYPES)
def test_cli_auto_selects_a_valid_default_for_each_type(tmp_path, kind):
    path = tmp_path / f"{kind}.json"
    assert main(["generate", "--type", kind, "--out", str(path)]) == 0
    assert main(["check", str(path)]) == 0


def test_wonder_label_maps_to_existing_platform_wire_name():
    assert Request("growth", "wonder", category="wonder").category == "wonders"


def test_impossible_type_category_combinations_are_rejected():
    with pytest.raises(ValueError, match="does not support"):
        Request("growth", "multiple-choice", category="science")
