"""Revision13 proposes distinct dependencies without relaxing planning gates."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from random import Random

import pytest
from tools.benchmark_state_planning import committed_costs, initial, oracle, shortest

from spie.questions.brainbloom import planning_causal_paths as causal_paths
from spie.questions.brainbloom import planning_experience_v2 as previous
from spie.questions.brainbloom import planning_experience_v3 as experience
from spie.questions.brainbloom import planning_foundations_v3 as foundations
from spie.questions.brainbloom import state_planning as domain
from spie.questions.brainbloom import state_planning_variety as variety


def minimum_decisions(model, graph):
    remaining = {state: shortest(model, graph, state)[0] for state in graph}

    def count(state):
        if not remaining[state]:
            return 0
        costs = [
            value for value in committed_costs(model, graph, state).values() if value is not None
        ]
        meaningful = len(costs) >= 2 and len(set(costs)) >= 2
        return meaningful + min(
            count(target)
            for target in graph[state].values()
            if remaining[target] == remaining[state] - 1
        )

    return count(initial(model))


@pytest.mark.parametrize("level", (1, 2, 3))
@pytest.mark.parametrize("profile", variety.PROFILES)
def test_new_populations_preserve_independently_checked_decisions_and_mechanics(level, profile):
    model = experience.propose(
        list("ABCDEF")[: level + 3], level, Random(101), requested_profile=profile
    )
    expected = oracle(model)
    report = experience.certify(model)
    assert model["strategy"] == profile
    assert model["experience_version"] == experience.VERSION
    assert report["version"] == experience.CERTIFICATE_VERSION
    assert model["solution"] == expected["solution"]
    assert model["answer_action"] == expected["optimal_first_actions"][0]
    assert model["best_steps"] == expected["best_steps"]
    assert minimum_decisions(model, expected["graph"]) >= 2
    assert report["causal_path_coverage"]["all_shortest_routes_linked"]
    for mechanic in domain.MECHANICS:
        relaxed = oracle(model, relaxed=mechanic)
        assert report["ablations"][mechanic] == {
            "best_steps": relaxed["best_steps"],
            "optimal_first_actions": relaxed["optimal_first_actions"],
        }
        assert (relaxed["best_steps"], relaxed["optimal_first_actions"]) != (
            expected["best_steps"],
            expected["optimal_first_actions"],
        )
    old_report = previous.certify({**model, "experience_version": previous.VERSION})
    for field in (
        "dimensions",
        "rank",
        "solution",
        "decisions",
        "ablations",
        "strategy",
        "causal_path_coverage",
    ):
        assert report[field] == old_report[field]


@pytest.fixture(scope="module")
def model():
    return experience.propose(list("ABCDE"), 2, Random(103), requested_profile="switch-first")


def test_every_foundation_family_is_physically_distinct_and_meets_the_unchanged_target():
    support = Counter()
    for (level, profile), groups in foundations.FAMILIES.items():
        assert 1 <= len(groups) < experience.PROPOSAL_BUDGET
        all_indices = [index for group in groups for index in group]
        assert sorted(all_indices) == list(range(len(foundations.FOUNDATIONS[(level, profile)])))
        family_roles = []
        structures = set()
        for group in groups:
            roles = set()
            for index in group:
                candidate = experience._foundation_at(
                    list("ABCDEF")[: level + 3], level, profile, index
                )
                candidate["experience_version"] = experience.VERSION
                report = experience.certify(candidate)
                roles.add(tuple(experience._role_sequence(candidate, report)))
                structure = domain.structural_key(candidate)
                assert structure not in structures
                structures.add(structure)
                assert report["causal_path_coverage"]["all_shortest_routes_linked"]
            assert len(roles) == 1
            family_roles.extend(roles)
            support.update(roles)
        assert len(set(family_roles)) == len(groups)
    assert sum(len(groups) > 1 for groups in foundations.FAMILIES.values()) >= 10
    assert dict(support) == foundations.ROLE_FREQUENCIES


def test_role_population_and_selection_evidence_preserve_budget_and_caps(model):
    search = model["experience_search"]
    assert search["budget"] == search["model_evaluations"] == 48
    assert search["foundation_version"] == foundations.VERSION
    assert len(search["foundation_order"]) == len(foundations.FAMILIES[(2, "switch-first")])
    rows = search["comparisons"]
    records = {row["attempt"]: row for row in rows}
    for row in rows:
        if row["origin"] == "foundation":
            assert row["parent_attempt"] is None
        else:
            assert row["parent_attempt"] < row["attempt"]
            assert row["parent_attempt"] in records
    selection = experience.audit_selection(json.loads(json.dumps(model)))
    assert selection == search["selection"]
    assert selection["frontier_role_sequences"] >= 2
    assert selection["maximum_regret"] == previous.REGRET_LIMITS
    assert all(
        value <= previous.REGRET_LIMITS[key]
        for key, value in selection["selected_minus_lexicographic"].items()
    )
    weights = selection["role_draw_weights"]
    assert len({row["family_support"] * row["integer_weight"] for row in weights}) == 1
    assert all(
        row["family_support"] == foundations.ROLE_FREQUENCIES.get(tuple(row["role_sequence"]), 1)
        for row in weights
    )


def test_genuine_edits_do_not_mutate_the_parent_or_only_relabel_it(model):
    original = deepcopy(model)
    changed = []
    for seed in range(101, 141):
        candidate = experience._mutate(model, Random(seed))
        assert candidate != model
        assert variety._physical_key(candidate) != variety._physical_key(model)
        changed.append(domain.structural_key(candidate))
    assert model == original
    assert len(set(changed)) > 20


def test_saved_replay_is_order_independent_and_old_generation_is_unchanged():
    original_foundations = deepcopy(foundations.FOUNDATIONS)
    old = previous.propose(list("ABCD"), 1, Random(104))
    first = experience.propose(list("ABCD"), 1, Random(104))
    original_first = deepcopy(first)
    experience.propose(list("ABCDEF"), 3, Random(105))
    second = experience.propose(list("ABCD"), 1, Random(104))
    assert first == second
    assert first == original_first
    assert foundations.FOUNDATIONS == original_foundations
    assert first["strategy"] == Random(104).choice(variety.PROFILES)
    assert old == previous.propose(list("ABCD"), 1, Random(104))


def test_final_certificate_uses_only_freshly_compiled_physical_rules(model, monkeypatch):
    expected = experience.certify(model)
    altered = deepcopy(model)
    altered.update(answer_action="invented", best_steps=999, solution=["invented"])
    altered["experience_search"] = {"selection": "invented", "foundation_version": "invented"}

    def forbidden(*args, **kwargs):
        raise AssertionError("Final certification reused proposal interpretation")

    for name in ("_graph", "_analyse_graph", "_successors", "solve"):
        monkeypatch.setattr(domain, name, forbidden)
    assert experience.certify(altered) == expected


@pytest.mark.parametrize(
    "field", ("dimensions", "role_sequence", "selection", "coverage", "weights")
)
def test_selection_audit_rejects_false_quality_claims(model, field):
    altered = deepcopy(model)
    search = altered["experience_search"]
    row = search["comparisons"][0]
    if field == "dimensions":
        row["dimensions"]["trap_choices_on_optimal_episodes"] += 1
    elif field == "role_sequence":
        row["role_sequence"] = ["invented-role"]
    elif field == "coverage":
        row["all_shortest_routes_linked"] = 1
    elif field == "weights":
        search["selection"]["role_draw_weights"][0]["integer_weight"] += 1
    else:
        search["selection"]["maximum_regret"]["maximum_forced_steps"] = 1
    with pytest.raises(ValueError, match="evidence|selection"):
        experience.audit_selection(altered)


@pytest.mark.parametrize("coverage", (False, None))
def test_false_or_unknown_causal_coverage_cannot_pass(model, monkeypatch, coverage):
    def exhausted(*args):
        if coverage is False:
            return {"all_shortest_routes_linked": False}
        raise causal_paths.CausalCoverageExhausted("test proof budget")

    monkeypatch.setattr(causal_paths, "evaluate", exhausted)
    with pytest.raises(experience.ExperienceExhausted):
        experience.propose(list("ABCD"), 1, Random(101), requested_profile="switch-first")
    message = "could not be certified" if coverage is None else "Every shortest"
    with pytest.raises(ValueError, match=message):
        experience.certify(model)


def test_failed_foundations_and_edits_never_escape_the_requested_budget(monkeypatch):
    monkeypatch.setattr(experience, "_assess", lambda model: (None, None, "profile", 5))
    with pytest.raises(experience.ExperienceExhausted) as failure:
        experience.propose(list("ABCD"), 1, Random(101), requested_profile="switch-first", budget=7)
    assert failure.value.search["requested_profile"] == "switch-first"
    assert failure.value.search["model_evaluations"] == 7
    assert failure.value.search["target"] == previous.TARGET


@pytest.mark.parametrize("budget", (-1, True, 49, 1.5))
def test_invalid_budgets_fail_closed(budget):
    with pytest.raises(ValueError, match="budget"):
        experience.propose(list("ABCD"), 1, Random(101), budget=budget)


def test_zero_budget_preserves_explicit_profile():
    with pytest.raises(experience.ExperienceExhausted) as failure:
        experience.propose(
            list("ABCD"), 1, Random(101), requested_profile="conserve-energy", budget=0
        )
    assert failure.value.search["requested_profile"] == "conserve-energy"
    assert failure.value.search["model_evaluations"] == 0
