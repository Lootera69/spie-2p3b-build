"""Answer coaching must describe the selected option and a real proof consequence."""

import copy
from dataclasses import asdict

import pytest

from spie.questions.brainbloom import Request, deduction, logic_grid, patterns, routes
from spie.questions.brainbloom.feedback import feedback_for, grid_feedback
from spie.questions.brainbloom.service import Generator, verify_bundle


def quiz(answer, kind="multiple-choice"):
    item = {"type": kind, "correctAnswer": answer,
            "correctExplanation": "DO NOT DUMP THE FULL SOLUTION",
            "incorrectExplanation": "DO NOT DUMP THE FULL SOLUTION"}
    if kind in {"type-answer", "riddle"}:
        item["acceptedAnswers"] = [answer, "the answer is " + answer, "answer: " + answer]
    return item


@pytest.fixture
def route_pair():
    model = {
        "names": ["Start", "A", "B", "C", "Finish"],
        "edges": [[0, 1, 1], [1, 4, 9], [0, 2, 4], [2, 4, 2],
                  [0, 3, 2], [3, 4, 6], [0, 4, 12]],
        "start": 0, "goal": 4, "answer": 2,
        "options": [{"next": 1, "cost": 10, "path": [0, 1, 4]},
                    {"next": 2, "cost": 6, "path": [0, 2, 4]},
                    {"next": 3, "cost": 8, "path": [0, 3, 4]},
                    {"next": 4, "cost": 12, "path": [0, 4]}],
    }
    return quiz("B"), routes.check(model)


def test_route_feedback_compares_whole_trip_and_does_not_mutate(route_pair):
    item, proof = route_pair
    before = copy.deepcopy(route_pair)
    result = feedback_for(item, proof, "A")
    assert result["correct"] is False and result["supported"] is True
    assert "Starting with A" in result["message"]
    assert "costs 10" in result["message"] and "total is 6" in result["message"]
    assert "4 extra" in result["message"]
    assert "DO NOT DUMP" not in result["message"]
    assert feedback_for(item, proof, "B")["correct"] is True
    assert route_pair == before


@pytest.mark.parametrize("claim,holds", [("A", False), ("B", True)])
@pytest.mark.parametrize("submitted", ["True", "False", " TRUE ", "false"])
def test_true_false_coaches_claim_instead_of_boolean(route_pair, claim, holds, submitted):
    _, proof = route_pair
    proof.update(claim=claim, claim_holds=holds)
    result = feedback_for(quiz(str(holds), "true-false"), proof, submitted)
    assert result["correct"] is (submitted.strip().lower() == str(holds).lower())
    assert result["supported"] is True
    assert f"The claim is {str(holds).lower()}." in result["message"]
    assert f"Starting with {claim}" in result["message"]


@pytest.mark.parametrize("submitted", ["yes", "no", "1", "0", "answer: True"])
def test_true_false_only_accepts_canonical_words(route_pair, submitted):
    _, proof = route_pair
    proof.update(claim="B", claim_holds=True)
    result = feedback_for(quiz("True", "true-false"), proof, submitted)
    assert result == {"correct": False, "supported": False,
                      "message": "Choose True or False to check this claim."}


@pytest.mark.parametrize("kind", ["type-answer", "riddle"])
def test_typed_aliases_normalize_unicode_case_and_whitespace(route_pair, kind):
    _, proof = route_pair
    result = feedback_for(quiz("B", kind), proof, "  ＡＮＳＷＥＲ：   b  ")
    assert result["correct"] is True and result["supported"] is True
    assert "Starting with B" in result["message"]


@pytest.mark.parametrize("wrong", ["-4", "4.0", "4!", "", "another idea"])
def test_typed_matching_preserves_meaningful_punctuation_and_unknown_fallback(wrong):
    result = feedback_for(quiz("4", "type-answer"), {"agree": True}, wrong)
    assert result["correct"] is False and result["supported"] is False
    assert "DO NOT DUMP" not in result["message"]
    assert "Rule" not in result["message"] and "contradict" not in result["message"]


def test_pattern_wrong_output_identifies_rule_and_observed_counterexample():
    model = {"names": ["First", "Second"], "rules": [[0, 1, 1], [0, 2, 0],
              [0, 3, 0], [0, 0, -4]], "examples": [[1, 2], [2, 3]],
             "answer_index": 0, "query": 5, "answer": 6}
    proof = patterns.check(model)
    result = feedback_for(quiz("6"), proof, "10")
    assert result["supported"] is True and result["correct"] is False
    assert "Rule B" in result["message"]
    assert "gives 4 for input 2" in result["message"]
    assert "example gives 3" in result["message"]
    negative = feedback_for(quiz("6"), proof, "-4")
    assert "Rule D" in negative["message"] and "gives -4 for input 1" in negative["message"]
    assert feedback_for(quiz("6"), proof, "4")["supported"] is False
    assert feedback_for(quiz("6"), proof, "6")["correct"] is True


def test_deduction_conflict_is_a_combination_not_arbitrary_single_clue():
    model = {"names": ["A", "B", "C", "D"], "solution": [0, 1, 2, 3],
             "clues": [asdict(deduction.Clue("before", i, i + 1)) for i in range(3)],
             "answer_index": 1, "position": 1, "minimum_support": 3}
    proof = deduction.check(model)
    proof["model"] = model
    result = feedback_for(quiz("B"), proof, "C")
    assert result["correct"] is False and result["supported"] is True
    assert "Clues 1–2 together rule out C in position 2" in result["message"]
    assert "B is left of C" in result["message"]
    # Each clue separately permits C at position 2; their combination does not.
    rows = [row for row in deduction.worlds(4) if row[2] == 1]
    assert all(deduction.survivors(rows, [deduction.Clue(**c)]) for c in model["clues"])
    assert not deduction.survivors(rows, [deduction.Clue(**c) for c in model["clues"]])
    assert feedback_for(quiz("B"), proof, "B")["supported"] is True


def test_possible_but_unforced_answer_is_not_called_a_contradiction():
    model = {"names": ["A", "B", "C", "D"], "position": 2,
             "clues": [asdict(deduction.Clue("before", 0, 1))]}
    proof = {"method": "z3-and-exhaustive-constraint-search", "agree": True, "model": model}
    result = feedback_for(quiz("B"), proof, "C")
    assert result["supported"] is False
    assert "conflict" not in result["message"] and "rule out" not in result["message"]


@pytest.mark.parametrize("group,canonical,submitted,description", [
    (-1, "1", "2", "A in position 2"),
    (1, "Red", "Blue", "A paired with Blue"),
])
def test_grid_uses_submitted_placement_and_includes_added_clues(
    group, canonical, submitted, description,
):
    model = logic_grid.parse({
        "groups": "Card: A, B, C\nColour: Red, Blue, Green",
        "rules": "A is before B. B is before C.",
    })
    added = [{"kind": "paired", "a": 0, "b": 3, "text": "A is paired with Red"},
             {"kind": "paired", "a": 1, "b": 4, "text": "B is paired with Blue"}]
    assert len(logic_grid.check(model, [*model["rules"], *added])) == 1
    proof = {"method": "custom-grid-z3-and-exhaustive-permutations", "agree": True,
             "model": model, "query": {"target": 0, "answer_group": group},
             "authored_rules": model["rules"], "added_rules": added}
    result = feedback_for(quiz(canonical), proof, submitted)
    assert result["supported"] is True and result["correct"] is False
    assert description in result["message"]
    if group == 1:
        assert "A is paired with Red" in result["message"]
    assert feedback_for(quiz(canonical), proof, canonical)["supported"] is True


@pytest.mark.parametrize("topic,variation", [
    ("activities", "best-move"), ("activities", "pattern"),
    ("activities", "contradiction"), ("reasoning", "deduction"),
    ("reasoning", "bayesian"), ("reasoning", "planning"),
])
def test_generated_verified_models_support_each_choice(topic, variation):
    bundle = Generator().build(Request(topic, variation=variation, subject="ocean", seed=7))
    assert verify_bundle(bundle) == 1
    item, proof = bundle["items"][0], bundle["proofs"][0]
    for answer in item["choices"]:
        result = feedback_for(item, proof, answer)
        assert result["correct"] is (answer == item["correctAnswer"])
        assert result["supported"] is True, result
        assert answer in result["message"]


def test_default_animal_puzzle_coaches_every_option_including_none_of_these():
    bundle = Generator().build(Request("autopilot", "multiple-choice", "easy",
                                       subject="animals", count=1, seed=7))
    assert verify_bundle(bundle) == 1
    item, proof = bundle["items"][0], bundle["proofs"][0]
    assert item["choices"][0] == "None of these"
    for answer in item["choices"]:
        result = feedback_for(item, proof, answer)
        assert result["correct"] is (answer == item["correctAnswer"])
        assert result["supported"] is True, result
    message = feedback_for(item, proof, "None of these")["message"]
    assert "BEETLE in exactly one of positions 1, 2, 3" in message
    assert "All these answers are listed" in message
    assert "satisfies every clue" in message
    # The exhaustive-options argument must not be used when an answer is missing.
    partial = {**item, "choices": [c for c in item["choices"] if c != item["correctAnswer"]]}
    assert feedback_for(partial, proof, "None of these")["supported"] is False


def test_mismatched_claim_or_unrecognized_proof_does_not_produce_specific_claim(route_pair):
    _, proof = route_pair
    proof.update(claim="A", claim_holds=True)
    result = feedback_for(quiz("True", "true-false"), proof, "False")
    assert result["supported"] is False
    assert "cost" not in result["message"]
    proof["method"] = "unrecognized-future-method"
    assert feedback_for(quiz("B"), proof, "A")["supported"] is False


def test_crossword_and_wonder_are_not_graded_as_quiz_answers():
    for kind in ("crossword", "wonder"):
        result = feedback_for(quiz("anything", kind), {}, "anything")
        assert result["correct"] is False and result["supported"] is False


def entry_proof(groups, rules, added=""):
    model = logic_grid.parse({"groups": groups, "rules": rules})
    extra = logic_grid.parse({"groups": groups, "rules": added})["rules"]
    solutions = logic_grid.check(model, [*model["rules"], *extra])
    assert len(solutions) == 1
    return {"method": "custom-grid-z3-and-exhaustive-permutations", "agree": True,
            "model": model, "authored_rules": model["rules"], "added_rules": extra,
            "solution_table": logic_grid.table(model, solutions[0])}


@pytest.fixture
def ordered_grid_proof():
    return entry_proof("Card: A, B, C, D",
                       "A is before B. B is before C. C is before D.")


def test_grid_entries_blank_partial_and_complete_outcomes(ordered_grid_proof):
    before = copy.deepcopy(ordered_grid_proof)
    empty = grid_feedback(ordered_grid_proof, ["", "", "", ""])
    assert empty == {"correct": False, "complete": False, "consistent": True,
                     "message": "No entries yet. Continue by placing a value, then check again.",
                     "conflicts": []}
    partial = grid_feedback(ordered_grid_proof, [" Ａ ", "", "  ", "d"])
    assert not partial["correct"] and not partial["complete"] and partial["consistent"]
    assert partial["conflicts"] == []
    assert "Continue filling the 2 remaining cells" in partial["message"]
    complete = grid_feedback(ordered_grid_proof, ["A", "B", "C", "D"])
    assert complete["correct"] and complete["complete"] and complete["consistent"]
    assert complete["conflicts"] == [] and "satisfies every clue" in complete["message"]
    assert ordered_grid_proof == before


@pytest.mark.parametrize("entries", [None, {}, "ABCD", ("A", "B", "C", "D"),
                                    [], ["A"], [""] * 5, [None] * 4, [0] * 4,
                                    [True] * 4, [["A"]] * 4, [{}] * 4,
                                    ["missing", "", "", ""], ["<script>", "", "", ""]])
def test_grid_entries_reject_invalid_client_values(ordered_grid_proof, entries):
    with pytest.raises(ValueError, match="Grid|grid"):
        grid_feedback(ordered_grid_proof, entries)


@pytest.mark.parametrize("proof", [{}, {"agree": False}, {"agree": True, "method": "future"}])
def test_grid_entries_require_grid_proof_type(proof):
    with pytest.raises(ValueError, match="verified logic-grid proof"):
        grid_feedback(proof, [])


def test_grid_entries_duplicate_labels_highlight_the_shared_conflict(ordered_grid_proof):
    result = grid_feedback(ordered_grid_proof, [" A ", "a", "C", "D"])
    assert not result["correct"] and result["complete"] and not result["consistent"]
    assert result["conflicts"] == [{"cells": [0, 1], "kind": "duplicate", "clue_numbers": [],
                                    "message": result["message"]}]
    assert "positions 1, 2" in result["message"]
    assert "at least one of these entries must change" in result["message"]
    assert "Clue" not in result["message"]


def test_grid_entries_direct_clue_does_not_label_every_solution_mismatch(ordered_grid_proof):
    result = grid_feedback(ordered_grid_proof, ["B", "A", "C", "D"])
    assert not result["correct"] and not result["consistent"] and result["complete"]
    conflict = result["conflicts"][0]
    assert conflict["kind"] == "clue" and conflict["clue_numbers"] == [1]
    assert conflict["cells"] == [0]
    assert "B at position 1" in conflict["message"]
    assert "A is before B" in conflict["message"]
    assert "unique solution" not in conflict["message"]


def test_grid_entries_cumulative_conflict_names_the_clue_combination(ordered_grid_proof):
    result = grid_feedback(ordered_grid_proof, ["", "", "B", ""])
    conflict = result["conflicts"][0]
    assert conflict["kind"] == "combined" and conflict["clue_numbers"] == [1, 2, 3]
    assert conflict["cells"] == [2]
    assert "Clues 1–3 together" in conflict["message"]
    assert "Each clue separately allows these entries" in conflict["message"]
    rows = [row for row in logic_grid.worlds(4, 1) if row[1] == 3]
    assert all(any(logic_grid.holds(rule, row) for row in rows)
               for rule in ordered_grid_proof["authored_rules"])


def test_grid_entries_combined_partial_assignments_are_not_blame_for_one_cell(ordered_grid_proof):
    result = grid_feedback(ordered_grid_proof, ["", "A", "C", ""])
    conflict = result["conflicts"][0]
    assert conflict["kind"] == "combined" and conflict["clue_numbers"] == [1, 2]
    assert conflict["cells"] == [1, 2]
    assert "A at position 2; C at position 3" in conflict["message"]
    assert "Reconsider at least one highlighted entry" in conflict["message"]
    # Either entry alone works with the cited prefix; both together do not.
    rules = ordered_grid_proof["authored_rules"][:2]
    rows = logic_grid.survivors(ordered_grid_proof["model"], rules)
    assert any(row[0] == 2 for row in rows) and any(row[2] == 3 for row in rows)
    assert not any(row[0] == 2 and row[2] == 3 for row in rows)
    # No individual clue rules out the pair either.
    pair = [row for row in logic_grid.worlds(4, 1) if row[0] == 2 and row[2] == 3]
    assert all(any(logic_grid.holds(rule, row) for row in pair) for rule in rules)


def test_grid_entries_direct_pair_conflict_keeps_both_cells_and_uses_group_order():
    proof = entry_proof("Card: A, B, C\nColour: Red, Blue, Green",
                        "A is paired with Red. A is before B. B is before C.",
                        "B is paired with Blue.")
    result = grid_feedback(proof, ["", "Red", "A", "", "", ""])
    conflict = result["conflicts"][0]
    assert conflict["kind"] == "clue" and conflict["clue_numbers"] == [1]
    assert conflict["cells"] == [1, 2]
    assert "Red at position 1; A at position 2" in conflict["message"]
    rows = logic_grid.survivors(proof["model"], proof["authored_rules"][:1])
    assert any(row[0] == 2 for row in rows) and any(row[3] == 1 for row in rows)
    assert not any(row[0] == 2 and row[3] == 1 for row in rows)
    with pytest.raises(ValueError, match="cell 1 must use a value from Card"):
        grid_feedback(proof, ["Red", "", "", "", "", ""])


def test_grid_entries_added_rule_numbers_follow_authored_rules():
    proof = entry_proof("Card: A, B, C\nColour: Red, Blue, Green",
                        "A is before B. B is before C. A is paired with Red.",
                        "B is paired with Blue.")
    result = grid_feedback(proof, ["", "Blue", "B", "", "", ""])
    conflict = result["conflicts"][0]
    assert conflict["kind"] == "clue" and conflict["clue_numbers"] == [4]
    assert conflict["cells"] == [1, 2]
    assert "B is paired with Blue" in conflict["message"]


def test_grid_entries_largest_supported_grid_is_bounded_and_row_major():
    proof = entry_proof("Card: A, B, C, D\nColour: Red, Blue, Green, Pink\n"
                        "Drink: Tea, Coffee, Milk, Water",
                        "A is before B. B is before C. C is before D. "
                        "A is paired with Red. B is paired with Blue. C is paired with Green. "
                        "A is paired with Tea. B is paired with Coffee. C is paired with Milk.")
    entries = [row[group["name"]] for row in proof["solution_table"]
               for group in proof["model"]["groups"]]
    assert len(entries) == 12 and grid_feedback(proof, entries)["correct"]
    # Only the two drink placements together contradict clue 7.
    partial = [""] * 12
    partial[0], partial[5] = "A", "Tea"
    result = grid_feedback(proof, partial)
    assert result["conflicts"][0]["cells"] == [0, 5]
    assert result["conflicts"][0]["clue_numbers"] == [7]


@pytest.mark.parametrize("revision", [1, 4, 5])
def test_grid_entries_work_with_verified_legacy_and_current_bundles(revision):
    bundle = Generator().build(Request("logic-grid", grid=logic_grid.EXAMPLE, seed=7,
                                       engine_revision=revision))
    assert verify_bundle(bundle) == 1
    proof = bundle["proofs"][0]
    entries = [row[group["name"]] for row in proof["solution_table"]
               for group in proof["model"]["groups"]]
    assert grid_feedback(proof, entries)["correct"]
    entries[0] = ""
    result = grid_feedback(proof, entries)
    assert result["consistent"] and not result["correct"] and not result["complete"]
    assert result["conflicts"] == []
