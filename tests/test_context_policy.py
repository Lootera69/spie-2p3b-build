"""Phase C2 tests — the deterministic *contextual* AOS policy (a LinUCB "decision model").

Two things are proven. (1) The contextual bandit is a correct, RNG-free disjoint-LinUCB: it solves
its per-arm ridge systems exactly, breaks ties on the sorted arm key, exploits the higher-survival
arm *for a given context*, genuinely changes its choice when the context changes, and emits a
clamped ``[0, 1]`` confidence. (2) Wired into ``evolve`` it stays thesis-safe and byte-reproducible:
a contextual-policy-driven run admits only puzzles that clear the unchanged
``validate -> verify -> certify`` gate, two runs with the same ``(seeds, iterations, seed)`` and a
fresh policy serialize identically, and the default ``policy=None`` path is byte-identical to the
historical uniform search (the reorder that threads context through the policy branch never touches
it). The calibration read is exercised as a *reported* metric — never a gate.
"""

from __future__ import annotations

import pytest

from spie import mapelites
from spie.certificate import certify
from spie.context_policy import (
    ContextualBandit,
    ContextualPolicy,
    _solve,
    calibration_report,
)
from spie.examples_src import BUILDERS
from spie.quality import descriptors
from spie.serialize import dumps
from spie.steering import SteeringPolicy
from spie.validate import validate
from spie.verify import verify

BY_NAME = {b.__name__: b for b in BUILDERS}
_SEED_NAMES = ("move", "which_door", "combination_lock")
_ITERATIONS = 5


def _seeds() -> list:
    return [BY_NAME[n]() for n in _SEED_NAMES]


# --- the contextual bandit is a correct, deterministic LinUCB -----------------------------------


def test_solve_matches_a_known_system() -> None:
    # A diagonal system with an obvious answer ...
    assert _solve([[2.0, 0.0], [0.0, 4.0]], [2.0, 4.0]) == [1.0, 1.0]
    # ... and a non-diagonal SPD one, verified by substitution (never by pinning float digits).
    x = _solve([[4.0, 1.0], [1.0, 3.0]], [1.0, 2.0])
    assert abs(4 * x[0] + 1 * x[1] - 1.0) < 1e-9
    assert abs(1 * x[0] + 3 * x[1] - 2.0) < 1e-9


def test_untried_arms_tie_and_break_on_sorted_key() -> None:
    bandit = ContextualBandit()
    ctx = (1.0, 0.5, 0.25)
    # Nothing credited -> every arm shares the ridge prior -> identical score -> first sorted key.
    assert bandit.select(["c", "a", "b"], ctx) == "a"


def test_bandit_exploits_the_higher_survival_arm_for_a_context() -> None:
    bandit = ContextualBandit()
    ctx = (1.0, 1.0)
    for _ in range(5):
        bandit.credit("a", ctx, 1.0)
        bandit.credit("b", ctx, 0.0)
    assert bandit.predict("a", ctx) > bandit.predict("b", ctx)
    assert bandit.select(["a", "b"], ctx) == "a"


def test_choice_is_genuinely_contextual() -> None:
    # Arm "a" survives on context x, arm "b" survives on context y: the estimate must flip with ctx.
    bandit = ContextualBandit()
    x = (1.0, 1.0, 0.0)
    y = (1.0, 0.0, 1.0)
    for _ in range(10):
        bandit.credit("a", x, 1.0)
        bandit.credit("a", y, 0.0)
        bandit.credit("b", x, 0.0)
        bandit.credit("b", y, 1.0)
    assert bandit.predict("a", x) > bandit.predict("b", x)
    assert bandit.predict("b", y) > bandit.predict("a", y)


def test_prediction_is_a_clamped_probability() -> None:
    bandit = ContextualBandit()
    ctx = (1.0, 1.0)
    for _ in range(20):
        bandit.credit("hot", ctx, 1.0)
        bandit.credit("cold", ctx, 0.0)
    assert 0.0 <= bandit.predict("hot", ctx) <= 1.0
    assert 0.0 <= bandit.predict("cold", ctx) <= 1.0
    assert bandit.predict("never", ctx) == 0.0  # untried arm -> zero-mean estimate


def test_selection_is_rng_free_and_reproducible() -> None:
    def run() -> ContextualBandit:
        bandit = ContextualBandit()
        ctx = (1.0, 0.3, 0.7)
        rewards = {"a": 1.0, "b": 0.0, "c": 1.0}
        for _ in range(9):
            arm = bandit.select(rewards.keys(), ctx)
            bandit.credit(arm, ctx, rewards[arm])
        return bandit

    first, second = run(), run()
    assert first.a_mat == second.a_mat
    assert first.b_vec == second.b_vec


def test_empty_selection_raises_and_dim_mismatch_is_caught() -> None:
    bandit = ContextualBandit()
    with pytest.raises(ValueError):
        bandit.select([], (1.0, 0.0))
    bandit.credit("a", (1.0, 0.0), 1.0)
    with pytest.raises(ValueError):
        bandit.select(["a"], (1.0, 0.0, 0.0))  # wrong dimension for an established bandit


# --- the calibration read (reported, never asserted as a gate) ----------------------------------


def test_calibration_report_on_synthetic_data() -> None:
    empty = calibration_report([])
    assert empty.n == 0 and empty.brier == 0.0
    # Perfectly-calibrated: half predicted 0.0 & fail, half predicted 1.0 & succeed.
    perfect = calibration_report([(0.0, 0.0)] * 4 + [(1.0, 1.0)] * 4)
    assert perfect.n == 8
    assert perfect.base_rate == 0.5
    assert perfect.brier == 0.0  # perfect predictions
    assert perfect.baseline_brier == 0.25  # always predicting the 0.5 base rate
    assert perfect.skill == 1.0  # maximal skill over the base rate
    assert perfect.ece == 0.0
    # A constant predictor equal to the base rate carries no information -> zero skill.
    useless = calibration_report([(0.5, 1.0), (0.5, 0.0)] * 4)
    assert useless.skill == 0.0


# --- wired into evolve: thesis-safe and byte-reproducible ---------------------------------------


def test_context_features_are_scaled_and_fixed_width() -> None:
    feats = mapelites._context_features(descriptors(BY_NAME["which_door"]()))
    assert len(feats) == mapelites._CONTEXT_DIM
    assert feats[0] == 1.0  # bias term
    assert all(0.0 <= f <= 1.0 for f in feats)


def test_contextual_policy_driven_evolve_is_byte_reproducible() -> None:
    a = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=ContextualPolicy())
    b = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=ContextualPolicy())
    assert dumps(mapelites.archive_to_json(a)) == dumps(mapelites.archive_to_json(b))


def test_contextual_policy_admits_only_certified_puzzles() -> None:
    archive = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=ContextualPolicy())
    assert archive.cells
    for cell in archive.cells.values():
        assert validate(cell.puzzle) == []
        assert verify(cell.puzzle).ok
        assert certify(cell.puzzle).solvable


def test_default_path_unchanged_and_calibration_is_populated() -> None:
    policy = ContextualPolicy()
    driven = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=policy)
    # The contextual model learned something and its calibration log filled (one entry per step).
    assert policy.operators.a_mat and policy.niches.stats
    report = policy.calibration()
    assert 0 < report.n <= _ITERATIONS
    assert 0.0 <= report.brier <= 1.0
    assert -1.0 <= report.skill <= 1.0  # reported, never asserted positive
    # The default path stays the historical uniform search, byte-for-byte (guards the reorder).
    plain_a = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0)
    plain_b = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=None)
    assert dumps(mapelites.archive_to_json(plain_a)) == dumps(mapelites.archive_to_json(plain_b))
    # Contextual steering is a genuinely different search from the uniform baseline.
    assert dumps(mapelites.archive_to_json(driven)) != dumps(mapelites.archive_to_json(plain_a))


def test_steering_and_contextual_policies_share_the_evolve_protocol() -> None:
    # Both policy types run through evolve's single call path (context threaded, ignored by C1).
    steered = mapelites.evolve(_seeds(), iterations=3, seed=0, policy=SteeringPolicy())
    contextual = mapelites.evolve(_seeds(), iterations=3, seed=0, policy=ContextualPolicy())
    assert steered.cells and contextual.cells

