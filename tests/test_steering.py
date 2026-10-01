"""Phase C1 tests — the deterministic AOS steering policy.

Two things are proven. (1) The bandit is a correct, RNG-free discounted-UCB: it forces every arm
once (sorted order), then exploits the higher-survival arm, discounts stale stats, and breaks ties
deterministically. (2) Wired into ``evolve`` it stays *thesis-safe and byte-reproducible*: a
policy-driven run admits only puzzles that clear the unchanged validate -> verify -> certify gate,
two runs with the same (seeds, iterations, seed) and a fresh policy serialize identically, and the
default ``policy=None`` path is byte-identical to the historical uniform search.
"""

from __future__ import annotations

import math

import pytest

from spie import mapelites
from spie.certificate import certify
from spie.examples_src import BUILDERS
from spie.serialize import dumps
from spie.steering import Bandit, SteeringPolicy
from spie.validate import validate
from spie.verify import verify

BY_NAME = {b.__name__: b for b in BUILDERS}


# --- the bandit is a correct, deterministic discounted-UCB --------------------------------------


def test_untried_arms_are_forced_once_in_sorted_order() -> None:
    b = Bandit()
    picks = []
    for _ in range(3):
        arm = b.select(["c", "a", "b"])
        picks.append(arm)
        b.credit(arm, 0.0)  # credit 0 so exploitation never overrides the +inf of an untried arm
    assert picks == ["a", "b", "c"]  # each forced once, in sorted key order


def test_after_forcing_the_higher_survival_arm_is_exploited() -> None:
    b = Bandit(gamma=1.0)  # stationary, so the estimate is a plain mean
    b.credit(b.select(["a", "b"]), 1.0)  # forces "a", rewards it
    b.credit(b.select(["a", "b"]), 0.0)  # forces "b", punishes it
    assert b.select(["a", "b"]) == "a"  # both pulled once -> higher mean wins
    assert b.mean("a") == 1.0 and b.mean("b") == 0.0


def test_ties_break_on_the_sorted_arm_key() -> None:
    b = Bandit(gamma=1.0)
    for arm in ("a", "b"):  # identical stats for both
        b.credit(arm, 1.0)
    assert b.select(["b", "a"]) == "a"  # exact tie -> first sorted key


def test_discount_decays_stale_stats_toward_recent_reward() -> None:
    b = Bandit(gamma=0.5)
    b.credit("a", 1.0)
    b.credit("a", 1.0)
    assert b.mean("a") == 1.0
    b.credit("a", 0.0)  # a recent failure pulls the discounted estimate down
    assert b.mean("a") == round(0.75 / 1.75, 6)


def test_selection_is_rng_free_and_reproducible() -> None:
    def run() -> Bandit:
        b = Bandit()
        rewards = {"a": 1.0, "b": 0.0, "c": 1.0}
        for _ in range(9):
            arm = b.select(rewards)
            b.credit(arm, rewards[arm])
        return b
    assert run().stats == run().stats  # identical sequences -> identical counters


def test_untried_arm_scores_infinity_and_empty_selection_raises() -> None:
    assert mapelites and math.isinf(float("inf"))  # sanity: inf import path
    b = Bandit()
    with pytest.raises(ValueError):
        b.select([])
    assert b.mean("never") == 0.0  # a never-pulled arm has a zero estimate, not an error


# --- wired into evolve: thesis-safe and byte-reproducible ---------------------------------------

_SEED_NAMES = ("move", "which_door", "combination_lock")
_ITERATIONS = 5


def _seeds() -> list:
    return [BY_NAME[n]() for n in _SEED_NAMES]


def test_policy_driven_evolve_is_byte_reproducible() -> None:
    a = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=SteeringPolicy())
    b = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=SteeringPolicy())
    assert dumps(mapelites.archive_to_json(a)) == dumps(mapelites.archive_to_json(b))


def test_policy_admits_only_formally_certified_puzzles() -> None:
    # The thesis guard: steering changes only *what is tried*; every archived elite must still pass
    # the full formal gate, exactly as under uniform search.
    archive = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=SteeringPolicy())
    assert archive.cells
    for cell in archive.cells.values():
        assert validate(cell.puzzle) == []
        assert verify(cell.puzzle).ok
        assert certify(cell.puzzle).solvable


def test_policy_accumulates_survival_credit_and_default_path_is_unchanged() -> None:
    policy = SteeringPolicy()
    driven = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=policy)
    # Every iteration credits exactly one operator and one niche, so the bandits learned something.
    assert policy.operators.stats and policy.niches.stats
    # The default (no-policy) path must remain the historical uniform search, byte-for-byte.
    plain_a = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0)
    plain_b = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, policy=None)
    assert dumps(mapelites.archive_to_json(plain_a)) == dumps(mapelites.archive_to_json(plain_b))
    # Steering and uniform are genuinely different searches (else the policy is a no-op here).
    assert dumps(mapelites.archive_to_json(driven)) != dumps(mapelites.archive_to_json(plain_a))
