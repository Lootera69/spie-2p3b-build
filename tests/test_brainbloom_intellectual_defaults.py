"""Default challenge requirements, answer leakage and revision-preserving replay."""

from dataclasses import replace
from fractions import Fraction
from itertools import combinations, permutations

import pytest

from spie.forge.contract import normalized
from spie.forge.corpus import digest
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.catalog import CATEGORIES, Request
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("subject", ["", "space, ocean, animals"])
def test_choose_for_me_requires_combining_clues_or_complete_strategy(category, subject):
    engine = Generator()
    plan = prepare(Brief(category=category, subject=subject), engine.dictionary)
    assert plan["ready"], plan["message"]
    assert plan["selected_activity"] in {"deduction", "planning"}
    assert plan["request"]["difficulty"] == "hard"
    bundle = engine.build(Request(**plan["request"]))
    proof = bundle["proofs"][0]
    assert proof["agree"] is True
    assert len(proof["model"]["names"]) == 6
    if proof["reasoning_style"] == "deduction":
        assert proof["minimum_supporting_clues"] >= 4
        assert proof["model_count"] == 1
        assert min(proof["clue_deletion_model_counts"]) > 1
        assert proof["quality"]["clue_kinds"] >= 2
    else:
        costs = [Fraction(cost) for cost in proof["expected_questions"]]
        assert costs.count(min(costs)) == 1
        assert max(proof["rollout_depths"]) >= 3
        assert min(costs) > 1
    assert verify_bundle(bundle) == 1


def test_default_deduction_answer_cannot_be_derived_from_any_three_clues():
    engine = Generator()
    plan = prepare(Brief(subject="space, ocean"), engine.dictionary)
    bundle = engine.build(Request(**plan["request"]))
    model = bundle["proofs"][0]["model"]

    # Separate direct evaluation of each stated clue, without invoking the
    # generator's mask, minimum-support function, or SMT encoder.
    def fits(clue, row):
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

    rows = list(permutations(range(6)))
    solutions = [row for row in rows if all(fits(c, row) for c in model["clues"])]
    assert solutions == [tuple(model["solution"])]
    answer, position = model["answer_index"], model["position"]
    assert bundle["items"][0]["correctAnswer"] == model["names"][answer]
    for subset in combinations(model["clues"], 3):
        assert any(row[answer] != position and all(fits(c, row) for c in subset)
                   for row in rows)


def test_automatic_choice_does_not_replace_a_capacity_failure_with_letter_sorting():
    class SmallDictionary(Dictionary):
        def _entries(self, sense):
            entries, source = super()._entries(sense)
            entries = entries[:4]
            return entries, {**source, "sha256": digest(entries)}

    dictionary = SmallDictionary()
    report = prepare(Brief(subject="ocean"), dictionary)
    assert not report["ready"] and report["request"] is None
    assert report["selected_activity"] == ""
    assert [option["available"] for option in report["difficulty_options"]] == [True, False, False]
    explicit = prepare(Brief(subject="ocean", activity="word-order"), dictionary)
    assert explicit["ready"]


@pytest.mark.parametrize("qtype", ["multiple-choice", "type-answer"])
def test_topic_name_cannot_give_away_answer_and_revision_two_replay_is_preserved(qtype):
    request = Request("dictionary", qtype, "medium", subject="plate tectonics", seed=31,
                      topic_mode="combined",
                      meanings={"plate tectonics": "coverage-v2:plate-tectonics"})
    engine = Generator()
    old = engine.build(replace(request, engine_revision=2))
    current = engine.build(request)
    old_item, item = old["items"][0], current["items"][0]
    assert old_item["correctAnswer"] == item["correctAnswer"] == "PLATE"
    assert " plate " in f" {normalized(old_item['title'])} "
    assert " plate " not in f" {normalized(item['title'])} "
    assert {key: value for key, value in old_item.items() if key != "title"} == {
        key: value for key, value in item.items() if key != "title"
    }
    assert verify_bundle(old) == verify_bundle(current) == 1


def test_changing_revision_of_a_title_repaired_bundle_cannot_bypass_replay():
    request = Request("dictionary", "type-answer", "medium", subject="plate tectonics", seed=31,
                      topic_mode="combined",
                      meanings={"plate tectonics": "coverage-v2:plate-tectonics"})
    bundle = Generator().build(request)
    bundle["request"]["engine_revision"] = 2
    with pytest.raises(ValueError):
        verify_bundle(bundle)
