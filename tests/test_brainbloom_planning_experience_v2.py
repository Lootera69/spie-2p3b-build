"""Revision-12 selection preserves hard gates and exposes its quality tradeoffs."""

from __future__ import annotations

import json
from copy import deepcopy
from random import Random

import pytest
from tools.benchmark_state_planning import committed_costs, initial, oracle, shortest

from spie.questions.brainbloom import planning_causal_paths as causal_paths
from spie.questions.brainbloom import planning_experience as previous
from spie.questions.brainbloom import planning_experience_v2 as experience
from spie.questions.brainbloom import state_planning as domain
from spie.questions.brainbloom import state_planning_variety as variety


def decision_range(model, graph):
    remaining = {state: shortest(model, graph, state)[0] for state in graph}
    counts = []

    def visit(state, count):
        if remaining[state] == 0:
            counts.append(count)
            return
        costs = [cost for cost in committed_costs(model, graph, state).values() if cost is not None]
        count += len(costs) >= 2 and len(set(costs)) >= 2
        for target in graph[state].values():
            if remaining[target] == remaining[state] - 1:
                visit(target, count)

    visit(initial(model), 0)
    return min(counts), max(counts)


@pytest.mark.parametrize("level", (1, 2, 3))
@pytest.mark.parametrize("profile", variety.PROFILES)
def test_every_profile_and_level_preserves_independently_replayed_targets(level, profile):
    model = experience.propose(
        list("ABCDEF")[:level + 3], level, Random(101), requested_profile=profile
    )
    report = experience.certify(model)
    old_report = previous.certify({**model, "experience_version": previous.VERSION})
    for field in ("dimensions", "rank", "solution", "decisions", "ablations", "strategy"):
        assert report[field] == old_report[field]
    expected = oracle(model)
    assert model["experience_version"] == experience.VERSION
    assert model["design_version"] == variety.VERSION
    assert model["strategy"] == profile
    assert report["version"] == experience.CERTIFICATE_VERSION
    assert report["meets_target"]
    assert model["answer_action"] == expected["optimal_first_actions"][0]
    assert model["solution"] == expected["solution"]
    assert model["best_steps"] == expected["best_steps"]
    assert decision_range(model, expected["graph"]) == (
        report["dimensions"]["minimum_meaningful_decisions"],
        report["dimensions"]["maximum_meaningful_decisions"],
    )
    assert report["dimensions"]["minimum_meaningful_decisions"] >= 2
    assert report["dimensions"]["causal_links"] >= 1
    assert report["causal_path_coverage"]["all_shortest_routes_linked"]
    for mechanic in domain.MECHANICS:
        variant = oracle(model, relaxed=mechanic)
        assert report["ablations"][mechanic] == {
            "best_steps": variant["best_steps"],
            "optimal_first_actions": variant["optimal_first_actions"],
        }
        assert (variant["best_steps"], variant["optimal_first_actions"]) != (
            expected["best_steps"], expected["optimal_first_actions"]
        )


def test_bounded_walk_is_preserved_and_reference_uses_eligible_pool():
    old = previous.propose(list("ABCDEF"), 3, Random(109), requested_profile="conserve-energy")
    model = experience.propose(list("ABCDEF"), 3, Random(109), requested_profile="conserve-energy")
    search = model["experience_search"]
    best = max(
        (row for row in search["comparisons"] if row["meets_target"]),
        key=lambda row: row["rank"],
    )
    assert best["rank"] == search["selection"]["lexicographic_rank"]
    assert all(
        best["dimensions"][key] == search["selection"]["lexicographic_dimensions"][key]
        for key in experience.TRADEOFF_DIMENSIONS
    )
    assert search["model_evaluations"] == 48
    fields = ("attempt", "origin", "physical_key", "dimensions", "rank")
    assert [tuple(row[key] for key in fields) for row in search["comparisons"]] == [
        tuple(row[key] for key in fields) for row in old["experience_search"]["comparisons"]
    ]
    assert search["selection"]["maximum_regret"] == experience.REGRET_LIMITS


def test_interventions_skip_irrelevant_committed_path_work(monkeypatch):
    model, _ = variety._foundation(list("ABCDE"), 2, "switch-first", Random(101))
    original = domain._analyse_graph
    calls = []

    def record(*args, **kwargs):
        if "initial" not in kwargs:
            calls.append(kwargs.get("committed", True))
        return original(*args, **kwargs)

    monkeypatch.setattr(domain, "_analyse_graph", record)
    _, graph, reason, count = experience._assess(model)
    assert reason is None
    assert graph
    assert count == 5
    assert calls == [True, False, False, False, False]


def comparison(attempt, structure, costs, *, role="route-a", topology="map-a", target=True):
    dimensions = dict(zip(experience.TRADEOFF_DIMENSIONS, costs, strict=True))
    return {
        "attempt": attempt,
        "structural_key": structure,
        "topology_key": topology,
        "role_sequence": [role],
        "dimensions": dimensions,
        "rank": [2, int(target), *(-cost for cost in costs)],
        "meets_target": target,
    }


def test_quality_limits_and_group_frontiers_preserve_variety_and_deduplicate():
    rows = [
        comparison(1, "a", (1, 2, 12, 5)),
        comparison(2, "b", (1, 2, 11, 6), role="route-b", topology="map-b"),
        comparison(3, "c", (3, 3, 13, 6)),
        comparison(4, "d", (1, 2, 12, 5), topology="map-d"),
        comparison(5, "a", (1, 2, 12, 5)),
        comparison(6, "f", (0, 0, 0, 0), target=False),
        comparison(7, "g", (1, 2, 12, 6)),
        comparison(8, "h", (1, 2, 12, 6), topology="map-h"),
        comparison(9, "i", (1, 3, 11, 5), topology="map-i"),
    ]
    selected = []
    for seed in range(101, 121):
        report = experience._selection(rows, seed)
        assert report["eligible_candidates"] == 8
        assert report["distinct_eligible_structures"] == 7
        assert report["quality_bounded_structures"] == 5
        assert report["frontier_attempts"] == [1, 2, 4, 8]
        assert report["frontier_role_sequences"] == 2
        assert report["frontier_topologies"] == 4
        assert all(
            value <= experience.REGRET_LIMITS[key]
            for key, value in report["selected_minus_lexicographic"].items()
        )
        selected.append(report["selected_attempt"])
    assert set(selected) == {1, 2, 4, 8}
    assert experience._selection([rows[5]], 101) is None


@pytest.fixture(scope="module")
def model():
    return experience.propose(list("ABCDE"), 2, Random(101), requested_profile="switch-first")


def test_selection_is_independently_replayable_and_reports_exact_tradeoffs(model):
    selection = experience.audit_selection(json.loads(json.dumps(model)))
    assert selection == model["experience_search"]["selection"]
    assert selection["selected_attempt"] in selection["frontier_attempts"]
    assert selection["selected_minus_lexicographic"] == {
        key: selection["selected_dimensions"][key] - selection["lexicographic_dimensions"][key]
        for key in experience.TRADEOFF_DIMENSIONS
    }
    assert all(
        value <= experience.REGRET_LIMITS[key]
        for key, value in selection["selected_minus_lexicographic"].items()
    )


def test_causal_coverage_failure_and_exhaustion_cannot_be_selected(model, monkeypatch):
    monkeypatch.setattr(
        causal_paths, "evaluate", lambda *args: {"all_shortest_routes_linked": False}
    )
    with pytest.raises(experience.ExperienceExhausted):
        experience.propose(list("ABCDE"), 2, Random(101), requested_profile="switch-first")
    with pytest.raises(ValueError, match="Every shortest"):
        experience.certify(model)

    def exhausted(*args):
        raise causal_paths.CausalCoverageExhausted("proof limit")

    monkeypatch.setattr(causal_paths, "evaluate", exhausted)
    with pytest.raises(experience.ExperienceExhausted):
        experience.propose(list("ABCDE"), 2, Random(101), requested_profile="switch-first")
    quality = experience._quality(model, domain._graph(model))
    assert quality["causal_coverage_status"] == "unknown"
    assert quality["all_shortest_routes_linked"] is None
    assert quality["meets_target"] is False
    with pytest.raises(ValueError, match="could not be certified"):
        experience.certify(model)


@pytest.mark.parametrize("field", ("dimensions", "structural_key", "role_sequence", "selection"))
def test_selection_audit_rejects_altered_provenance(model, field):
    altered = deepcopy(model)
    search = altered["experience_search"]
    if field == "selection":
        search["selection"]["selected_attempt"] = -1
    elif field == "dimensions":
        search["comparisons"][0][field]["rule_rows"] += 1
    elif field == "role_sequence":
        search["comparisons"][0][field] = ["invented"]
    else:
        search["comparisons"][0][field] = "invented"
    with pytest.raises(ValueError, match="evidence|selection"):
        experience.audit_selection(altered)


@pytest.mark.parametrize("change", (
    "target-as-int", "coverage-as-int", "limit-as-bool", "rows-as-float",
    "budget-as-bool", "budget-over-limit",
))
def test_selection_audit_rejects_type_changes_and_invalid_budget(model, change):
    altered = deepcopy(model)
    search = altered["experience_search"]
    row = next(row for row in search["comparisons"] if row["meets_target"])
    if change == "target-as-int":
        row["meets_target"] = 1
    elif change == "coverage-as-int":
        row["all_shortest_routes_linked"] = 1
    elif change == "limit-as-bool":
        search["selection"]["maximum_regret"]["trap_choices_on_optimal_episodes"] = False
    elif change == "rows-as-float":
        row["dimensions"]["rule_rows"] = float(row["dimensions"]["rule_rows"])
    else:
        search["budget"] = True if change == "budget-as-bool" else 49
    with pytest.raises(ValueError, match="evidence|selection"):
        experience.audit_selection(altered)


def test_final_certificate_ignores_saved_scores_and_uses_only_compiled_rules(model, monkeypatch):
    expected = experience.certify(model)
    altered = deepcopy(model)
    altered.update(answer_action="invented", best_steps=999, solution=["invented"])
    altered["experience_search"] = {"selected_rank": [999], "selection": "invented"}

    def forbidden(*args, **kwargs):
        raise AssertionError("Certification reused the proposal interpreter")

    for name in ("_graph", "_analyse_graph", "_successors", "solve"):
        monkeypatch.setattr(domain, name, forbidden)
    assert experience.certify(altered) == expected


def test_role_and_structure_grouping_survive_room_and_gate_relabeling(model):
    expected = previous.evaluate(model)
    role = experience._role_sequence(model, expected)
    shape, topology = domain.structural_key(model), experience._topology_key(model)
    for seed in range(101, 107):
        relabeled = deepcopy(model)
        variety._relabel(relabeled, Random(seed))
        assert experience._role_sequence(relabeled, previous.evaluate(relabeled)) == role
        assert domain.structural_key(relabeled) == shape
        assert experience._topology_key(relabeled) == topology


def test_seeded_selection_is_replayable_without_cross_request_state():
    old = previous.propose(list("ABCD"), 1, Random(101))
    first = experience.propose(list("ABCD"), 1, Random(101))
    experience.propose(list("ABCD"), 1, Random(102))
    second = experience.propose(list("ABCD"), 1, Random(101))
    assert first == second
    assert first["strategy"] == Random(101).choice(variety.PROFILES)
    assert previous.propose(list("ABCD"), 1, Random(101)) == old


@pytest.mark.parametrize("profile", variety.PROFILES)
def test_exhaustion_never_changes_profile_or_weakens_target(profile, monkeypatch):
    monkeypatch.setattr(experience, "_assess", lambda model: (None, None, "profile", 5))
    with pytest.raises(experience.ExperienceExhausted) as failure:
        experience.propose(list("ABCD"), 1, Random(101), requested_profile=profile, budget=7)
    assert failure.value.search["requested_profile"] == profile
    assert failure.value.search["target"] == experience.TARGET
    assert failure.value.search["model_evaluations"] == 7


@pytest.mark.parametrize("budget", (-1, True, 49, 1.5))
def test_invalid_budgets_are_rejected(budget):
    with pytest.raises(ValueError, match="budget"):
        experience.propose(list("ABCD"), 1, Random(101), budget=budget)


def test_zero_budget_preserves_requested_profile():
    with pytest.raises(experience.ExperienceExhausted) as failure:
        experience.propose(
            list("ABCD"), 1, Random(101), requested_profile="conserve-energy", budget=0
        )
    assert failure.value.search["requested_profile"] == "conserve-energy"
    assert failure.value.search["model_evaluations"] == 0
