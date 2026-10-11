"""Creator controls certify the displayed answer and never lower requested gates."""

import copy
import random
from itertools import combinations

import pytest

from spie.questions.brainbloom import Request, autopilot, logic_grid, reasoning_constraints
from spie.questions.brainbloom.brief import ACTIVITIES, Brief, configuration, prepare
from spie.questions.brainbloom.grid_quality import propagate
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.topics import resolve_many
from spie.questions.brainbloom.workshop import candidate

ORDER = {"groups": "Animal: Tiger, Lion, Owl", "rules":
         "Tiger is before Lion.\nOwl cannot be next to Tiger.",
         "complete": False, "target": "Owl", "answer_group": "Position"}
CASE_GRID = {
    "groups": ("Person: Ada, Bo, Cy, Dee\nColour: Red, Blue, Green, Pink\n"
               "Drink: Tea, Coffee, Milk, Juice"),
    "rules": ("Bo is paired with Tea.\nPink is paired with Coffee.\n"
              "Cy is paired with Green.\nMilk is before Cy.\nBlue is before Milk.\n"
              "Ada is next to Milk.\nRed is before Coffee."),
    "complete": False, "target": "Cy", "answer_group": "Colour",
}


def assert_exact_support(proof):
    model, solution, query = proof["model"], proof["solution_positions"], proof["query"]
    rules = [*proof["authored_rules"], *proof["added_rules"]]
    target, group = query["target"], query["answer_group"]
    if group == -1:
        claimed = int(proof.get("claim", solution[target]))

        def claim_holds(row):
            return row[target] == claimed
    else:
        claimed = (model["names"].index(proof["claim"]) if "claim" in proof else
                   next(i for i in model["groups"][group]["indices"]
                        if solution[i] == solution[target]))

        def claim_holds(row):
            return row[target] == row[claimed]

    wrong = [row for row in logic_grid.worlds(model["size"], len(model["groups"]))
             if claim_holds(row) != proof.get("claim_holds", True)]
    certificate = proof["reasoning_constraints"]
    minimum = certificate["minimum_supporting_clues"]
    for size in range(minimum):
        for subset in combinations(rules, size):
            assert any(all(logic_grid.holds(rule, row) for rule in subset) for row in wrong)
    support = [rules[number - 1] for number in certificate["supporting_clues"]]
    assert len(support) == minimum
    assert not any(all(logic_grid.holds(rule, row) for rule in support) for row in wrong)


@pytest.mark.parametrize("qtype", ["multiple-choice", "true-false", "type-answer", "riddle"])
def test_custom_grid_deduction_only_and_exact_two_clue_answer(qtype):
    request = Request("logic-grid", qtype, grid=ORDER, reasoning_mode="deduction-only",
                      min_supporting_clues=2)
    bundle = Generator().build(request)
    proof = bundle["proofs"][0]
    certificate = proof["reasoning_constraints"]
    assert certificate["passed"] and certificate["deduction_only"]
    assert certificate["minimum_supporting_clues"] == 2
    assert certificate["case_checks"] == 0 and not certificate["exhaustive_fallback"]
    assert all(step["kind"] == "constraint" for step in proof["quality"]["deductions"])
    domains, _, conflict = propagate(proof["model"], proof["authored_rules"])
    assert conflict is None
    assert domains == [{position} for position in proof["solution_positions"]]
    assert_exact_support(proof)
    assert verify_bundle(bundle) == 1


@pytest.mark.parametrize("minimum", [2, 3, 4])
@pytest.mark.parametrize("revision", [5, 6])
def test_autopilot_proposes_until_both_requested_gates_hold(minimum, revision):
    request = Request("autopilot", difficulty="hard", subject="animals", seed=7,
                      reasoning_mode="deduction-only", min_supporting_clues=minimum,
                      engine_revision=revision)
    bundle = Generator().build(request)
    proof = bundle["proofs"][0]
    assert proof["reasoning_constraints"]["minimum_supporting_clues"] >= minimum
    assert proof["reasoning_constraints"]["deduction_only"]
    expected_budget = (autopilot.SYNTHESIS_BUDGET if revision == 6
                       else autopilot.CONSTRAINED_BUDGET)
    assert proof["search"]["budget"] == expected_budget
    assert proof["search"]["qualified"] + proof["search"]["rejected"] == proof["search"]["budget"]
    domains, _, conflict = propagate(proof["model"], proof["added_rules"])
    assert conflict is None and domains == [{p} for p in proof["solution_positions"]]
    assert_exact_support(proof)
    assert verify_bundle(bundle) == 1


def test_a_case_solved_grid_does_not_qualify_as_deduction_only():
    _, proof = candidate(Request("logic-grid", grid=CASE_GRID), 0)
    assert proof["quality"]["propagation_complete"] and proof["quality"]["case_checks"] > 0
    domains, _, conflict = propagate(proof["model"], proof["authored_rules"])
    assert conflict is None and any(len(values) > 1 for values in domains)
    with pytest.raises(ValueError, match="without case assumptions"):
        candidate(Request("logic-grid", grid=CASE_GRID, reasoning_mode="deduction-only"), 0)


def test_false_claim_support_is_not_inflated_by_the_full_query():
    # Owl's correct position needs two rules, but one ordering rule rules out Owl at 1.
    spec = {"groups": "Animal: Tiger, Lion, Owl", "rules":
            "Tiger is before Owl.\nLion is before Tiger.",
            "target": "Owl", "answer_group": "Position", "complete": False}
    _, proof = candidate(Request("logic-grid", grid=spec), 0)
    proof.update(claim="1", claim_holds=False)
    request = Request("logic-grid", "true-false", grid=spec, min_supporting_clues=2)
    with pytest.raises(reasoning_constraints.ConstraintRejected, match="only 1"):
        reasoning_constraints.certify(request, proof)


@pytest.mark.parametrize("revision", [5, 6])
def test_custom_grid_exhaustion_is_bounded_and_does_not_relax(monkeypatch, revision):
    original = logic_grid._candidate_once
    calls = []

    def counted(request, rng):
        calls.append(1)
        return original(request, rng)

    monkeypatch.setattr(logic_grid, "_candidate_once", counted)
    with pytest.raises(ValueError, match="controls were not relaxed"):
        candidate(Request("logic-grid", grid=ORDER, min_supporting_clues=4,
                          engine_revision=revision), 0)
    assert len(calls) == (1 if revision == 6 else logic_grid.CONSTRAINED_BUDGET)


@pytest.mark.parametrize("revision", [5, 6])
def test_autopilot_exhaustion_rejects_every_proposal_without_early_abort(monkeypatch, revision):
    calls = []
    item, proof = candidate(Request("logic-grid", grid=ORDER), 0)

    def fixed_proposal(request, rng):
        calls.append(1)
        return copy.deepcopy((item, proof))

    monkeypatch.setattr(logic_grid, "candidate", fixed_proposal)
    context = resolve_many(Dictionary(), "animals", {}, "logic")
    with pytest.raises(ValueError, match="controls were not relaxed"):
        autopilot.candidate(Request("autopilot", min_supporting_clues=4,
                                    engine_revision=revision), random.Random(0), context)
    assert len(calls) == (autopilot.SYNTHESIS_BUDGET if revision == 6
                          else autopilot.CONSTRAINED_BUDGET)


def test_exact_support_work_cap_rejects_uncertified_output(monkeypatch):
    monkeypatch.setattr(reasoning_constraints, "MAX_SUPPORT_SUBSETS", 0)
    with pytest.raises(ValueError, match="bounded search budget"):
        candidate(Request("logic-grid", grid=ORDER, min_supporting_clues=2), 0)


@pytest.mark.parametrize("fields", [
    {"reasoning_mode": "deduction"}, {"reasoning_mode": None}, {"reasoning_mode": True},
    {"min_supporting_clues": True}, {"min_supporting_clues": 2.0},
    {"min_supporting_clues": "2"}, {"min_supporting_clues": 1},
    {"min_supporting_clues": 5}, {"min_supporting_clues": None},
])
def test_invalid_controls_are_rejected_by_both_api_types(fields):
    with pytest.raises(ValueError):
        Request("autopilot", **fields)
    with pytest.raises(ValueError):
        Brief(activity="autopilot", **fields)


@pytest.mark.parametrize("activity", ["arithmetic", "deduction", "resource-plan", "auto"])
def test_prepare_and_request_refuse_unsupported_activity_combinations(activity):
    report = prepare(Brief(activity=activity, min_supporting_clues=2), Dictionary())
    assert not report["ready"] and report["request"] is None
    assert "only to Autopilot and custom logic grids" in report["message"]
    selected = ACTIVITIES.get(activity, ACTIVITIES["deduction"])
    with pytest.raises(ValueError, match="only to Autopilot"):
        Request(selected.family, variation=selected.variation, min_supporting_clues=2)


def test_prepare_reports_the_controls_and_resource_plan_capacity():
    dictionary = Dictionary()
    for activity in ("autopilot", "logic-grid"):
        report = prepare(Brief(activity=activity, reasoning_mode="deduction-only",
                               min_supporting_clues=3), dictionary)
        assert report["ready"] and report["reasoning_relevant"]
        assert report["request"]["reasoning_mode"] == "deduction-only"
        assert report["request"]["min_supporting_clues"] == 3
        assert "human difficulty" in report["reasoning_controls"]["scope"]
    report = prepare(Brief(activity="resource-plan", difficulty="easy",
                           subject="animals, space, ocean, plants, science"), dictionary)
    assert not report["ready"] and "4 words" in report["message"]
    assert [o["available"] for o in report["difficulty_options"]] == [False, True, True]
    assert configuration()["minimum_supporting_clues"] == ("auto", 2, 3, 4)


@pytest.mark.parametrize("topic", ["logic-grid", "autopilot"])
def test_default_controls_preserve_old_generation_and_old_bundle_replay(topic):
    kwargs = {"grid": ORDER} if topic == "logic-grid" else {"subject": "animals"}
    assert candidate(Request(topic, engine_revision=4, **kwargs), 7) == candidate(
        Request(topic, engine_revision=5, **kwargs), 7)
    bundle = Generator().build(Request(topic, engine_revision=4, **kwargs))
    bundle["request"].pop("reasoning_mode", None)
    bundle["request"].pop("min_supporting_clues", None)
    assert verify_bundle(bundle) == 1


@pytest.mark.parametrize("revision", [1, 2, 3, 4])
def test_new_controls_and_resource_planning_cannot_be_smuggled_into_old_revisions(revision):
    with pytest.raises(ValueError, match="revision 5"):
        Request("autopilot", engine_revision=revision, min_supporting_clues=2)
    with pytest.raises(ValueError, match="revision 5"):
        Request("activities", variation="resource-plan", engine_revision=revision)


def test_saved_constraint_certificate_is_recomputed():
    bundle = Generator().build(Request("logic-grid", grid=ORDER, min_supporting_clues=2))
    bundle["proofs"][0]["reasoning_constraints"]["minimum_supporting_clues"] = 4
    with pytest.raises(ValueError, match="freshly checked generation"):
        verify_bundle(bundle)


@pytest.mark.parametrize("topic", ["logic-grid", "autopilot"])
def test_historical_bundles_without_revision_or_controls_still_replay(topic):
    kwargs = {"grid": ORDER} if topic == "logic-grid" else {"subject": "animals"}
    bundle = Generator().build(Request(topic, engine_revision=1, **kwargs))
    assert "reasoning_mode" not in bundle["request"]
    assert "min_supporting_clues" not in bundle["request"]
    bundle["request"].pop("engine_revision")
    assert verify_bundle(bundle) == 1


@pytest.mark.parametrize("field", ["reasoning_mode", "min_supporting_clues", "engine_revision"])
def test_saved_requests_cannot_drop_a_control_or_downgrade_its_revision(field):
    bundle = Generator().build(Request("logic-grid", grid=ORDER, reasoning_mode="deduction-only",
                                       min_supporting_clues=2))
    bundle["request"].pop(field)
    with pytest.raises(ValueError):
        verify_bundle(bundle)
