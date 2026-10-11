"""Guided repairs remain bounded, reproducible and subordinate to exact proofs."""

from __future__ import annotations

import copy
import random

import pytest

from spie.questions.brainbloom import planning_invention as invention
from spie.questions.brainbloom import planning_strategy, state_planning


@pytest.fixture(scope="module", params=(1, 2, 3))
def designed(request):
    level = request.param
    return invention.propose(list("ABCDEF")[:level + 3], level, random.Random(20), budget=1000)


def test_every_accepted_design_keeps_old_gates_and_proves_the_strategy(designed):
    proof = state_planning.check(designed)
    assert proof["agree"] and proof["smt"]["different_first_action"] == "unsat"
    assert len(proof["quality"]["ablations"]) == 4
    assert all(row["answer_changes"] or row["optimum_changes"]
               for row in proof["quality"]["ablations"].values())
    assert proof["strategy"] == planning_strategy.certify(designed)
    assert proof["strategy"]["minimum_extra_steps"] >= 1
    assert invention.strategy_status(designed, state_planning.solve(designed))["holds"]


def test_seeded_search_and_all_accounting_replay_exactly(designed):
    assert designed == invention.propose(designed["names"], designed["level"],
                                         random.Random(20), budget=1000)
    search = designed["search"]
    assert search["model_evaluations"] <= search["budget"] == 1000
    assert search["restarts"] + search["repairs_evaluated"] == search["model_evaluations"]
    assert sum(search["rejections"].values()) + 1 == search["model_evaluations"]
    assert search["graph_evaluations"] <= 5 * search["model_evaluations"]


def test_repair_history_reconstructs_failed_parents_and_accepted_rules(designed):
    history = designed["search"]["repair_history"]
    assert bool(history) == (designed["search"]["accepted_via"] == "repair")
    assert len(history) <= invention.MAX_REPAIR_DEPTH
    previous = None
    for step in history:
        parent, child = step["parent_model"], step["child_model"]
        before = copy.deepcopy(parent)
        assert invention.physical_key(parent) == step["parent"]
        assert invention.physical_key(child) == step["child"]
        assert invention.apply_edit(parent, step["edit"]) == child
        assert parent == before
        if previous is not None:
            assert step["parent"] == previous
        previous = step["child"]
        old = invention.evaluate(parent)
        new = invention.evaluate(child)
        assert old["reason"] is not None  # The accepted plan was rescued from a real rejection.
        assert list(old["score"]) == step["before_score"]
        assert list(new["score"]) == step["after_score"]
    if history:
        assert previous == invention.physical_key(designed)
        assert invention.evaluate(history[-1]["child_model"])["reason"] is None


@pytest.mark.parametrize("mode", ("guided", "restart"))
def test_exhaustion_counts_every_attempt_and_never_returns_a_partial_model(monkeypatch, mode):
    calls = []

    def no_model(*args):
        calls.append(1)
        return None

    monkeypatch.setattr(state_planning, "_sample", no_model)
    with pytest.raises(invention.InventionExhausted) as failed:
        invention.propose(list("ABCD"), 1, random.Random(0), mode=mode, budget=9)
    search = failed.value.search
    assert len(calls) == search["model_evaluations"] == search["restarts"] == 9
    assert search["graph_evaluations"] == search["repairs_evaluated"] == 0
    assert search["rejections"]["shape"] == 9
    assert search["accepted_via"] is None and search["repair_history"] == []
    assert isinstance(failed.value, state_planning.ProposalExhausted)


def test_restart_control_never_uses_repairs(monkeypatch):
    def forbidden(*args):
        pytest.fail("Restart control attempted a guided repair")

    monkeypatch.setattr(invention, "_repairs", forbidden)
    model = invention.propose(list("ABCD"), 1, random.Random(0), mode="restart", budget=1000)
    assert model["search"]["repairs_evaluated"] == 0
    assert model["search"]["accepted_via"] == "restart"
    state_planning.check(model)


def test_forged_search_diagnostic_cannot_bypass_independent_strategy_check(monkeypatch):
    # Revision 7's medium seed 0 satisfies all old gates, but its cheapest
    # zero-energy switch is the winning first action, so it fails this strategy.
    old = state_planning.propose(list("ABCDE"), 2, random.Random(0))
    assert not invention.strategy_status(old, state_planning.solve(old))["holds"]
    monkeypatch.setattr(state_planning, "_sample", lambda *args: copy.deepcopy(old))
    original = invention.strategy_status

    def forged(*args):
        return {**original(*args), "holds": True}

    monkeypatch.setattr(invention, "strategy_status", forged)
    candidate = invention.propose(list("ABCDE"), 2, random.Random(0), budget=1)
    with pytest.raises(ValueError, match="invest more"):
        state_planning.check(candidate)


def test_domain_failures_propagate_without_consuming_a_retry_budget(monkeypatch):
    model = state_planning._sample(list("ABCD"), 1, random.Random(0))
    assert model is not None
    monkeypatch.setattr(state_planning, "_sample", lambda *args: model)

    def broken(*args, **kwargs):
        raise RuntimeError("Domain solver failed")

    monkeypatch.setattr(state_planning, "solve", broken)
    with pytest.raises(RuntimeError, match="Domain solver failed"):
        invention.propose(list("ABCD"), 1, random.Random(0))


@pytest.mark.parametrize("options", [
    {"mode": "unknown"}, {"budget": True}, {"budget": -1}, {"budget": 2001},
])
def test_search_configuration_is_bounded_and_explicit(options):
    with pytest.raises(ValueError):
        invention.propose(list("ABCD"), 1, random.Random(0), **options)


@pytest.mark.parametrize("field,value", [
    ("design_version", "future"), ("strategy", "unknown"), ("strategy", None),
])
def test_unknown_design_metadata_is_rejected(designed, field, value):
    broken = copy.deepcopy(designed)
    broken[field] = value
    with pytest.raises(ValueError, match="Unsupported planning invention"):
        state_planning.check(broken)
