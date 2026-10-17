"""Player-visible shortcut checks, independent clue evaluation, and old replay."""

import copy
import json
import re
from itertools import combinations
from pathlib import Path

import pytest

from spie.forge.contract import issues as studio_issues
from spie.forge.corpus import digest
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.contract import issues
from spie.questions.brainbloom.feedback import feedback_for
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.logic_grid import EXAMPLE
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.workshop import generate

LEVELS = ("easy", "medium", "hard")
SEEDS = (7, 23, 91)


def number_clues(question):
    """Read the displayed English rather than trusting proof support fields."""
    low, high = map(int, re.search(r"from (\d+) to (\d+), inclusive", question).groups())
    checks = []
    for clause in question.split(". ")[1:]:
        if match := re.match(r"Dividing me by (\d+) leaves remainder (\d+)", clause):
            modulus, remainder = map(int, match.groups())
            checks.append(lambda n, m=modulus, r=remainder: n % m == r)
        elif match := re.match(r"My decimal digits add to (\d+)", clause):
            total = int(match[1])
            checks.append(lambda n, total=total: sum(map(int, str(n))) == total)
        elif clause.startswith("I am odd"):
            checks.append(lambda n: n % 2 == 1)
        elif clause.startswith("I am even"):
            checks.append(lambda n: n % 2 == 0)
    return low, high, checks


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("seed", SEEDS)
def test_ordering_choices_are_all_possible_positions(level, seed):
    bundle = Generator().build(Request("ordering", difficulty=level, seed=seed))
    item, proof = bundle["items"][0], bundle["proofs"][0]
    count = len(proof["possible_orders"][0])
    assert len(set(item["choices"])) == 4
    assert all(1 <= int(choice) <= count for choice in item["choices"])
    assert verify_bundle(bundle) == 1


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("kind", ("multiple-choice", "type-answer", "riddle", "true-false"))
def test_number_mysteries_need_each_displayed_clue(level, seed, kind):
    bundle = Generator().build(Request("number-riddles", kind, level, seed=seed,
                                       category="riddles"))
    item, proof = bundle["items"][0], bundle["proofs"][0]
    low, high, checks = number_clues(item["question"])
    expected = 3 if level == "hard" else 2
    assert len(checks) == expected
    domain = list(range(low, high + 1))
    answer = proof["survivors"][0]
    assert [n for n in domain if all(check(n) for check in checks)] == [answer]
    for subset in combinations(checks, expected - 1):
        assert sum(all(check(n) for check in subset) for n in domain) > 1
    if kind == "multiple-choice":
        choices = list(map(int, item["choices"]))
        assert len(set(choices)) == 4
        assert all(low <= n <= high for n in choices)
        for subset in combinations(checks, expected - 1):
            assert sum(all(check(n) for check in subset) for n in choices) > 1
        assert [n for n in choices if all(check(n) for check in checks)] == [answer]
    assert verify_bundle(bundle) == 1


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("variation", ("anagram", "missing-letters"))
@pytest.mark.parametrize("kind", ("multiple-choice", "type-answer", "riddle", "true-false"))
def test_letter_puzzles_cannot_be_solved_by_length_alone(level, seed, variation, kind):
    bundle = Generator().build(Request("dictionary", kind, level, category="puzzles",
                                       variation=variation, subject="space, ocean",
                                       topic_mode="combined", seed=seed))
    item, proof = bundle["items"][0], bundle["proofs"][0]
    answer = proof["survivors"][0]
    assert sum(len(word) == len(answer) for word in proof["word_bank"]) >= 3
    if kind == "multiple-choice":
        assert 3 <= len(item["choices"]) <= 4
        assert {len(word) for word in item["choices"]} == {len(answer)}
    if kind == "true-false":
        assert len(proof["claim"]) == len(answer)
    assert issues(item) == []
    assert verify_bundle(bundle) == 1


def test_insufficient_letter_vocabulary_fails_without_a_length_only_fallback():
    context = Dictionary().resolve("space", "", "logic")
    context["entries"] = [
        {"word": word, "definition": "Fixture meaning", "sense": "fixture", "path": ["fixture"]}
        for word in ("SUN", "MOON", "COMET", "GALAXY")
    ]
    with pytest.raises(ValueError, match="three same-length words"):
        generate(Request("dictionary", subject="space", variation="anagram"), context=context)


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("seed", SEEDS)
def test_reversal_choices_have_the_stated_length(level, seed):
    bundle = Generator().build(Request("word-riddles", difficulty=level, seed=seed,
                                       category="riddles"))
    item = bundle["items"][0]
    count = int(re.search(r"resulting (\d+)-letter", item["question"])[1])
    assert 3 <= len(item["choices"]) <= 4
    assert {len(word) for word in item["choices"]} == {count}
    assert verify_bundle(bundle) == 1


def test_grid_has_three_real_options_and_keeps_studio_contract_separate():
    bundle = Generator().build(Request("logic-grid", grid=EXAMPLE, seed=7))
    item, proof = bundle["items"][0], bundle["proofs"][0]
    assert len(item["choices"]) == 3 and "None of these" not in item["choices"]
    assert issues(item) == []
    assert studio_issues(item) == ["choice-count"]
    for choice in item["choices"]:
        feedback = feedback_for(item, proof, choice)
        assert feedback["supported"]
        assert feedback["correct"] is (choice == item["correctAnswer"])
    broken = copy.deepcopy(item)
    broken["choices"][0] = broken["choices"][1]
    assert "duplicate-choice" in issues(broken)
    missing = {**item, "correctAnswer": "unlisted"}
    assert "answer-choice" in issues(missing)
    assert verify_bundle(bundle) == 1


LEGACY = json.loads((Path(__file__).parent / "fixtures/creator_choices_revision8.json").read_text())


@pytest.mark.parametrize("fixture", LEGACY, ids=lambda row: row["activity"])
def test_revision_eight_replays_the_audited_items_and_proofs_exactly(fixture):
    bundle = Generator().build(Request(**fixture["request"]))
    assert digest(bundle["items"][0]) == fixture["item_sha256"]
    assert digest(bundle["proofs"][0]) == fixture["proof_sha256"]
    assert verify_bundle(bundle) == 1
