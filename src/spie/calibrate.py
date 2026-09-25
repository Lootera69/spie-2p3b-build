"""Phase 5.4 -- LEARNING, part 2: recalibrating the difficulty evaluator on synthetic telemetry.

Gate G5 asks whether the machine metrics *predict* difficulty. This module answers it honestly:
it fits the structural difficulty formula's weights to maximise the rank correlation between the
predicted difficulty and the **observed** difficulty of the synthetic player population
(:mod:`spie.telemetry`), and reports how well the fitted formula generalises to *held-out* puzzles.

The predictor. Both difficulty regimes (:func:`spie.quality._difficulty` and its epistemic
analogue) fold the *same* six stored proxies with the same coefficients, so a single linear form
over a :class:`~spie.quality.Difficulty` reproduces the live ``raw`` exactly at the default weights
(a test asserts this)::

    raw = w_depth*depth + w_free*free_choices + w_branch*max(max_branching-1, 0)
        + w_trap*trap_density + w_spread*depth_spread + w_info*information_gain

Calibration searches the weight vector; :func:`predicted_raw` is that form, and
:data:`DEFAULT_WEIGHTS` are the live coefficients.

Honesty and anti-circularity. The thing calibrated is the *static structural formula*; the target
is a *noisy behavioural simulation* (a distinct process -- see :mod:`spie.telemetry`); they share
only the puzzle. The fit is therefore meaningful only if it **generalises**, so the puzzles are
split into train and held-out sets and both correlations are reported; G5 is the held-out
correlation clearing a documented :data:`G5_THRESHOLD`, *reported* -- never asserted into being.

No live mutation. Calibration produces an *artifact* (:class:`Calibration`): fitted weights plus
train/held-out correlations. It does **not** rewrite :mod:`spie.quality`'s coefficients, so the
corpus's bands, niches, and certificates are untouched. :func:`difficulty_calibrated` applies a
fitted weight vector on demand, for demonstration, kept off the default path.

The optimiser is deterministic (coordinate ascent over a fixed sorted grid, ties keeping the
incumbent) and the Spearman correlation is hand-rolled (Pearson on tie-averaged ranks), so a whole
calibration run is byte-reproducible -- the determinism discipline lifted to the learning loop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from . import fingerprint, quality, telemetry
from .examples_src import BUILDERS
from .ir import Puzzle
from .quality import Difficulty

# The six structural difficulty proxies, in the order the fold applies them. DEFAULT_WEIGHTS are
# the live coefficients in spie.quality (depth + 2*free + 1.5*(maxbranch-1) + 3*trap + 2*spread +
# info); predicted_raw at these weights reproduces Difficulty.raw exactly.
_FIELDS = ("depth", "free", "branch", "trap", "spread", "info")

# Candidate weight values for the coordinate search -- a fixed, sorted grid (so ties resolve to the
# smallest value, deterministically). Spans the live coefficients (0.5..4.0) plus 0.0 (drop a term).
_GRID = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
_PASSES = 4

# Gate G5: the held-out rank correlation a calibration must clear to count as "generalising".
# Documented and conservative; the *result* is reported either way (Calibration.generalizes).
G5_THRESHOLD = 0.3


@dataclass(frozen=True)
class DifficultyWeights:
    """The six coefficients of the difficulty fold (see the module docstring)."""

    depth: float
    free: float
    branch: float
    trap: float
    spread: float
    info: float


DEFAULT_WEIGHTS = DifficultyWeights(1.0, 2.0, 1.5, 3.0, 2.0, 1.0)


@dataclass(frozen=True)
class DataPoint:
    """One puzzle's calibration row: its structural difficulty proxies and the observed mean effort
    of the synthetic player population."""

    puzzle_id: str
    difficulty: Difficulty
    observed_effort: float


@dataclass(frozen=True)
class Calibration:
    """The calibration artifact: the fitted ``weights`` and the train / held-out Spearman
    correlations they achieve, alongside the baseline (default-weight) correlations for comparison.
    ``generalizes`` is the reported G5 verdict -- held-out correlation clearing :data:`G5_THRESHOLD`
    -- not an assertion. Nothing here mutates the live difficulty formula."""

    weights: DifficultyWeights
    train_rho: float
    holdout_rho: float
    baseline_train_rho: float
    baseline_holdout_rho: float
    threshold: float
    players: int
    base_seed: int
    train_ids: tuple[str, ...]
    holdout_ids: tuple[str, ...]

    @property
    def generalizes(self) -> bool:
        return self.holdout_rho >= self.threshold


# --- The predictor: the unified linear difficulty fold over the six stored proxies -----------


def predicted_raw(diff: Difficulty, w: DifficultyWeights) -> float:
    """The linear difficulty form (see the module docstring). At :data:`DEFAULT_WEIGHTS` this
    reproduces :attr:`spie.quality.Difficulty.raw` exactly for every corpus puzzle -- both regimes
    (:func:`spie.quality._difficulty` and its epistemic analogue) fold these same six stored
    proxies with these same coefficients -- which a test asserts. The ``max(max_branching-1, 0)``
    term matches the live fold (branching is only costly beyond a single forced choice)."""
    return (
        w.depth * diff.depth
        + w.free * diff.free_choices
        + w.branch * max(diff.max_branching - 1, 0)
        + w.trap * diff.trap_density
        + w.spread * diff.depth_spread
        + w.info * diff.information_gain
    )


def difficulty_calibrated(diff: Difficulty, w: DifficultyWeights) -> tuple[float, int]:
    """Apply a fitted weight vector on demand: the recomputed ``(raw, band)`` under ``w``. A
    demonstration helper kept deliberately off the default path -- calibration is an *artifact*, so
    the live corpus difficulty/bands are never rewritten (see the module docstring). The band cut
    (width 4, capped at 5) mirrors :func:`spie.quality._difficulty`'s banding."""
    raw = round(predicted_raw(diff, w), 6)
    band = 1 + min(4, int(raw // 4))
    return raw, band


# --- Spearman rank correlation, hand-rolled (Pearson on tie-averaged ranks) ------------------


def _ranks(xs: tuple[float, ...]) -> list[float]:
    """Tie-averaged 1-based ranks (ascending): tied values share the mean of the ranks they span,
    so the rank vector is a deterministic function of the values alone."""
    order = sorted(range(len(xs)), key=lambda i: (xs[i], i))
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # mean of 1-based ranks i+1 .. j+1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: tuple[float, ...], ys: tuple[float, ...]) -> float:
    """Spearman's rank correlation: Pearson's correlation of the tie-averaged ranks. Returns
    ``0.0`` when there are fewer than two points or either variable is constant (rank variance
    zero, so the coefficient is undefined -- reported as no correlation, never NaN). Rounded to six
    places for byte-reproducibility."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return 0.0
    rx = _ranks(xs)
    ry = _ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0.0 or vy <= 0.0:
        return 0.0
    return round(cov / math.sqrt(vx * vy), 6)


def _rho(data: tuple[DataPoint, ...], w: DifficultyWeights) -> float:
    """The Spearman correlation between predicted difficulty (under ``w``) and observed effort over
    ``data`` -- the objective the fit maximises and the number G5 reports."""
    pred = tuple(predicted_raw(d.difficulty, w) for d in data)
    obs = tuple(d.observed_effort for d in data)
    return spearman(pred, obs)


# --- Dataset assembly: structural proxies (predictor) vs synthetic effort (target) -----------


def build_dataset(
    puzzles: list[Puzzle],
    players: int = telemetry.DEFAULT_PLAYERS,
    base_seed: int = 0,
    corpus: object | None = None,
) -> tuple[DataPoint, ...]:
    """Assemble the calibration rows: for each puzzle, its structural
    :class:`~spie.quality.Difficulty` (the predictor's inputs) paired with the synthetic
    population's mean effort (the target). The novelty ``corpus`` fingerprint set is computed once
    and shared across :func:`spie.quality.descriptors` calls; the synthetic observed difficulty
    comes from :func:`spie.telemetry.collect`. Rows are sorted by puzzle id for determinism."""
    if corpus is None:
        corpus = fingerprint.corpus_fingerprints([b() for b in BUILDERS])
    observed = {o.puzzle_id: o for o in telemetry.collect(puzzles, players, base_seed)}
    rows = [
        DataPoint(
            puzzle_id=p.id,
            difficulty=quality.descriptors(p, corpus).difficulty,
            observed_effort=observed[p.id].mean_effort,
        )
        for p in puzzles
    ]
    return tuple(sorted(rows, key=lambda d: d.puzzle_id))


def split_dataset(
    data: tuple[DataPoint, ...],
) -> tuple[tuple[DataPoint, ...], tuple[DataPoint, ...]]:
    """Split the (id-sorted) rows into train and held-out sets. Every third row (indices 0, 3, 6,
    ...) is held out; the rest train. A deterministic, id-driven split -- so the honesty check
    (does the fit *generalise*?) is on puzzles the fit never saw, and the split is reproducible."""
    ordered = tuple(sorted(data, key=lambda d: d.puzzle_id))
    holdout = tuple(d for i, d in enumerate(ordered) if i % 3 == 0)
    train = tuple(d for i, d in enumerate(ordered) if i % 3 != 0)
    return train, holdout


def fit_weights(train: tuple[DataPoint, ...]) -> DifficultyWeights:
    """Fit the six weights by deterministic coordinate ascent: starting from
    :data:`DEFAULT_WEIGHTS`, sweep each field over :data:`_GRID` in turn (``_PASSES`` passes),
    keeping a candidate only on *strict* improvement of the train Spearman ``_rho`` (ties keep the
    incumbent, so the smallest grid value wins). No randomness, fixed sweep order -- the fit is a
    pure function of ``train`` and byte-reproducible."""
    best = DEFAULT_WEIGHTS
    best_rho = _rho(train, best)
    for _ in range(_PASSES):
        for field in _FIELDS:
            for value in _GRID:
                cand = replace(best, **{field: value})
                cand_rho = _rho(train, cand)
                if cand_rho > best_rho + 1e-12:
                    best, best_rho = cand, cand_rho
    return best


def calibrate(
    puzzles: list[Puzzle],
    players: int = telemetry.DEFAULT_PLAYERS,
    base_seed: int = 0,
    corpus: object | None = None,
) -> Calibration:
    """Run the whole calibration: build the dataset, split train/held-out, fit the weights on
    train, and report train and held-out Spearman correlations for both the fitted and the default
    (baseline) weights. ``generalizes`` (held-out rho vs :data:`G5_THRESHOLD`) is *reported*, never
    asserted. Produces only an artifact -- the live difficulty formula is untouched."""
    data = build_dataset(puzzles, players, base_seed, corpus)
    train, holdout = split_dataset(data)
    weights = fit_weights(train)
    return Calibration(
        weights=weights,
        train_rho=_rho(train, weights),
        holdout_rho=_rho(holdout, weights),
        baseline_train_rho=_rho(train, DEFAULT_WEIGHTS),
        baseline_holdout_rho=_rho(holdout, DEFAULT_WEIGHTS),
        threshold=G5_THRESHOLD,
        players=players,
        base_seed=base_seed,
        train_ids=tuple(d.puzzle_id for d in train),
        holdout_ids=tuple(d.puzzle_id for d in holdout),
    )


# --- Plain-data views (canonical, for the CLI artifact) --------------------------------------


def weights_to_json(w: DifficultyWeights) -> dict:
    """A plain-data view of a difficulty weight vector, in fold order."""
    return {name: getattr(w, name) for name in _FIELDS}


def calibration_to_json(c: Calibration) -> dict:
    """A plain-data view of a calibration artifact: the fitted weights, the train/held-out and
    baseline correlations, the reported G5 verdict, and the run's provenance (players, seed, and the
    exact train/held-out puzzle ids). Serialise with :func:`spie.serialize.dumps` for a
    byte-reproducible artifact."""
    return {
        "weights": weights_to_json(c.weights),
        "train_rho": c.train_rho,
        "holdout_rho": c.holdout_rho,
        "baseline_train_rho": c.baseline_train_rho,
        "baseline_holdout_rho": c.baseline_holdout_rho,
        "threshold": c.threshold,
        "generalizes": c.generalizes,
        "players": c.players,
        "base_seed": c.base_seed,
        "train_ids": list(c.train_ids),
        "holdout_ids": list(c.holdout_ids),
    }


__all__ = [
    "G5_THRESHOLD",
    "DifficultyWeights",
    "DEFAULT_WEIGHTS",
    "DataPoint",
    "Calibration",
    "predicted_raw",
    "difficulty_calibrated",
    "spearman",
    "build_dataset",
    "split_dataset",
    "fit_weights",
    "calibrate",
    "weights_to_json",
    "calibration_to_json",
]
