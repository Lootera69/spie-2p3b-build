"""Joint clue/question synthesis preserves authored requirements and exact replay."""

import copy
import json
from itertools import combinations

import pytest

from spie.forge.corpus import digest
from spie.questions.brainbloom import Request, clue_synthesis, logic_grid, reasoning_constraints
from spie.questions.brainbloom.contract import issues
from spie.questions.brainbloom.grid_quality import propagate
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.workshop import candidate

ADA = {
    "groups": "Person: Ada, Bo, Cy\nColour: Red, Blue, Green",
    "rules": "", "complete": True, "target": "Ada", "answer_group": "Colour",
}
ORDER = {
    "groups": "Animal: Tiger, Lion, Owl",
    "rules": "Tiger is before Lion.\nOwl cannot be next to Tiger.",
    "complete": False, "target": "Owl", "answer_group": "Position",
}
# Recorded before revision 6 implementation, with the repository's pinned solvers.
REVISION_FIVE_DIGESTS = {
    "multiple-choice": "5d39de5238d8771581860d20b0c439c50fc1d7c1624e13e83cc8d8dce7b3f5fd",
    "true-false": "772c17234e0b2366652db99735aa37330b8564e41bef433ea2274f29ed13e2f2",
    "type-answer": "8e111aacf072a008b30688f0d94d42eb1efd1d405cc783c7787167045d8bede2",
    "riddle": "a05b0a805fddc64490980ff13b27019e1780d8be0f618370c09f76a202fd6909",
}


def answer_at(proof, row):
    model, query = proof["model"], proof["query"]
    target, group = query["target"], query["answer_group"]
    if group == -1:
        return str(row[target])
    return next(model["names"][i] for i in model["groups"][group]["indices"]
                if row[i] == row[target])


def minimum_support(proof):
    """Independently enumerate clue subsets, including the actual false-claim task."""
    model, solution = proof["model"], proof["solution_positions"]
    rules = [*proof["authored_rules"], *proof["added_rules"]]
    expected = proof.get("claim", answer_at(proof, solution))
    truth = proof.get("claim_holds", True)
    wrong = [row for row in logic_grid.worlds(model["size"], len(model["groups"]))
             if (answer_at(proof, row) == expected) != truth]
    for size in range(len(rules) + 1):
        for subset in combinations(range(len(rules)), size):
            if not any(all(logic_grid.holds(rules[i], row) for i in subset) for row in wrong):
                return size, wrong
    pytest.fail("The displayed answer is not forced by the clues")


def assert_certified(item, proof):
    model, solution = proof["model"], tuple(proof["solution_positions"])
    rules = [*proof["authored_rules"], *proof["added_rules"]]
    remaining = [row for row in logic_grid.worlds(model["size"], len(model["groups"]))
                 if all(logic_grid.holds(rule, row) for rule in rules)]
    assert remaining == [solution]
    assert proof["solution_count"] == 1
    assert issues(item) == []
    if "claim" in proof:
        truth = answer_at(proof, solution) == proof["claim"]
        assert proof["claim_holds"] is truth
        assert item["correctAnswer"] == str(truth)
    else:
        assert item["correctAnswer"] == answer_at(proof, solution)
    assert isinstance(proof["synthesis"], dict) and proof["synthesis"]
    certificate = proof["reasoning_constraints"]
    assert certificate["passed"] is True
    minimum, wrong = minimum_support(proof)
    assert certificate["minimum_supporting_clues"] == minimum
    support = certificate["supporting_clues"]
    assert len(support) == len(set(support)) == minimum
    assert all(type(i) is int and 1 <= i <= len(rules) for i in support)
    assert not any(all(logic_grid.holds(rules[i - 1], row) for i in support) for row in wrong)


@pytest.mark.parametrize("kind", REVISION_FIVE_DIGESTS)
def test_revision_five_reproduces_the_pre_synthesis_item_and_proof(kind):
    result = candidate(Request("logic-grid", kind, grid=ADA, engine_revision=5), 6)
    assert digest(list(result)) == REVISION_FIVE_DIGESTS[kind]


@pytest.mark.parametrize("kind", REVISION_FIVE_DIGESTS)
def test_every_current_answer_format_certifies_the_displayed_answer(kind):
    assert Request().engine_revision >= 6
    item, proof = candidate(Request("logic-grid", kind, grid=ORDER, engine_revision=6), 7)
    assert proof["authored_rules"] == logic_grid.parse(ORDER)["rules"]
    assert proof["added_rules"] == []
    assert_certified(item, proof)


@pytest.mark.parametrize("target,group", [
    ("Ada", "Colour"), ("Ada", ""), ("", "Colour"), ("", ""),
])
def test_joint_selection_preserves_authored_clues_and_explicit_query_restrictions(target, group):
    spec = {**ADA, "target": target, "answer_group": group,
            "rules": "Ada is before Bo.\nCy is not paired with Red."}
    before = copy.deepcopy(spec)
    item, proof = candidate(Request("logic-grid", grid=spec, engine_revision=6), 6)
    assert spec == before
    model = logic_grid.parse(spec)
    assert proof["authored_rules"] == model["rules"]
    assert proof["model"]["rules"] == model["rules"]
    query = proof["query"]
    if target:
        assert query["target"] == model["target"]
    if group:
        assert query["answer_group"] == model["answer_group"]
    assert query["answer_group"] != model["owners"][query["target"]]
    assert_certified(item, proof)
    for index in range(len(proof["added_rules"])):
        others = [rule for i, rule in enumerate(proof["added_rules"]) if i != index]
        assert len(logic_grid.survivors(model, [*model["rules"], *others])) > 1


def test_seed_six_joint_design_improves_answer_support_without_more_clues():
    _, old = candidate(Request("logic-grid", grid=ADA, engine_revision=5), 6)
    item, proof = candidate(Request("logic-grid", grid=ADA, engine_revision=6,
                                    min_supporting_clues=3), 6)
    assert old["solution_positions"] == [3, 1, 2, 2, 1, 3]
    assert proof["solution_positions"] == old["solution_positions"]
    assert minimum_support(old)[0] == 2
    assert proof["reasoning_constraints"]["minimum_supporting_clues"] >= 3
    assert len(proof["added_rules"]) <= len(old["added_rules"]) == 4
    assert_certified(item, proof)


def test_only_an_explicit_minimum_can_expand_a_too_small_baseline_clue_set():
    automatic_item, automatic = candidate(Request(
        "logic-grid", grid=ADA, difficulty="hard", engine_revision=6,
    ), 0)
    assert automatic["synthesis"]["baseline_added_clues"] == 3
    assert automatic["synthesis"]["preferred_support"] == 4
    assert automatic["synthesis"]["preferred_support_met"] is False
    assert len(automatic["added_rules"]) <= 3
    assert_certified(automatic_item, automatic)
    assert_search_within_budget(automatic["synthesis"])

    item, proof = candidate(Request(
        "logic-grid", grid=ADA, difficulty="hard", engine_revision=6, min_supporting_clues=4,
    ), 0)
    assert proof["solution_positions"] == automatic["solution_positions"]
    assert proof["authored_rules"] == automatic["authored_rules"] == []
    assert proof["query"] == automatic["query"]
    assert proof["synthesis"]["baseline_added_clues"] == 3
    assert len(proof["added_rules"]) == 4
    assert proof["reasoning_constraints"]["minimum_supporting_clues"] == 4
    assert proof["synthesis"]["preferred_support_met"] is True
    assert_certified(item, proof)
    assert_search_within_budget(proof["synthesis"])


def test_current_true_false_designs_keep_both_truth_values_and_exact_claim_support():
    truths = set()
    for seed in range(8):
        item, proof = candidate(Request("logic-grid", "true-false", grid=ORDER,
                                        engine_revision=6), seed)
        truths.add(proof["claim_holds"])
        assert_certified(item, proof)
    assert truths == {False, True}


def test_deduction_only_remains_a_checked_complete_trace_without_cases():
    item, proof = candidate(Request("logic-grid", grid=ORDER, engine_revision=6,
                                    reasoning_mode="deduction-only", min_supporting_clues=2), 7)
    assert_certified(item, proof)
    certificate = proof["reasoning_constraints"]
    assert certificate["deduction_only"] and certificate["case_checks"] == 0
    assert not certificate["exhaustive_fallback"]
    rules = [*proof["authored_rules"], *proof["added_rules"]]
    domains, _, conflict = propagate(proof["model"], rules)
    assert conflict is None and domains == [{p} for p in proof["solution_positions"]]


def test_completion_off_does_not_replace_full_grid_uniqueness_with_answer_uniqueness():
    spec = {"groups": "Person: Ada, Bo, Cy", "rules": "Ada is in position 1.",
            "complete": False, "target": "Ada", "answer_group": "Position"}
    with pytest.raises(ValueError, match="arrangements"):
        candidate(Request("logic-grid", grid=spec, engine_revision=6), 6)


def test_required_clues_cannot_be_removed_to_artificially_raise_answer_support():
    spec = {**ORDER, "rules": ORDER["rules"] + "\nOwl is in position 3."}
    with pytest.raises(ValueError):
        candidate(Request("logic-grid", grid=spec, engine_revision=6,
                          min_supporting_clues=2), 6)


def assert_search_within_budget(report):
    for counter, limit in (
        ("targets_evaluated", "target_budget"),
        ("candidate_evaluations", "candidate_budget"),
        ("search_nodes", "node_budget"),
        ("support_subsets_checked", "support_subset_budget"),
    ):
        assert type(report[counter]) is int
        assert 0 <= report[counter] <= report[limit]


@pytest.mark.parametrize("constant,limit,counter", [
    ("MAX_CANDIDATES", 0, "candidate_evaluations"),
    ("MAX_SUPPORT_SUBSETS", 0, "support_subsets_checked"),
    ("MAX_SEARCH_NODES", 0, "search_nodes"),
    ("MAX_SEARCH_NODES", 1, "search_nodes"),
])
def test_exhausted_search_returns_only_certified_auto_fallback_and_never_relaxes_a_minimum(
    monkeypatch, constant, limit, counter,
):
    monkeypatch.setattr(clue_synthesis, constant, limit)
    request = Request("logic-grid", grid=ADA, engine_revision=6)
    first = candidate(request, 6)
    assert candidate(request, 6) == first
    item, proof = first
    report = proof["synthesis"]
    assert report["budget_exhausted"] is True
    assert report[counter] == limit
    assert_search_within_budget(report)
    assert report["preferred_support_met"] is False
    assert proof["reasoning_constraints"]["minimum_supporting_clues"] == 2
    assert_certified(item, proof)
    if constant in ("MAX_CANDIDATES", "MAX_SUPPORT_SUBSETS"):
        # Search did not measure any answer. The separate final verifier must
        # supply the exact minimum rather than inventing a search measurement.
        assert report["selected_support"] is None
        assert proof["reasoning_constraints"]["support_subsets_checked"] > 0
    with pytest.raises(reasoning_constraints.ConstraintRejected, match="controls were not relaxed"):
        candidate(Request("logic-grid", grid=ADA, engine_revision=6,
                          min_supporting_clues=3), 6)


def test_auto_fallback_is_rejected_if_final_independent_support_check_exhausts(monkeypatch):
    monkeypatch.setattr(clue_synthesis, "MAX_CANDIDATES", 0)
    monkeypatch.setattr(reasoning_constraints, "MAX_SUPPORT_SUBSETS", 0)
    with pytest.raises(reasoning_constraints.ConstraintRejected, match="bounded search budget"):
        candidate(Request("logic-grid", grid=ADA, engine_revision=6), 6)


def test_automatic_query_selects_best_tested_support_without_overriding_a_fixed_target():
    spec = {**ORDER, "target": "",
            "rules": ORDER["rules"] + "\nTiger is in position 1."}
    item, proof = candidate(Request("logic-grid", grid=spec, engine_revision=6), 7)
    eligible = logic_grid._queries(proof["model"])
    assert len(eligible) <= clue_synthesis.MAX_TARGETS
    assert proof["synthesis"]["targets_evaluated"] == len(eligible)
    assert proof["added_rules"] == []
    supports = []
    for target, group in eligible:
        alternative = {**proof, "query": {"target": target, "answer_group": group}}
        supports.append(minimum_support(alternative)[0])
    assert len(set(supports)) > 1
    assert proof["reasoning_constraints"]["minimum_supporting_clues"] == max(supports)
    assert_certified(item, proof)
    assert_search_within_budget(proof["synthesis"])

    fixed = {**spec, "target": "Tiger"}
    fixed_item, fixed_proof = candidate(Request("logic-grid", grid=fixed, engine_revision=6), 7)
    assert fixed_proof["model"]["names"][fixed_proof["query"]["target"]] == "Tiger"
    assert fixed_proof["reasoning_constraints"]["minimum_supporting_clues"] == 1
    assert max(supports) > 1
    assert_certified(fixed_item, fixed_proof)


def test_unrepairable_best_baseline_query_does_not_block_a_weaker_querys_repair(monkeypatch):
    spec = {**ADA, "target": "", "answer_group": "",
            "rules": "Ada is before Bo.\nBo is before Cy."}
    original_targets = clue_synthesis._targets

    def first_authored_then_repairable(model, solution, queries, rng, qtype):
        # Isolate a legitimate sampled pair: Cy's position already has a short
        # authored proof, while Ada's colour can gain support by changing clues.
        cy, ada = model["names"].index("Cy"), model["names"].index("Ada")
        colour = next(i for i, group in enumerate(model["groups"]) if group["name"] == "Colour")
        sampled = [(cy, -1), (ada, colour)]
        assert all(query in queries for query in sampled)
        targets = original_targets(model, solution, sampled, rng, qtype)
        return sorted(targets, key=lambda target: target[0] != cy)

    monkeypatch.setattr(clue_synthesis, "_targets", first_authored_then_repairable)
    with monkeypatch.context() as baseline_budget:
        baseline_budget.setattr(clue_synthesis, "MAX_SEARCH_NODES", 0)
        baseline_item, baseline = candidate(Request("logic-grid", grid=spec,
                                                     engine_revision=6), 0)
    assert_certified(baseline_item, baseline)
    assert baseline["model"]["names"][baseline["query"]["target"]] == "Cy"
    assert baseline["query"]["answer_group"] == -1
    assert minimum_support({**baseline, "added_rules": []})[0] == 2
    ada_query = {"target": baseline["model"]["names"].index("Ada"), "answer_group": 1}
    assert minimum_support({**baseline, "query": ada_query})[0] == 1

    item, proof = candidate(Request("logic-grid", grid=spec, engine_revision=6,
                                    min_supporting_clues=3), 0)
    assert proof["solution_positions"] == baseline["solution_positions"]
    assert proof["authored_rules"] == baseline["authored_rules"]
    assert proof["query"] == ada_query
    assert proof["reasoning_constraints"]["minimum_supporting_clues"] >= 3
    assert len(proof["added_rules"]) <= len(baseline["added_rules"])
    assert proof["synthesis"]["targets_evaluated"] == 2
    assert proof["synthesis"]["targets_repaired"] >= 1
    assert proof["synthesis"]["baseline_support"] == 1
    assert_search_within_budget(proof["synthesis"])
    assert_certified(item, proof)


@pytest.fixture(scope="module")
def synthesis_bundle():
    return Generator().build(Request("logic-grid", grid=ADA, seed=6, engine_revision=6,
                                     min_supporting_clues=3))


def test_current_synthesis_and_its_saved_telemetry_are_deterministic(synthesis_bundle):
    request = Request(**synthesis_bundle["request"])
    again = Generator().build(request)
    assert again == synthesis_bundle
    assert verify_bundle(json.loads(json.dumps(synthesis_bundle))) == 1
    assert_certified(synthesis_bundle["items"][0], synthesis_bundle["proofs"][0])


@pytest.mark.parametrize("field", ["query", "added_rules", "synthesis", "reasoning_constraints"])
def test_replay_rejects_tampered_joint_design_or_support(synthesis_bundle, field):
    changed = copy.deepcopy(synthesis_bundle)
    proof = changed["proofs"][0]
    if field == "query":
        proof[field]["target"] = (proof[field]["target"] + 1) % len(proof["model"]["names"])
    elif field == "added_rules":
        proof[field][0]["text"] += " altered"
    else:
        proof[field]["tampered"] = True
    with pytest.raises(ValueError, match="freshly checked generation"):
        verify_bundle(changed)
