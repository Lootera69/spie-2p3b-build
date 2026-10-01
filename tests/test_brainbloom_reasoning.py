"""Deeper reasoning has explicit mathematical gates, not a claimed intelligence score."""

import copy
import json
import socket
import subprocess
from dataclasses import asdict
from fractions import Fraction
from itertools import combinations

import pytest

from spie.forge.corpus import compact
from spie.questions import prover
from spie.questions.brainbloom import Request, deduction, probabilistic
from spie.questions.brainbloom.__main__ import main
from spie.questions.brainbloom.catalog import DIFFICULTIES
from spie.questions.brainbloom.contract import issues
from spie.questions.brainbloom.reasoning import STYLES
from spie.questions.brainbloom.service import Generator, verify_bundle


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
@pytest.mark.parametrize("kind", ["multiple-choice", "true-false", "type-answer", "riddle"])
def test_reasoning_styles_across_difficulties_and_formats(style, difficulty, kind):
    request = Request("reasoning", kind, difficulty, subject="ocean", variation=style, seed=7)
    result = Generator().build(request)
    item, proof = result["items"][0], result["proofs"][0]
    assert result["version"] == 4
    assert issues(item) == []
    assert proof["agree"] and proof["reasoning_style"] == style
    assert proof["search"]["selected_score"] == max(proof["search"]["qualified_scores"])
    assert proof["search"]["qualified"] + proof["search"]["rejected"] == 32
    assert verify_bundle(json.loads(compact(result))) == 1
    level = DIFFICULTIES[difficulty]
    if style == "deduction":
        assert level + 1 <= proof["minimum_supporting_clues"] <= level + 2
        assert all(count > 1 for count in proof["clue_deletion_model_counts"])
    elif style == "bayesian":
        assert sum(Fraction(p) for p in proof["posterior"]) == 1
        assert proof["quality"]["evidence_steps"] == level
    else:
        assert len(proof["model"]["names"]) == level + 3
        assert proof["quality"]["lookahead"] == "until exact identification"


def test_deduction_support_is_really_minimal_and_removing_clues_introduces_ambiguity():
    bundle = Generator().build(Request("reasoning", variation="deduction", subject="animals"))
    proof = bundle["proofs"][0]
    model = proof["model"]
    clues = [deduction.Clue(**row) for row in model["clues"]]
    rows = deduction.worlds(len(model["names"]))
    minimum = proof["minimum_supporting_clues"]
    for size in range(minimum):
        for subset in combinations(clues, size):
            candidates = deduction.survivors(rows, subset)
            assert any(row[model["answer_index"]] != model["position"] for row in candidates)
    assert len(deduction.survivors(rows, clues)) == 1


def test_z3_disagreement_blocks_deduction(monkeypatch):
    monkeypatch.setattr(prover, "decide", lambda _: (False, None))
    with pytest.raises(RuntimeError, match="disagreement"):
        Generator().build(Request("reasoning", variation="deduction", subject="space"))


def test_known_chain_and_corrupted_clue_are_checked():
    model = {
        "names": ["A", "B", "C", "D"], "solution": [0, 1, 2, 3],
        "clues": [asdict(deduction.Clue("before", i, i + 1)) for i in range(3)],
        "answer_index": 0, "position": 0, "minimum_support": 3,
    }
    assert deduction.check(model)["minimum_supporting_clues"] == 3
    model["clues"].append(asdict(deduction.Clue("before", 3, 0)))
    with pytest.raises(RuntimeError, match="not uniquely solved"):
        deduction.check(model)


def test_bayes_checker_handles_base_rates_and_rejects_fabricated_probability():
    model = {
        "names": ["A", "B", "C", "D"], "priors": [9, 1, 1, 1],
        "positive_rates_out_of_ten": [[2], [9], [1], [1]], "observed_positive": [True],
        "posterior": ["18/29", "9/29", "1/29", "1/29"], "answer_index": 0,
    }
    assert probabilistic.bayes_check(model)["frequency_counts"] == [18, 9, 1, 1]
    model["posterior"][0] = "1"
    with pytest.raises(RuntimeError, match="disagreement"):
        probabilistic.bayes_check(model)


def test_bayes_quality_does_not_mislabel_a_likelihood_tie_as_an_overturned_winner():
    class FixedRandom:
        values = iter([2, 3, 1, 1, 8, 8, 8, 8, 1, 1, 1, 1])

        def randint(self, _low, _high):
            return next(self.values)

    model = probabilistic.bayes_propose(["A", "B", "C", "D"], 2, FixedRandom())
    assert model["answer_index"] == 1
    assert not model["quality"]["base_rates_change_likelihood_only_winner"]


def test_planner_looks_beyond_first_partition_and_accounts_for_priors():
    questions = [[0, 1], [0], [1], [2]]
    costs, tree = probabilistic.optimal_costs([1, 1, 1, 1], questions)
    assert costs == [Fraction(2), Fraction(9, 4), Fraction(9, 4), Fraction(9, 4)]
    assert tree["question"] == 0
    weighted, tree = probabilistic.optimal_costs([9, 1, 1, 1], questions)
    assert min(weighted) == Fraction(17, 12)
    assert tree["question"] == 1  # A balanced card count is no longer optimal.


def test_planner_rejects_indistinguishable_states():
    with pytest.raises(ValueError, match="cannot distinguish"):
        probabilistic.optimal_costs([1, 1, 1, 1], [[0], [0, 1]])


def test_plan_is_replayed_through_both_branches_not_just_trusted():
    bundle = Generator().build(Request("reasoning", variation="planning", subject="space"))
    model = copy.deepcopy(bundle["proofs"][0]["model"])
    node = model["tree"]
    while "question" in node:
        node = node["yes"]
    node["answer"] = 999
    with pytest.raises(RuntimeError, match="misidentifies"):
        probabilistic.planning_check(model)


@pytest.mark.parametrize("style", STYLES)
def test_more_search_never_reduces_the_structural_objective(style):
    engine = Generator()
    quick = engine.build(Request("reasoning", subject="space", variation=style,
                                 search_effort="quick"))["proofs"][0]["search"]
    thorough = engine.build(Request("reasoning", subject="space", variation=style,
                                    search_effort="thorough"))["proofs"][0]["search"]
    assert thorough["selected_score"] >= quick["selected_score"]
    assert thorough["budget"] == 80 and quick["budget"] == 12


def test_auto_batch_rotates_skills_and_has_distinct_structures():
    result = Generator().build(Request("reasoning", subject="space", count=3, seed=6))
    assert [p["reasoning_style"] for p in result["proofs"]] == list(STYLES)
    assert len({p["structural_key"] for p in result["proofs"]}) == 3
    assert verify_bundle(result) == 3


@pytest.mark.parametrize("key", ["model", "quality", "search", "structural_key"])
def test_replay_detects_tampered_reasoning_and_search_scores(key):
    result = Generator().build(Request("reasoning", subject="space"))
    result["proofs"][0][key] = "altered"
    with pytest.raises(ValueError, match="does not match"):
        verify_bundle(result)


def test_reasoning_uses_no_network_or_model_process(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected network or model process")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    for style in STYLES:
        result = Generator().build(Request("reasoning", subject="plants", variation=style))
        assert verify_bundle(result) == 1


@pytest.mark.parametrize("kwargs", [
    {"variation": "anagram"}, {"search_effort": "unlimited"}, {"search_effort": []},
    {"topic": "dictionary", "search_effort": "thorough"}, {"qtype": "crossword"},
])
def test_invalid_reasoning_options_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Request(**{"topic": "reasoning", **kwargs})


def test_cli_benchmark_exports_measured_results_and_never_overwrites(tmp_path):
    path = tmp_path / "benchmark.json"
    args = ["benchmark", "--seeds", "1", "--out", str(path)]
    assert main(args) == 0
    report = json.loads(path.read_text())
    assert report["summary"]["requested"] == report["summary"]["verified"] == 9
    assert report["summary"]["rejected"] == 0
    assert "no human ratings" in report["scope"]
    before = path.read_bytes()
    assert main(args) == 2 and path.read_bytes() == before


def test_cli_can_select_reasoning_style_and_search_effort(tmp_path):
    path = tmp_path / "reasoning.json"
    assert main(["generate", "--topic", "reasoning", "--subject", "ocean", "--variation",
                 "planning", "--search-effort", "thorough", "--out", str(path)]) == 0
    assert main(["check", str(path)]) == 0
