"""Regressions for the player-visible shortcuts found in the creator audit."""

import copy
import hashlib
import json
import random
import re
from itertools import combinations, permutations

import pytest

from spie.questions.brainbloom import Request, contradiction, deduction, patterns, smart_activities
from spie.questions.brainbloom.activity_policy import PATTERN_TRUE_FALSE_UNAVAILABLE
from spie.questions.brainbloom.feedback import feedback_for
from spie.questions.brainbloom.service import Generator, verify_bundle

FORMATS = ("multiple-choice", "true-false", "type-answer", "riddle")


def surviving_rules(model, indices):
    return [i for i, (a, b, c) in enumerate(model["rules"])
            if all(a * model["examples"][j][0] ** 2 + b * model["examples"][j][0] + c
                   == model["examples"][j][1] for j in indices)]


def eligible_rule_answers(rules, level):
    """Independently find all winners permitted by one unchanged printed rule list."""
    values = {x: [a * x * x + b * x + c for a, b, c in rules] for x in range(6)}
    eligible = set()
    for inputs in combinations(range(5), level):
        if any(not 0 <= y <= 120 for x in inputs for y in values[x]):
            continue
        if not any(x not in inputs and len(set(values[x])) == 4
                   and all(0 <= y <= 120 for y in values[x]) for x in range(6)):
            continue
        for winner in range(4):
            alternative = {"rules": rules, "examples": [[x, values[x][winner]] for x in inputs]}
            if surviving_rules(alternative, range(level)) != [winner]:
                continue
            if all(len(surviving_rules(alternative, subset)) >= 2
                   for subset in combinations(range(level), level - 1)):
                eligible.add(winner)
    return eligible


def displayed_relation(text, names):
    """Evaluate the printed relation without the generator's clue predicates."""
    index = names.index
    if match := re.fullmatch(r"(\w+) is left of (\w+)\.", text):
        a, b = map(index, match.groups())
        return lambda row: row[a] < row[b]
    if match := re.fullmatch(r"(\w+) is next to (\w+)\.", text):
        a, b = map(index, match.groups())
        return lambda row: abs(row[a] - row[b]) == 1
    if match := re.fullmatch(r"(\w+) and (\w+) differ by (\d+) positions\.", text):
        a, b, distance = index(match[1]), index(match[2]), int(match[3])
        return lambda row: abs(row[a] - row[b]) == distance
    if match := re.fullmatch(r"(\w+) is not at position (\d+)\.", text):
        a, position = index(match[1]), int(match[2]) - 1
        return lambda row: row[a] != position
    if match := re.fullmatch(r"(\w+) lies between (\w+) and (\w+); gaps allowed\.", text):
        a, b, c = map(index, match.groups())
        return lambda row: min(row[b], row[c]) < row[a] < max(row[b], row[c])
    raise AssertionError(f"Unrecognized displayed relation: {text}")


def check_displayed_contradiction(item, quality):
    question = item["question"]
    names = re.search(r"left to right: ([^\n]+)\.", question)[1].split(", ")
    printed_base = re.findall(r"^(\d+)\. (.+)$", question, re.MULTILINE)
    assert [int(number) for number, _ in printed_base] == list(range(1, len(printed_base) + 1))
    base = [displayed_relation(text, names) for _, text in printed_base]
    printed_options = re.findall(r"^(?:Test )?Statement ([A-D]): (.+)$", question, re.MULTILINE)
    assert all(text not in [line for _, line in printed_base] for _, text in printed_options)
    options = [displayed_relation(text, names) for _, text in printed_options]
    rows = list(permutations(range(len(names))))
    if item["type"] == "true-false":
        assert len(options) == 1

        def answer(row):
            return str(not options[0](row))
    else:
        assert [label for label, _ in printed_options] == list("ABCD")
        rows = [row for row in rows if sum(not option(row) for option in options) == 1]

        def answer(row):
            return next(f"Statement {label}" for (label, _), option
                        in zip(printed_options, options, strict=True) if not option(row))

        assert {answer(row) for row in rows} == {f"Statement {label}" for label in "ABCD"}
    correct = item["correctAnswer"]
    assert {answer(row) for row in rows if all(clue(row) for clue in base)} == {correct}
    minimum = next(count for count in range(len(base) + 1)
                   for subset in combinations(base, count)
                   if {answer(row) for row in rows if all(clue(row) for clue in subset)}
                   == {correct})
    assert minimum == quality["minimum_supporting_clues"]


def check_displayed_pattern(item, quality):
    question = item["question"]
    rules = []
    for expression in re.findall(r"^Rule [A-D] \([^\n]+\): (.+)$", question, re.MULTILINE):
        coefficients = [0, 0, 0]
        term = r"([+−]?)\s*(\d+)(?: × (input²|input))?"
        assert not re.sub(term, "", expression).strip()
        for sign, number, variable in re.findall(term, expression):
            coefficients[{"input²": 0, "input": 1, "": 2}[variable]] += (
                (-1 if sign == "−" else 1) * int(number))
        rules.append(coefficients)
    assert len(rules) == 4
    observations = [tuple(map(int, pair)) for pair in re.findall(
        r": input (\d+) → output (\d+)$", question, re.MULTILINE)]

    def matches(indices):
        return [i for i, (a, b, c) in enumerate(rules)
                if all(a * observations[j][0] ** 2 + b * observations[j][0] + c
                       == observations[j][1] for j in indices)]

    surviving = matches(range(len(observations)))
    minimum = next(count for count in range(len(observations) + 1)
                   for indices in combinations(range(len(observations)), count)
                   if matches(indices) == surviving)
    assert minimum == quality["minimum_supporting_examples"]
    if item["type"] == "true-false":
        assert len(surviving) <= 1
        assert str(len(surviving) == 1) == item["correctAnswer"]
    else:
        assert len(surviving) == 1
        query = int(re.search(r"What output does it give for input (\d+)\?", question)[1])
        outputs = [a * query**2 + b * query + c for a, b, c in rules]
        assert str(outputs[surviving[0]]) == item["correctAnswer"]
        assert len(set(outputs)) == 4
        if item["type"] == "multiple-choice":
            assert set(item["choices"]) == set(map(str, outputs))


@pytest.mark.parametrize("level", (1, 2, 3))
@pytest.mark.parametrize("seed", (0, 1, 7, 23, 91))
def test_novel_contradiction_options_need_combined_clues_even_with_the_choice_promise(level, seed):
    model = contradiction.propose([f"Card{i}" for i in range(level + 3)], level,
                                  random.Random(seed), engine_revision=9)
    proof = contradiction.check(model)
    base = [deduction.Clue(**row) for row in model["clues"]]
    options = [deduction.Clue(**row) for row in model["options"]]
    assert not set(base) & set(options)
    assert len({frozenset((c.a, c.b)) for c in options}) == 4
    rows = list(permutations(range(level + 3)))
    task_rows = [row for row in rows if sum(not deduction.holds(c, row) for c in options) == 1]
    # No choice is impossible just from the text of the other three options.
    assert {next(i for i, c in enumerate(options) if not deduction.holds(c, row))
            for row in task_rows} == set(range(4))
    required = level + 1
    for indices in combinations(range(len(base)), required - 1):
        remaining = [row for row in rows if all(deduction.holds(base[i], row) for i in indices)]
        for option in options:
            assert {deduction.holds(option, row) for row in remaining} == {True, False}
        remaining_task = [row for row in task_rows
                          if all(deduction.holds(base[i], row) for i in indices)]
        answers = {next(i for i, c in enumerate(options) if not deduction.holds(c, row))
                   for row in remaining_task}
        assert len(answers) > 1
    assert proof["quality"]["minimum_supporting_clues"] >= required
    assert max(proof["quality"]["option_minimum_support"]) - min(
        proof["quality"]["option_minimum_support"]) <= 1


def test_new_contradiction_checker_rejects_the_old_copied_option_shortcut():
    model = contradiction.propose([f"Card{i}" for i in range(6)], 3, random.Random(7))
    model.update(design_version=contradiction.VERSION, level=3)
    with pytest.raises(RuntimeError, match="novel"):
        contradiction.check(model)


@pytest.mark.parametrize("level", (1, 2, 3))
def test_pattern_support_is_checked_across_seeds(level):
    for seed in range(20):
        model = patterns.propose([f"Card{i}" for i in range(level + 3)], level,
                                 random.Random(seed), engine_revision=9)
        proof = patterns.check(model)
        matches = surviving_rules(model, range(level))
        assert matches == [model["answer_index"]]
        assert proof["quality"]["minimum_supporting_examples"] == level
        assert eligible_rule_answers(model["rules"], level) == set(range(4))
        assert proof["quality"]["eligible_rule_indices"] == list(range(4))
        for indices in combinations(range(level), level - 1):
            remaining = surviving_rules(model, indices)
            assert len(remaining) >= 2
        if level > 1:
            assert all(len(surviving_rules(model, [i])) >= 2 for i in range(level))
        shown_inputs = [model["query"], *[x for x, _ in model["examples"]]]
        assert all(0 <= a * x * x + b * x + c <= 120
                   for a, b, c in model["rules"] for x in shown_inputs)


@pytest.mark.parametrize("difficulty", ("easy", "medium", "hard"))
def test_new_pattern_true_false_is_unavailable_instead_of_leaking_consistency(difficulty):
    level = ("easy", "medium", "hard").index(difficulty) + 1
    with pytest.raises(ValueError) as raw_error:
        patterns.propose([f"Card{i}" for i in range(level + 3)], level, random.Random(7),
                         engine_revision=9, qtype="true-false")
    assert str(raw_error.value) == PATTERN_TRUE_FALSE_UNAVAILABLE
    with pytest.raises(ValueError) as request_error:
        Request("activities", "true-false", difficulty, variation="pattern", engine_revision=9)
    assert str(request_error.value) == PATTERN_TRUE_FALSE_UNAVAILABLE


def test_new_pattern_checker_rejects_many_rows_with_only_one_useful_observation():
    model = {"design_version": patterns.VERSION, "mode": "prediction", "level": 3,
             "names": [f"Card{i}" for i in range(6)], "rules": [[a, 0, 0] for a in range(1, 5)],
             "examples": [[1, 1], [2, 4], [3, 9]], "query": 4, "answer_index": 0,
             "answer": 16, "consistent": True}
    with pytest.raises(RuntimeError, match="fewer observations"):
        patterns.check(model)


def test_new_pattern_checker_rejects_a_rule_list_with_a_privileged_winner():
    # The earlier repair made only the middle slope eligible for two-row support.
    # Its observations were necessary, but its rule-list construction leaked the winner.
    model = {"design_version": patterns.VERSION, "mode": "prediction", "level": 2,
             "names": [f"Card{i}" for i in range(5)],
             "rules": [[0, 2, 5], [0, 3, 5], [0, 3, 3], [0, 1, 5]],
             "examples": [[0, 5], [2, 9]], "query": 3, "answer_index": 0,
             "answer": 11, "consistent": True}
    assert eligible_rule_answers(model["rules"], 2) != set(range(4))
    with pytest.raises(RuntimeError, match="Every listed rule must be eligible"):
        patterns.check(model)


def test_pattern_checker_rejects_a_wrong_output_or_the_abandoned_consistency_mode():
    model = patterns.propose([f"Card{i}" for i in range(6)], 3, random.Random(7), engine_revision=9)
    changed = copy.deepcopy(model)
    changed["answer"] += 1
    with pytest.raises(RuntimeError, match="query"):
        patterns.check(changed)
    changed = copy.deepcopy(model)
    changed["mode"] = "consistency"
    changed["consistent"] = False
    with pytest.raises(RuntimeError, match="Invalid finite-pattern-v2"):
        patterns.check(changed)


@pytest.mark.parametrize("activity,qtype", [
    (activity, qtype) for activity in ("contradiction", "pattern") for qtype in FORMATS
    if (activity, qtype) != ("pattern", "true-false")
])
@pytest.mark.parametrize("difficulty", ("easy", "medium", "hard"))
@pytest.mark.parametrize("seed", (7, 23, 91))
def test_new_activity_formats_replay_with_claim_specific_support_and_feedback(
    activity, qtype, difficulty, seed,
):
    bundle = Generator().build(Request("activities", qtype, difficulty, subject="space, ocean",
                                       variation=activity, topic_mode="combined", seed=seed,
                                       engine_revision=9))
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1
    item, proof = bundle["items"][0], bundle["proofs"][0]
    level = ("easy", "medium", "hard").index(difficulty) + 1
    support_field = ("minimum_supporting_clues" if activity == "contradiction"
                     else "minimum_supporting_examples")
    assert proof["quality"][support_field] >= level + (activity == "contradiction")
    if activity == "contradiction":
        check_displayed_contradiction(item, proof["quality"])
        if qtype != "true-false":
            assert item["question"].endswith(
                "Which statement (A, B, C or D) is impossible together with the base clues?")
            assert item["correctExplanation"] == proof["steps"][proof["model"]["answer_index"]]
    else:
        check_displayed_pattern(item, proof["quality"])
    if qtype == "true-false":
        assert "Test these statements" not in item["question"]
        assert item["question"].count("Test Statement") == 1
        assert "single displayed" in proof["quality"]["scope"]
        for answer in ("True", "False"):
            feedback = feedback_for(item, proof, answer)
            assert feedback["supported"] is True
            assert feedback["correct"] is (answer == item["correctAnswer"])
    else:
        assert feedback_for(item, proof, item["correctAnswer"])["supported"] is True


@pytest.mark.parametrize("module,expected", [
    (contradiction, "f4d847838e62b8825353f74b0d18f8c90d8801074ce1543c9baf9e755cc2dafd"),
    (patterns, "1be5ab46cdaa1930387a73657f314a4089b7a8ec2a31fb4003efc2631b28552d"),
])
def test_revision_eight_seed_models_remain_identical_to_the_audited_engine(module, expected):
    # Frozen from HEAD before this repair, independently compared with its
    # propose/check/render functions. This protects saved request regeneration.
    models = [module.propose([f"Card{i}" for i in range(level + 3)], level, random.Random(seed),
                             engine_revision=8)
              for level in (1, 2, 3) for seed in (7, 23, 91)]
    encoded = json.dumps(models, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == expected
    assert all(module.check(model)["agree"] for model in models)


@pytest.mark.parametrize("revision", range(1, 9))
def test_every_legacy_revision_preserves_complete_activity_items_and_proofs(revision):
    # Canonical item/proof bytes compared directly against the audited HEAD's
    # smart_activities, contradiction and patterns implementations before freezing.
    expected = {
        1: "e8ca1a92fa566c278e2614909991526587aa2c7d1010dd4204dd46e084a4ab41",
        2: "bacbc191dcaf0c95ff9f8d11c383a318ba1ed81700b043e8f586a0d28a5d05d1",
        4: "bc8133d66c80691364a8a26fc32221c239febf13f7f65260fb20b628db4fc538",
    }[1 if revision == 1 else 2 if revision < 4 else 4]
    words = [f"CARD{i}" for i in range(12)]
    context = {"label": "fictional cards", "entries": [{"word": word} for word in words],
               "topics": [{"anchor": "CARD0", "words": words}]}
    candidates = []
    for activity in ("contradiction", "pattern"):
        for qtype in FORMATS:
            for difficulty in ("easy", "medium", "hard"):
                for seed in (7, 23, 91):
                    request = Request("activities", qtype, difficulty, variation=activity,
                                      engine_revision=revision)
                    if revision == 1 and activity == "pattern" and qtype == "riddle":
                        # This format was not supported by the revision-one route.
                        with pytest.raises(ValueError) as exc:
                            smart_activities.candidate(request, random.Random(seed), context, seed)
                        candidates.append({"refusal": str(exc.value)})
                    else:
                        candidates.append(smart_activities.candidate(
                            request, random.Random(seed), context, seed))
    encoded = json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == expected


@pytest.mark.parametrize("qtype", FORMATS)
def test_new_activity_auto_routes_to_a_core_deduction_with_replay(qtype):
    bundle = Generator().build(Request("activities", qtype, variation="auto", subject="space",
                                       engine_revision=9))
    proof = bundle["proofs"][0]
    assert proof["reasoning_style"] == "deduction"
    assert proof["word_bank"] == proof["model"]["names"]
    assert verify_bundle(bundle) == 1
