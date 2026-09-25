"""Phase 5.4 tests, part 2: recalibrating the difficulty evaluator on synthetic telemetry.

These lock the calibration's honesty guarantees: the linear predictor reproduces the *live*
difficulty formula at the default weights (so the fit targets the real thing), the hand-rolled
Spearman behaves, the fit never underperforms the default baseline and on this corpus generalises
to held-out puzzles (Gate G5, reported), the run is byte-reproducible, and calibration is an
artifact that leaves the live difficulty formula untouched."""

from __future__ import annotations

from spie import calibrate, fingerprint, quality
from spie.calibrate import DEFAULT_WEIGHTS, predicted_raw, spearman
from spie.examples_src import BUILDERS
from spie.serialize import dumps

PUZZLES = [b() for b in BUILDERS]
CORPUS = fingerprint.corpus_fingerprints(PUZZLES)


def test_predictor_reproduces_live_raw_at_default_weights():
    # The unified linear fold at DEFAULT_WEIGHTS equals the live Difficulty.raw for every corpus
    # puzzle, across BOTH the fully-observable and the epistemic regime -- so the fit is over the
    # real formula, not a lookalike.
    for p in PUZZLES:
        d = quality.descriptors(p, CORPUS).difficulty
        assert round(predicted_raw(d, DEFAULT_WEIGHTS), 6) == d.raw


def test_difficulty_calibrated_matches_live_at_default():
    for p in PUZZLES:
        d = quality.descriptors(p, CORPUS).difficulty
        assert calibrate.difficulty_calibrated(d, DEFAULT_WEIGHTS) == (d.raw, d.band)


def test_ranks_tie_averaging():
    assert calibrate._ranks((10.0, 20.0, 30.0)) == [1.0, 2.0, 3.0]
    assert calibrate._ranks((10.0, 10.0, 30.0)) == [1.5, 1.5, 3.0]
    assert calibrate._ranks((5.0, 5.0, 5.0)) == [2.0, 2.0, 2.0]


def test_spearman_units():
    assert spearman((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)) == 1.0
    assert spearman((1.0, 2.0, 3.0), (3.0, 2.0, 1.0)) == -1.0
    assert spearman((1.0, 2.0, 3.0), (1.0, 4.0, 9.0)) == 1.0  # rank-based: any monotone map -> 1
    assert spearman((1.0, 1.0, 1.0), (1.0, 2.0, 3.0)) == 0.0  # a constant column -> 0, never NaN
    assert spearman((1.0,), (1.0,)) == 0.0  # fewer than two points -> 0
    assert spearman((1.0, 1.0, 2.0), (5.0, 5.0, 9.0)) == 1.0  # aligned ties


def test_split_is_disjoint_and_every_third_held_out():
    data = calibrate.build_dataset(PUZZLES, players=6, base_seed=0, corpus=CORPUS)
    train, holdout = calibrate.split_dataset(data)
    tids = {d.puzzle_id for d in train}
    hids = {d.puzzle_id for d in holdout}
    assert tids.isdisjoint(hids)
    assert tids | hids == {d.puzzle_id for d in data}
    ordered = sorted(d.puzzle_id for d in data)
    assert [d.puzzle_id for d in holdout] == ordered[::3]


def test_fit_never_underperforms_baseline_and_generalizes():
    c = calibrate.calibrate(PUZZLES, players=8, base_seed=0, corpus=CORPUS)
    # Coordinate ascent from the default weights, accepting only strict improvements, so the fitted
    # train correlation can never fall below the default baseline -- and on this corpus it strictly
    # improves and the held-out correlation clears G5_THRESHOLD (a *reported* verdict).
    assert c.train_rho >= c.baseline_train_rho
    assert c.train_rho > c.baseline_train_rho
    assert c.generalizes
    assert c.holdout_rho >= c.threshold
    assert c.holdout_rho > c.baseline_holdout_rho
    assert -1.0 <= c.holdout_rho <= 1.0
    assert set(c.train_ids).isdisjoint(c.holdout_ids)


def test_calibration_is_byte_reproducible():
    a = calibrate.calibrate(PUZZLES, players=8, base_seed=0, corpus=CORPUS)
    b = calibrate.calibrate(PUZZLES, players=8, base_seed=0, corpus=CORPUS)
    assert dumps(calibrate.calibration_to_json(a)) == dumps(calibrate.calibration_to_json(b))


def test_calibration_does_not_mutate_the_live_difficulty_formula():
    before = {p.id: quality.descriptors(p, CORPUS).difficulty.raw for p in PUZZLES}
    calibrate.calibrate(PUZZLES, players=6, base_seed=0, corpus=CORPUS)
    after = {p.id: quality.descriptors(p, CORPUS).difficulty.raw for p in PUZZLES}
    assert before == after

