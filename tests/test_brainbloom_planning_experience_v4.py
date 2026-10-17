"""Revision14 decision selection, physical correctness and replay isolation."""

from copy import deepcopy
from random import Random

import pytest
from tools.benchmark_state_planning import oracle

from spie.questions.brainbloom import planning_experience_v4 as experience
from spie.questions.brainbloom import state_planning_variety as variety


@pytest.mark.parametrize("level", (1, 2, 3))
@pytest.mark.parametrize("profile", variety.PROFILES)
def test_raw_solution_and_selection_replay_across_all_families(level, profile):
    model = experience.propose(list("ABCDEF")[:level + 3], level, Random(1426),
                               requested_profile=profile)
    raw = oracle(model)
    assert model["solution"] == raw["solution"]
    assert model["answer_action"] == raw["optimal_first_actions"][0]
    report = experience.certify(model)
    assert report["decision_judgment"]["minimum_meaningful_decisions"] >= 2
    assert report["causal_path_coverage"]["all_shortest_routes_linked"]
    assert experience.audit_selection(model) == model["experience_search"]["selection"]


def test_cache_history_and_external_mutation_cannot_change_generation():
    def generate():
        return experience.propose(list("ABCDE"), 2, Random(1427),
                                  requested_profile="recharge-first")

    experience._foundation_analysis.cache_clear()
    first = generate()
    expected = deepcopy(first)
    first["routes"][0][2] = 999
    first["experience_search"]["comparisons"].clear()
    assert generate() == expected
    experience._foundation_analysis.cache_clear()
    assert generate() == expected


def test_selection_rejects_forged_policy_and_prior_evidence():
    model = experience.propose(list("ABCD"), 1, Random(1428))
    changed = deepcopy(model)
    changed["experience_search"]["selection"]["prior_version"] = "forged"
    with pytest.raises(ValueError, match="selection disagrees"):
        experience.audit_selection(changed)
    changed = deepcopy(model)
    row = next(r for r in changed["experience_search"]["comparisons"] if r["meets_target"])
    row["decision_judgment"]["policy_checks"][0]["success_probability"] = "9/8"
    with pytest.raises(ValueError, match="candidate evidence disagrees"):
        experience.audit_selection(changed)


def test_zero_budget_does_not_return_an_uncertified_foundation():
    with pytest.raises(experience.ExperienceExhausted):
        experience.propose(list("ABCD"), 1, Random(1429), budget=0)
