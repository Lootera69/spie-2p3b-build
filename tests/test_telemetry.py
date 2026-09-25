"""Phase 5.4 tests, part 1: the synthetic player and its honestly-labeled telemetry.

These lock the three properties LEARNING depends on: byte-reproducibility (stable SHA-256 seeding,
never Python's salted ``hash``), honest provenance (every record is stamped synthetic with no
human-provenance field), and genuine distinctness from the difficulty evaluator (the player emits
hints/restarts/backtracks -- signals with no analogue in the structural formula -- and its effort
ordering is not a re-encoding of the static difficulty)."""

from __future__ import annotations

import hashlib

from spie import fingerprint, quality, telemetry
from spie.examples_src import BUILDERS, move

PUZZLES = [b() for b in BUILDERS]
CORPUS = fingerprint.corpus_fingerprints(PUZZLES)

# Substrings that would betray a record masquerading as (or contaminated by) real human data.
_HUMAN_MARKERS = ("human", "playtest", "real", "person")


def test_player_seed_is_stable_sha256_not_salted_hash():
    # The per-player seed is a process-independent SHA-256 digest of (id|base|index), so telemetry
    # is byte-reproducible across processes -- Python's salted hash() would break that.
    for pid in ("01_move", "07_hidden"):
        for i in (0, 1, 7):
            expected = int.from_bytes(hashlib.sha256(f"{pid}|0|{i}".encode()).digest()[:8], "big")
            assert telemetry._player_seed(pid, i, 0) == expected
    assert telemetry._player_seed("01_move", 0, 0) != telemetry._player_seed("01_move", 1, 0)
    assert telemetry._player_seed("01_move", 0, 0) != telemetry._player_seed("01_move", 0, 1)


def test_records_are_honestly_labeled_with_no_human_field():
    fields = set(telemetry.TelemetryRecord.__dataclass_fields__)
    assert "synthetic" in fields and "source" in fields
    for name in fields:
        assert not any(m in name for m in _HUMAN_MARKERS), name
    recs = telemetry.simulate_puzzle(move(), players=6, base_seed=0)
    assert recs and all(r.synthetic is True for r in recs)
    assert all(r.source == "strategy-solver-simulation" for r in recs)
    j = telemetry.record_to_json(recs[0])
    assert j["synthetic"] is True and j["source"] == "strategy-solver-simulation"
    assert not any(m in key for key in j for m in _HUMAN_MARKERS)


def test_telemetry_is_byte_reproducible_both_regimes():
    a = [telemetry.record_to_json(r) for r in telemetry.simulate_puzzle(move(), 8, 0)]
    b = [telemetry.record_to_json(r) for r in telemetry.simulate_puzzle(move(), 8, 0)]
    assert a == b
    o1 = telemetry.observe(move(), 8, 0)
    o2 = telemetry.observe(move(), 8, 0)
    assert telemetry.observed_to_json(o1) == telemetry.observed_to_json(o2)
    hidden = next(p for p in PUZZLES if p.initial_belief)
    h1 = [telemetry.record_to_json(r) for r in telemetry.simulate_puzzle(hidden, 8, 0)]
    h2 = [telemetry.record_to_json(r) for r in telemetry.simulate_puzzle(hidden, 8, 0)]
    assert h1 == h2
    # A strong plan never physically backtracks, so the hidden regime reports backtracks == 0.
    assert all(r.backtracks == 0 for r in telemetry.simulate_puzzle(hidden, 8, 0))


def test_effort_fold_and_lower_bound():
    for r in telemetry.simulate_puzzle(move(), players=8, base_seed=0):
        assert r.effort == r.steps + 2 * r.backtracks + 3 * r.hints_used + 8 * r.restarts
        assert r.effort >= r.steps  # every behavioural event weighs at least one step-equivalent


def test_easy_puzzle_is_mostly_solved():
    o = telemetry.observe(move(), players=12, base_seed=0)
    assert o.players == 12
    assert o.solved_fraction >= 0.5  # a trivial puzzle: the noisy population still mostly solves it
    assert o.mean_effort > 0.0


def test_player_is_a_distinct_process_behaviorally():
    # Hints, restarts, and backtracks are behavioural signals with NO analogue in the difficulty
    # formula; a genuinely distinct, noisier process must exhibit at least one across the corpus.
    obs = telemetry.collect(PUZZLES, players=10, base_seed=0)
    assert sum(o.mean_hints + o.mean_restarts + o.mean_backtracks for o in obs) > 0.0


def test_effort_ordering_is_not_a_reencoding_of_difficulty():
    # Correlated with, but not identical to, the static formula: an ordering inversion must exist
    # (the default structural difficulty only weakly predicts synthetic effort -- that gap is what
    # calibration closes).
    obs = {o.puzzle_id: o for o in telemetry.collect(PUZZLES, players=10, base_seed=0)}
    raw = {p.id: quality.descriptors(p, CORPUS).difficulty.raw for p in PUZZLES}
    ids = sorted(raw)
    inversion = any(
        raw[a] < raw[b] and obs[a].mean_effort >= obs[b].mean_effort for a in ids for b in ids
    )
    assert inversion

