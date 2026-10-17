"""Player-visible difficulty survives answer choices and true/false formatting."""

import copy
from itertools import combinations, permutations

import pytest

from spie.questions.brainbloom.catalog import DIFFICULTIES, Request
from spie.questions.brainbloom.service import Generator, verify_bundle


def _fits(clue, row):
    a, b, k = row[clue["a"]], row[clue["b"]], clue["k"]
    if clue["kind"] == "before":
        return a < b
    if clue["kind"] == "adjacent":
        return abs(a - b) == 1
    if clue["kind"] == "distance":
        return abs(a - b) == k
    if clue["kind"] == "not-at":
        return a != k
    return min(b, row[k]) < a < max(b, row[k])


def _independent_support(item, proof):
    model = proof["model"]
    names, position = model["names"], model["position"]
    scenarios = []
    for row in permutations(range(len(names))):
        occupant = names[row.index(position)]
        if item["type"] == "multiple-choice" and occupant not in item["choices"]:
            continue
        satisfied = sum(1 << i for i, clue in enumerate(model["clues"]) if _fits(clue, row))
        target = (occupant == proof["claim"] if item["type"] == "true-false"
                  else occupant == item["correctAnswer"])
        if item["type"] == "true-false" and not proof["claim_holds"]:
            target = not target
        scenarios.append((satisfied, target))
    for size in range(len(model["clues"]) + 1):
        for subset in combinations(range(len(model["clues"])), size):
            mask = sum(1 << index for index in subset)
            survivors = [target for satisfied, target in scenarios if satisfied & mask == mask]
            if survivors and all(survivors):
                return size
    pytest.fail("Displayed answer is not entailed")


@pytest.mark.parametrize("seed", [7, 23, 91])
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
@pytest.mark.parametrize("kind", ["multiple-choice", "true-false", "type-answer", "riddle"])
def test_difficulty_is_measured_on_the_rendered_task(seed, difficulty, kind):
    bundle = Generator().build(Request("reasoning", kind, difficulty, seed=seed,
                                       subject="space", variation="deduction"))
    item, proof = bundle["items"][0], bundle["proofs"][0]
    task = proof["player_task"]
    actual = _independent_support(item, proof)
    assert actual == task["minimum_supporting_clues"]
    assert actual >= DIFFICULTIES[difficulty] + 1
    assert task["required_supporting_clues"] == DIFFICULTIES[difficulty] + 1
    assert proof["quality"]["displayed_supporting_clues"] == actual
    assert f"at least {actual} clues" in item["correctExplanation"]
    assert f"at least {actual} clues" in proof["steps"][-1]
    assert "displayed" in proof["steps"][-1]
    assert "underlying open question" in proof["steps"][-2]
    if kind == "multiple-choice":
        assert set(task["answer_domain"]) == set(item["choices"])
    elif kind == "true-false":
        assert task["claim"] in item["question"]
        assert task["claim_holds"] == proof["claim_holds"]
        assert "Which card must occupy" not in item["question"]
    assert verify_bundle(bundle) == 1


def test_saved_task_certificate_is_verified_instead_of_trusted():
    bundle = Generator().build(Request("reasoning", subject="ocean", variation="deduction"))
    altered = copy.deepcopy(bundle)
    altered["proofs"][0]["player_task"]["minimum_supporting_clues"] = 999
    with pytest.raises(ValueError, match="does not match"):
        verify_bundle(altered)


def test_legacy_deduction_replay_keeps_its_original_proof_shape():
    bundle = Generator().build(Request("reasoning", "true-false", "hard", seed=7,
                                       subject="space", variation="deduction", engine_revision=8))
    assert "player_task" not in bundle["proofs"][0]
    assert "displayed_supporting_clues" not in bundle["proofs"][0]["quality"]
    assert verify_bundle(bundle) == 1
