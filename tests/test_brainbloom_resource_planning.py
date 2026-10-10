"""Resource limits are proved by an oracle independent of both engine solvers."""

import copy
import json
import math
import random
import re
import shutil
from itertools import permutations
from pathlib import Path

import pytest

from spie.questions.brainbloom import Request
from spie.questions.brainbloom import resource_planning as plans
from spie.questions.brainbloom.contract import issues
from spie.questions.brainbloom.feedback import feedback_for
from spie.questions.brainbloom.service import Generator, verify_bundle

FORMATS = ("multiple-choice", "true-false", "type-answer", "riddle")
VERIFIER = Path(__file__).resolve().parents[3] / "BrainBloom/lib/forge/verify.ts"


def _oracle(model):
    """A deliberately simple test oracle that does not call the production replay."""
    results = []
    for order in permutations(range(1, len(model["names"]))):
        stops = (0, *order, 0)
        times = [model["travel_time"][a][b] for a, b in zip(stops, stops[1:], strict=False)]
        fuel = sum(model["travel_fuel"][a][b] for a, b in zip(stops, stops[1:], strict=False))
        if 0 in times:
            results.append({"order": list(order), "time": None, "fuel": None,
                            "violations": {"unlisted-leg"}})
            continue
        reasons = set()
        if fuel > model["fuel_budget"]:
            reasons.add("fuel")
        if any(sum(times[:i + 1]) > model["deadlines"][task]
               for i, task in enumerate(order)):
            reasons.add("deadline")
        if any(order.index(a) >= order.index(b) for a, b in model["dependencies"]):
            reasons.add("dependency")
        results.append({"order": list(order), "time": sum(times), "fuel": fuel,
                        "violations": reasons})
    return results


def _base():
    return {"names": ["Depot", "Alpha", "Beta", "Gamma"], "level": 1,
            "travel_time": [[0, 1, 1, 1], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]],
            "travel_fuel": [[0, 1, 1, 1], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]],
            "fuel_budget": 4, "deadlines": [None, 1, 2, 3],
            "dependencies": [[1, 2], [2, 3]]}


@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize("seed", range(10))
def test_resource_plans_match_independent_oracle_and_each_constraint_is_necessary(level, seed):
    names = ["Depot", "Alpha", "Beta", "Gamma", "Delta", "Epsilon"][:level + 3]
    model = plans.propose(names, level, random.Random(seed))
    proof = plans.check(model)
    oracle = _oracle(model)
    feasible = [row for row in oracle if not row["violations"]]
    fastest = min(row["time"] for row in feasible)
    winners = [row for row in feasible if row["time"] == fastest]
    assert len(winners) == 1
    assert model["solution"] == winners[0]["order"]
    assert model["options"][model["answer_index"]] == winners[0]["order"]
    assert model["best_time"] == fastest
    dynamic = plans.solve(model)
    assert dynamic["feasible_count"] == len(feasible)
    assert dynamic["optimal_count"] == 1
    assert dynamic["solution"] == winners[0]["order"]
    assert proof["quality"]["routes_checked"] == math.factorial(level + 2) <= 120
    assert proof["quality"]["faster_infeasible_routes"] > 0
    assert proof["quality"]["faster_infeasible_options"] > 0
    if level > 1:
        assert not proof["quality"]["cheapest_first_leg_is_optimal"]
    for constraint in plans.CONSTRAINTS:
        only_this_constraint = [row for row in oracle if row["violations"] == {constraint}]
        assert only_this_constraint
        assert proof["quality"]["independently_rejected_routes"][constraint] == len(
            only_this_constraint)
        relaxed = [row for row in oracle if row["violations"] <= {constraint}]
        assert len(relaxed) > len(feasible)
        assert proof["quality"]["constraint_ablation_feasible_counts"][constraint] == len(relaxed)
        # The rule is necessary even for the four choices visible to a learner.
        option_violations = [{v["constraint"] for v in option["violations"]}
                             for option in proof["option_costs"].values()]
        assert option_violations.count({constraint}) == 1
    for option in proof["option_costs"].values():
        expected = next(row for row in oracle if row["order"] == option["order"])
        assert option["time"] == expected["time"]
        assert option["fuel"] == expected["fuel"]
        assert option["feasible"] == (not expected["violations"])
        assert {v["constraint"] for v in option["violations"]} == expected["violations"]
        assert all(option["reasons"]) if option["reasons"] else option["is_answer"]


def test_exact_fuel_and_deadline_are_inclusive_and_depot_return_consumes_fuel():
    model = _base()
    route = plans.interpret(model, [1, 2, 3])
    assert route["feasible"] and route["time"] == route["fuel"] == 4
    assert all(row["time"] == row["deadline"] for row in route["arrivals"])
    assert plans.solve(model)["solution"] == [1, 2, 3]
    model["fuel_budget"] = 3  # All deliveries fit, but the return leg does not.
    assert plans.solve(model)["feasible_count"] == 0
    assert {v["constraint"] for v in plans.interpret(model, [1, 2, 3])["violations"]} == {
        "fuel"}
    model["fuel_budget"] = 4
    model["deadlines"][2] = 1
    assert plans.solve(model)["feasible_count"] == 0
    assert {v["constraint"] for v in plans.interpret(model, [1, 2, 3])["violations"]} == {
        "deadline"}


def test_prerequisite_is_checked_against_the_whole_delivery_order():
    model = _base()
    model["deadlines"] = [None, 100, 100, 100]
    model["dependencies"] = [[1, 3]]
    assert plans.interpret(model, [2, 1, 3])["feasible"]
    rejected = plans.interpret(model, [2, 3, 1])
    assert [v["constraint"] for v in rejected["violations"]] == ["dependency"]
    assert plans.solve(model)["feasible_count"] == 3


def test_missing_legs_are_unusable_even_on_the_final_return():
    model = _base()
    model["travel_time"][1][3] = model["travel_time"][3][1] = 0
    model["travel_fuel"][1][3] = model["travel_fuel"][3][1] = 0
    assert plans.solve(model)["solution"] == [1, 2, 3]
    blocked = plans.interpret(model, [1, 3, 2])
    assert blocked["time"] is None and blocked["fuel"] is None
    assert {v["constraint"] for v in blocked["violations"]} == {"unlisted-leg"}
    model["travel_time"][0][3] = model["travel_time"][3][0] = 0
    model["travel_fuel"][0][3] = model["travel_fuel"][3][0] = 0
    assert plans.solve(model)["feasible_count"] == 0
    assert not plans.interpret(model, [1, 2, 3])["feasible"]


def test_impossible_and_equal_cost_ambiguous_models_are_rejected():
    impossible = _base()
    impossible["fuel_budget"] = 0
    assert plans.solve(impossible)["best_time"] is None
    with pytest.raises(RuntimeError, match="impossible"):
        plans.check(impossible)
    cyclic = _base()
    cyclic["dependencies"].append([3, 1])
    assert plans.solve(cyclic)["feasible_count"] == 0
    with pytest.raises(RuntimeError, match="impossible"):
        plans.check(cyclic)
    ambiguous = _base()
    ambiguous["deadlines"] = [None, 100, 100, 100]
    ambiguous["dependencies"] = [[1, 2]]
    dynamic = plans.solve(ambiguous)
    assert dynamic["best_time"] == 4 and dynamic["optimal_count"] == 3
    with pytest.raises(RuntimeError, match="ambiguous"):
        plans.check(ambiguous)


@pytest.mark.parametrize("field,value", [
    ("names", ["Same", "same", "Beta", "Gamma"]),
    ("names", ["Depot", "Alpha", "Beta"]),
    ("level", True), ("level", 2), ("fuel_budget", -1), ("fuel_budget", False),
    ("travel_time", [[0, 1], [1, 0]]),
    ("travel_fuel", [[0, 0, 1, 1], [0, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]]),
    ("deadlines", [None, 1, None, 3]), ("deadlines", [0, 1, 2, 3]),
    ("dependencies", []), ("dependencies", [[1, 4]]), ("dependencies", [[1, 1]]),
    ("dependencies", [[1, 2], [1, 2]]),
])
def test_bad_resource_models_are_rejected_before_search(field, value):
    model = _base()
    model[field] = value
    with pytest.raises(ValueError):
        plans.solve(model)


@pytest.mark.parametrize("order", [[1, 2], [1, 2, 2], [0, 1, 2, 3], [True, 2, 3], [1, 2, 4]])
def test_routes_cannot_skip_repeat_invent_or_return_early(order):
    with pytest.raises(ValueError, match="every delivery exactly once"):
        plans.interpret(_base(), order)


def test_claimed_answer_full_witness_and_cost_are_not_trusted():
    model = plans.propose(_base()["names"], 1, random.Random(7))
    wrong = (model["answer_index"] + 1) % 4
    for field, value in [("answer_index", wrong), ("solution", model["options"][wrong]),
                         ("best_time", model["best_time"] + 1), ("answer_index", True)]:
        tampered = copy.deepcopy(model)
        tampered[field] = value
        with pytest.raises(RuntimeError, match="witness disagrees"):
            plans.check(tampered)
    model["options"][wrong] = list(model["solution"])
    with pytest.raises(ValueError, match="four distinct"):
        plans.check(model)


def test_disagreement_between_solvers_fails_closed(monkeypatch):
    model = plans.propose(_base()["names"], 1, random.Random(11))
    actual = plans.solve(model)
    monkeypatch.setattr(plans, "solve", lambda _: {**actual, "feasible_count": 99})
    with pytest.raises(RuntimeError, match="disagreed"):
        plans.check(model)


@pytest.mark.parametrize("level", [1, 2, 3])
def test_seeded_batches_are_reproducible_diverse_and_bounded(level):
    names = ["Depot", "Alpha", "Beta", "Gamma", "Delta", "Epsilon"][:level + 3]
    rng_a, rng_b = random.Random(47), random.Random(47)
    batch_a = [plans.propose(names, level, rng_a) for _ in range(5)]
    batch_b = [plans.propose(names, level, rng_b) for _ in range(5)]
    assert batch_a == batch_b
    proofs = [plans.check(model) for model in batch_a]
    assert len({proof["structural_key"] for proof in proofs}) == 5
    assert all(proof["quality"]["routes_checked"] <= 120 for proof in proofs)


def test_player_gets_every_number_rule_topic_label_and_specific_option_reason():
    names = ["Coral", "Reef", "Whale", "Tide", "Pearl", "Wave"]
    model = plans.propose(names, 3, random.Random(12))
    draft = plans.render(model)
    stem = draft["stem"]
    assert all(name in stem for name in names)
    assert "Fictional" in stem
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            if model["travel_time"][a][b]:
                assert (f"{names[a]} ↔ {names[b]}: {model['travel_time'][a][b]}/"
                        f"{model['travel_fuel'][a][b]}") in stem
            else:
                assert f"{names[a]} ↔ {names[b]}:" not in stem
    for i in range(1, len(names)):
        assert f"{names[i]}≤{model['deadlines'][i]}" in stem
    for a, b in model["dependencies"]:
        assert f"{names[a]}→{names[b]}" in stem
    assert f"fuel≤{model['fuel_budget']}" in stem
    assert "minute 0" in stem and "instantly" in stem
    assert "Start/end" in stem and "Arrival deadlines" in stem
    assert "Only listed reversible legs (minutes/fuel)" in stem and "No refueling" in stem
    assert "Visit others once" in stem and "Deliver before" in stem
    assert len({draft["answer"], *draft["distractors"]}) == 4
    assert draft["answer"] in draft["explanation"]
    for option in draft["proof"]["option_costs"].values():
        assert all(reason in draft["explanation"] for reason in option["reasons"])


def test_excess_tasks_and_invalid_level_cannot_start_factorial_search():
    with pytest.raises(ValueError, match="level"):
        plans.propose([str(i) for i in range(7)], 4, random.Random(1))
    with pytest.raises(ValueError, match="level"):
        plans.propose(_base()["names"], True, random.Random(1))


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
@pytest.mark.parametrize("kind", FORMATS)
@pytest.mark.parametrize("seed", [3, 19])
def test_full_generator_batches_replay_and_coach_every_option(difficulty, kind, seed):
    request = Request("activities", kind, difficulty, variation="resource-plan",
                      subject="space, ocean", topic_mode="combined", count=2, seed=seed)
    engine = Generator()
    bundle = engine.build(request)
    assert bundle["summary"]["complete"], bundle["rejected"]
    assert bundle == engine.build(request)
    saved = json.loads(json.dumps(bundle))
    assert verify_bundle(saved) == 2
    assert len({p["structural_key"] for p in saved["proofs"]}) == 2
    for item, proof in zip(saved["items"], saved["proofs"], strict=True):
        assert issues(item) == []
        assert len(re.findall(r"[a-z0-9]+", item["question"].lower())) <= 120
        assert len(proof["word_bank"]) == {"easy": 4, "medium": 5, "hard": 6}[difficulty]
        assert all(word in item["question"] for word in proof["word_bank"])
        assert {topic["term"] for topic in proof["topic_coverage"]} == {"space", "ocean"}
        assert all(topic["used_words"] for topic in proof["topic_coverage"])
        before = copy.deepcopy((item, proof))
        if kind == "multiple-choice":
            assert item["choices"] == ["Plan A", "Plan B", "Plan C", "Plan D"]
        if kind == "true-false":
            claim = proof["claim"]
            option = proof["option_costs"][claim]
            assert proof["claim_holds"] is option["is_answer"]
            for submitted in ("True", "False"):
                feedback = feedback_for(item, proof, submitted)
                assert feedback["supported"]
                assert feedback["correct"] is (submitted == item["correctAnswer"])
                assert claim in feedback["message"]
                assert f"The claim is {str(proof['claim_holds']).lower()}." in feedback["message"]
                assert all(reason in feedback["message"] for reason in option["reasons"])
        else:
            for label, option in proof["option_costs"].items():
                feedback = feedback_for(item, proof, label)
                assert feedback["supported"]
                assert feedback["correct"] is option["is_answer"]
                assert label in feedback["message"]
                assert all(reason in feedback["message"] for reason in option["reasons"])
                if option["is_answer"]:
                    assert f"{option['time']} minutes" in feedback["message"]
                    assert f"{option['fuel']} fuel" in feedback["message"]
                if kind in {"type-answer", "riddle"}:
                    letter = feedback_for(item, proof, label[-1].lower())
                    assert letter["supported"]
                    assert letter["correct"] is option["is_answer"]
                    assert label in letter["message"]
                    assert all(reason in letter["message"] for reason in option["reasons"])
            if kind in {"type-answer", "riddle"}:
                feedback = feedback_for(item, proof, "answer: " + item["correctAnswer"])
                assert feedback["correct"] and feedback["supported"]
        assert (item, proof) == before


@pytest.fixture
def saved_resource_bundle():
    bundle = Generator().build(Request("activities", "multiple-choice", "hard",
                                       variation="resource-plan", subject="space, ocean",
                                       topic_mode="combined", seed=29))
    assert verify_bundle(bundle) == 1
    return json.loads(json.dumps(bundle))


@pytest.mark.parametrize("target", ["fuel", "deadline", "dependency", "return-leg", "option",
                                   "witness", "option-time", "reason", "quality", "structure",
                                   "answer", "request"])
def test_saved_resource_bundle_rejects_forged_model_evidence_and_answers(
    saved_resource_bundle, target,
):
    bundle = saved_resource_bundle
    proof = bundle["proofs"][0]
    model = proof["model"]
    if target == "fuel":
        model["fuel_budget"] += 1
    elif target == "deadline":
        model["deadlines"][1] += 1
    elif target == "dependency":
        model["dependencies"][0].reverse()
    elif target == "return-leg":
        last = model["solution"][-1]
        model["travel_time"][last][0] += 1
        model["travel_time"][0][last] += 1
    elif target == "option":
        model["options"][0].reverse()
    elif target == "witness":
        proof["witness"]["path"][-1] = 1
    elif target == "option-time":
        proof["option_costs"]["Plan A"]["time"] += 1
    elif target == "reason":
        option = next(o for o in proof["option_costs"].values() if not o["is_answer"])
        option["reasons"] = ["This plan has no problem."]
    elif target == "quality":
        proof["quality"]["routes_checked"] += 1
    elif target == "structure":
        proof["structural_key"] = "forged"
    elif target == "answer":
        bundle["items"][0]["correctAnswer"] = "Plan Z"
    else:
        bundle["request"]["seed"] += 1
    with pytest.raises(ValueError):
        verify_bundle(bundle)


@pytest.mark.skipif(not VERIFIER.is_file() or not shutil.which("node"),
                    reason="Optional sibling Studio verifier and Node are not installed")
@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
@pytest.mark.parametrize("kind", FORMATS)
def test_resource_plans_pass_actual_studio_editorial_gate(difficulty, kind):
    bundle = Generator(verifier=VERIFIER).build(Request(
        "activities", kind, difficulty, variation="resource-plan", subject="space, ocean",
        topic_mode="combined", seed=7))
    assert bundle["summary"]["complete"], bundle["rejected"]
    assert verify_bundle(bundle) == 1


@pytest.mark.skipif(not VERIFIER.is_file() or not shutil.which("node"),
                    reason="Optional sibling Studio verifier and Node are not installed")
def test_multiword_subjects_still_use_single_word_labels_and_pass_tight_editorial_limit():
    bundle = Generator(verifier=VERIFIER).build(Request(
        "activities", "true-false", "hard", variation="resource-plan",
        subject="machine learning, renewable energy, robotics", topic_mode="combined", seed=8))
    assert bundle["summary"]["complete"], bundle["rejected"]
    assert all(re.fullmatch(r"[A-Z]{3,15}", name) for name in bundle["proofs"][0]["word_bank"])
    assert verify_bundle(bundle) == 1
