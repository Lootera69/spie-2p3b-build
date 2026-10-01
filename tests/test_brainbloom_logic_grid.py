"""Authored constraints, multi-attribute completion, independent proofs and replay."""

import copy
import json
import socket
import subprocess

import pytest

from spie.questions import prover
from spie.questions.brainbloom import Request
from spie.questions.brainbloom.__main__ import main
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.contract import issues
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.logic_grid import EXAMPLE, analyze, check, holds, parse, survivors
from spie.questions.brainbloom.service import Generator, verify_bundle

ORDER = {"groups": "Animal: Tiger, Lion, Owl", "rules":
         "Tiger must appear before Lion.\nOwl cannot be next to Tiger.",
         "complete": False, "target": "Owl", "answer_group": "Position"}


def test_user_example_has_a_proven_unique_order():
    result = analyze(ORDER)
    assert result["status"] == "unique" and result["solution_count"] == 1
    model = parse(ORDER)
    assert check(model, model["rules"]) == [(1, 2, 3)]


@pytest.mark.parametrize("kind", ["multiple-choice", "true-false", "type-answer", "riddle"])
def test_ordering_question_formats_are_valid_and_replay(kind):
    result = Generator().build(Request("logic-grid", kind, grid=ORDER))
    assert result["version"] == 6 and verify_bundle(result) == 1
    item, proof = result["items"][0], result["proofs"][0]
    assert issues(item) == [] and proof["added_rules"] == []
    assert proof["solution_positions"] == [1, 2, 3]
    if kind != "true-false":
        assert item["correctAnswer"] == "3"
    if kind == "multiple-choice":
        assert set(item["choices"]) == {"1", "2", "3", "None of these"}


def test_attribute_groups_are_jointly_solved_not_independent_word_lists():
    analysis = analyze(EXAMPLE)
    assert analysis["solution_count"] == 2
    assert len(analysis["witnesses"]) == 2
    for seed in range(5):
        result = Generator().build(Request("logic-grid", grid=EXAMPLE, seed=seed))
        proof = result["proofs"][0]
        model, solution = proof["model"], tuple(proof["solution_positions"])
        assert all(holds(rule, solution) for rule in model["rules"])
        assert proof["authored_rules"] == parse(EXAMPLE)["rules"]
        assert proof["added_rules"] and proof["solution_count"] == 1
        assert len(survivors(model, [*model["rules"], *proof["added_rules"]])) == 1
        for clue in proof["added_rules"]:
            rest = [r for r in proof["added_rules"] if r != clue]
            assert len(survivors(model, [*model["rules"], *rest])) > 1
        assert verify_bundle(json.loads(json.dumps(result))) == 1


def test_strict_mode_refuses_an_ambiguous_complete_grid_even_if_one_answer_is_known():
    spec = {**EXAMPLE, "complete": False}
    plan = prepare(Brief(activity="logic-grid", grid=spec), Dictionary())
    assert not plan["ready"] and "2 arrangements" in plan["message"]
    with pytest.raises(ValueError, match="2 arrangements"):
        Generator().build(Request("logic-grid", grid=spec))


def test_conflict_report_is_an_irreducible_set_of_user_rules():
    spec = {**ORDER, "rules": "Tiger is before Lion.\nLion is before Tiger.\nOwl is in position 3."}
    analysis = analyze(spec)
    assert analysis["status"] == "contradictory"
    assert [r["number"] for r in analysis["conflicts"]] == [1, 2]
    for complete in (True, False):
        with pytest.raises(ValueError, match="rules conflict"):
            Generator().build(Request("logic-grid", grid={**spec, "complete": complete}))


@pytest.mark.parametrize("rule,expected", [
    ("Tiger is before Lion", True), ("Tiger is after Lion", False),
    ("Tiger is immediately before Lion", True), ("Tiger is next to Owl", False),
    ("Tiger cannot be next to Owl", True), ("Tiger is paired with Red", True),
    ("Tiger is not paired with Red", False), ("Owl is in position 3", True),
    ("Owl is not in position 3", False), ("Tiger is 2 positions away from Owl", True),
    ("Lion is between Tiger and Owl", True),
])
def test_each_rule_has_exact_bounded_semantics(rule, expected):
    model = parse({"groups": "Animal: Tiger, Lion, Owl\nColour: Red, Blue, Green", "rules": rule})
    assert holds(model["rules"][0], (1, 2, 3, 1, 2, 3)) is expected
    # The independent SMT path must agree about consistency and uniqueness too.
    assert check(model, model["rules"])


@pytest.mark.parametrize("spec", [
    {}, {"groups": "Animal: Tiger, Lion"},
    {"groups": "Animal: Tiger, Lion, Owl\nColour: Red, Blue, Green, Pink"},
    {"groups": "Animal: Tiger, Lion, Owl\nColour: Red, Blue, tiger"},
    {"groups": "Position: Tiger, Lion, Owl"},
    {**ORDER, "rules": "Tiger is in position 4"},
    {**ORDER, "rules": "Elephant is before Tiger"},
    {**ORDER, "rules": "Tiger is before Lion unless Owl is first"},
    {**ORDER, "target": "Unknown"}, {**ORDER, "answer_group": "Unknown"},
    {**ORDER, "answer_group": "Animal"}, {**ORDER, "complete": "yes"},
    {**ORDER, "target": "", "answer_group": "Animal"},
    {**ORDER, "rules": "Tiger is before Lion.\n" * 21},
    {**ORDER, "run": "code"},
])
def test_malformed_or_unrecognised_rules_never_partially_generate(spec):
    with pytest.raises(ValueError):
        Generator().build(Request("logic-grid", grid=spec))


def test_completion_from_no_rules_covers_every_value_in_four_by_three_grid():
    spec = {"groups": "Person: Ada, Bo, Cy, Dee\nColour: Red, Blue, Green, Pink\n"
                      "Drink: Tea, Coffee, Milk, Juice", "rules": "", "complete": True}
    result = Generator().build(Request("logic-grid", grid=spec))
    proof = result["proofs"][0]
    assert proof["initial_solutions"] == 13824 and proof["solution_count"] == 1
    assert len(proof["solution_table"]) == 4
    for group in proof["model"]["groups"]:
        assert {row[group["name"]] for row in proof["solution_table"]} == set(group["values"])
    assert verify_bundle(result) == 1


def test_solver_disagreement_blocks_preview_and_generation(monkeypatch):
    monkeypatch.setattr(prover, "decide", lambda _: (False, None))
    with pytest.raises(RuntimeError, match="uniqueness disagreement"):
        analyze(ORDER)
    with pytest.raises(RuntimeError):
        Generator().build(Request("logic-grid", grid=ORDER))


def test_preview_gives_real_capacity_and_does_not_ignore_other_topics():
    plan = prepare(Brief(activity="logic-grid", grid=ORDER), Dictionary())
    assert plan["ready"] and plan["max_count"] == 1
    assert not plan["difficulty_relevant"] and not plan["search_relevant"]
    assert plan["request"]["grid"] == ORDER
    assert not prepare(Brief(activity="logic-grid", grid=ORDER, count=2), Dictionary())["ready"]
    assert not prepare(
        Brief(activity="logic-grid", grid=ORDER, subject="space"), Dictionary()
    )["ready"]


def test_different_clue_wording_cannot_fill_a_batch_with_the_same_grid_query():
    assert analyze(EXAMPLE)["max_count"] == 2
    bundle = Generator().build(Request("logic-grid", grid=EXAMPLE, count=2))
    assert len({p["structural_key"] for p in bundle["proofs"]}) == 2
    assert verify_bundle(bundle) == 2
    with pytest.raises(ValueError, match="at most 2"):
        Generator().build(Request("logic-grid", grid=EXAMPLE, count=3))


@pytest.mark.parametrize("field", ["grid", "added_rules", "solution_table", "query"])
def test_saved_grid_rules_and_solutions_cannot_be_tampered_with(field):
    result = Generator().build(Request("logic-grid", grid=EXAMPLE))
    if field == "grid":
        result["request"]["grid"]["rules"] = "Tiger is after Lion."
    else:
        result["proofs"][0][field] = []
    with pytest.raises((ValueError, RuntimeError)):
        verify_bundle(result)


def test_grid_replay_requires_its_own_generator_version():
    result = Generator().build(Request("logic-grid", grid=ORDER))
    result.update(version=2, generator="brainbloom-symbolic-v2")
    with pytest.raises(ValueError, match="version 6"):
        verify_bundle(result)


def test_custom_grid_instructions_route_to_the_builder():
    plan = prepare(Brief(activity="custom", instructions="Build a logic grid.", grid=ORDER),
                   Dictionary())
    assert plan["ready"] and plan["request"]["topic"] == "logic-grid"
    result = Generator().build(Request(**plan["request"]))
    assert verify_bundle(result) == 1


def test_generation_is_offline_and_deterministic(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected network or external model call")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    request = Request("logic-grid", grid=copy.deepcopy(EXAMPLE))
    first = Generator().build(request)
    assert first == Generator().build(request)
    assert verify_bundle(first) == 1


def test_cli_reads_custom_grid_spec_and_replays(tmp_path):
    spec, out = tmp_path / "grid.json", tmp_path / "draft.json"
    spec.write_text(json.dumps(ORDER), encoding="utf-8")
    assert main(["generate", "--grid", str(spec), "--type", "type-answer", "--out", str(out)]) == 0
    assert main(["check", str(out)]) == 0
    assert json.loads(out.read_text())["version"] == 6
