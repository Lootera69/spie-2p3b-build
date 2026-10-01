"""Phase C2 — deterministic, dependency-free *contextual* Adaptive Operator Selection.

Where Phase C1's :mod:`spie.steering` bandit chooses an operator from context-free survival counts,
this module chooses one *conditioned on the parent elite's quality features* — the "decision model"
shape the roadmap's learning stage settles on (state in -> best operator + calibrated confidence
out), realised with the canonical open technique (disjoint **LinUCB**, Li et al. 2010) and nothing
heavier. No neural net, no third-party library: per-arm ridge regression over a small feature
vector, in pure ``math``.

**Thesis-safe by construction, exactly as C1.** The policy decides only *what to try*; every child
it proposes still clears the unchanged ``validate -> verify -> certify`` gate before it can occupy a
cell, and the reward is *derived from* that gate's verdict. The calibrated probability it emits is a
*reported* estimate of survival, never consulted for acceptance — the formal solvers remain the sole
authority (roadmap stage 8: learning "recalibrates search policies", never proof or acceptance).

**Determinism is preserved.** Selection is a pure ``argmax`` of LinUCB scores rounded to 6 dp (the
:mod:`spie.steering` / :func:`spie.mapelites.fitness_of` convention) with sorted-arm-key tie-breaks,
so it never touches the run's ``random.Random`` and a contextual-policy-driven ``evolve`` is as
byte-reproducible as the uniform one. The per-arm linear systems are solved by a fixed partial-pivot
Gaussian elimination (deterministic pivot order), and the ridge prior keeps every per-arm matrix
symmetric positive-definite, hence invertible.

**Calibration is measured, never asserted** (mirroring the Phase 5.4 G5 discipline).
:class:`CalibrationReport` reports the Brier score of the confidences the policy emitted for the
operators it actually chose against a base-rate baseline (a Brier skill score) plus a reliability
table and its expected calibration error — an honest read on whether the confidence carries
information, not a gate that could ever weaken correctness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .steering import Bandit

_ALPHA = 1.0  # LinUCB exploration weight on the confidence radius sqrt(xᵀ A⁻¹ x)
_RIDGE = 1.0  # ridge prior A0 = ridge*I: keeps each per-arm matrix SPD (invertible) and every
# untried arm tied, so the first pick falls to the sorted-key winner (deterministic).
_ROUND = 6  # decimal places; must match steering._ROUND and mapelites.fitness_of

def _identity(dim: int, scale: float) -> list[list[float]]:
    """The ``dim``×``dim`` matrix ``scale*I`` as nested lists."""
    return [[scale if i == j else 0.0 for j in range(dim)] for i in range(dim)]


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve ``matrix @ x == rhs`` for a symmetric positive-definite ``matrix`` by Gauss-Jordan
    elimination with partial pivoting. ``matrix`` is copied (never mutated). The pivot in each
    column is the row of largest magnitude, ties broken to the lowest row index, so the elimination
    order — and thus every bit of the result — is a deterministic function of the inputs."""
    dim = len(rhs)
    aug = [list(matrix[i]) + [rhs[i]] for i in range(dim)]
    for col in range(dim):
        pivot = max(range(col, dim), key=lambda r, c=col: (abs(aug[r][c]), -r))
        if aug[pivot][col] == 0.0:  # singular; the ridge prior makes this unreachable in practice
            continue
        aug[col], aug[pivot] = aug[pivot], aug[col]
        inv = 1.0 / aug[col][col]
        for j in range(col, dim + 1):
            aug[col][j] *= inv
        for r in range(dim):
            if r != col and aug[r][col] != 0.0:
                factor = aug[r][col]
                for j in range(col, dim + 1):
                    aug[r][j] -= factor * aug[col][j]
    return [aug[i][dim] for i in range(dim)]


@dataclass
class ContextualBandit:
    """A disjoint-LinUCB bandit over hashable, sortable arm keys and a fixed-length real feature
    vector. Per arm it keeps ``A = ridge*I + Σ x xᵀ`` and ``b = Σ r x``; the ridge estimate is
    ``θ = A⁻¹ b`` and the score is ``θ·x + alpha*sqrt(xᵀ A⁻¹ x)`` (exploit + confidence radius).
    The feature dimension is inferred from the first context seen and then fixed. No RNG — selection
    is an ``argmax`` with sorted-key tie-breaking; scores round to :data:`_ROUND` dp so equal scores
    compare equal (untried arms share the ridge prior and therefore always tie)."""

    alpha: float = _ALPHA
    ridge: float = _RIDGE
    dim: int | None = None
    a_mat: dict[object, list[list[float]]] = field(default_factory=dict)
    b_vec: dict[object, list[float]] = field(default_factory=dict)

    def _ensure_dim(self, context) -> None:
        d = len(context)
        if self.dim is None:
            self.dim = d
        elif d != self.dim:
            raise ValueError(f"context has dimension {d}, expected {self.dim}")

    def _params(self, arm):
        """The stored ``(A, b)`` for ``arm``, or a fresh *unstored* ``(ridge*I, 0)`` prior — reads
        never create state, so scoring or predicting an untried arm is side-effect free."""
        if arm in self.a_mat:
            return self.a_mat[arm], self.b_vec[arm]
        return _identity(self.dim, self.ridge), [0.0] * self.dim

    def _score(self, arm, context) -> float:
        a_mat, b_vec = self._params(arm)
        theta = _solve(a_mat, b_vec)
        mean = math.fsum(theta[i] * context[i] for i in range(self.dim))
        z = _solve(a_mat, list(context))
        var = math.fsum(context[i] * z[i] for i in range(self.dim))
        bonus = self.alpha * math.sqrt(var) if var > 0.0 else 0.0
        return round(mean + bonus, _ROUND)

    def select(self, arms, context):
        """Return the arm maximizing the LinUCB score under ``context``, scanning ``arms`` in sorted
        order so the first of any (rounded) tie wins deterministically. ``ValueError`` on empty."""
        self._ensure_dim(context)
        keys = sorted(arms)
        if not keys:
            raise ValueError("cannot select from an empty arm set")
        best, best_u = keys[0], -math.inf
        for key in keys:
            u = self._score(key, context)
            if u > best_u:  # strict > keeps the first (sorted) arm on exact ties
                best, best_u = key, u
        return best

    def credit(self, arm, context, reward: float) -> None:
        """Fold one observed ``reward`` at ``context`` into ``arm``'s ridge stats
        (``A += x xᵀ``, ``b += reward x``)."""
        self._ensure_dim(context)
        if arm not in self.a_mat:
            self.a_mat[arm] = _identity(self.dim, self.ridge)
            self.b_vec[arm] = [0.0] * self.dim
        a_mat, b_vec = self.a_mat[arm], self.b_vec[arm]
        for i in range(self.dim):
            xi = context[i]
            b_vec[i] += reward * xi
            row = a_mat[i]
            for j in range(self.dim):
                row[j] += xi * context[j]

    def predict(self, arm, context) -> float:
        """The calibrated survival estimate ``clamp(θ·x, 0, 1)`` for ``arm`` at ``context`` — the
        confidence the policy reports, never consulted for acceptance."""
        self._ensure_dim(context)
        a_mat, b_vec = self._params(arm)
        theta = _solve(a_mat, b_vec)
        p = math.fsum(theta[i] * context[i] for i in range(self.dim))
        return round(min(1.0, max(0.0, p)), _ROUND)


@dataclass
class ContextualPolicy:
    """The learned proposer :func:`spie.mapelites.evolve` consults when steering contextually: a
    context-free discounted-UCB :class:`~spie.steering.Bandit` over parent niches (which niche to
    expand is not a function of a not-yet-chosen parent's features), paired with a
    :class:`ContextualBandit` over operator names conditioned on the parent elite's quality
    features. Carried across ``evolve`` calls it accumulates survival history; ``log`` records, per
    credited step, the ``(confidence, survived)`` pair for the operator actually chosen, from which
    :meth:`calibration` builds an honest reliability read. It matches
    :class:`~spie.steering.SteeringPolicy`'s ``choose_niche`` / ``choose_operator`` / ``reward``
    protocol (the extra ``context`` being the only difference), so ``evolve`` drives either through
    one code path."""

    niches: Bandit = field(default_factory=Bandit)
    operators: ContextualBandit = field(default_factory=ContextualBandit)
    log: list[tuple[float, float]] = field(default_factory=list)

    def choose_niche(self, niches):
        """Pick which occupied niche to expand (context-free discounted-UCB, as Phase C1)."""
        return self.niches.select(niches)

    def choose_operator(self, operator_names, context):
        """Pick which mutation operator (by ``__name__``) to apply, conditioned on the parent's
        ``context`` feature vector."""
        return self.operators.select(operator_names, context)

    def reward(self, niche, operator_name: str, survived: float, context) -> None:
        """Credit the parent niche and the ``(context, operator)`` pair with the child's survival,
        logging the pre-update confidence the operator carried for this context against the outcome
        (so calibration reflects what the model believed at decision time)."""
        self.niches.credit(niche, survived)
        self.log.append((self.operators.predict(operator_name, context), survived))
        self.operators.credit(operator_name, context, survived)

    def calibration(self, n_bins: int = 10) -> CalibrationReport:
        """An honest reliability read on the emitted confidences (reported, never a gate)."""
        return calibration_report(self.log, n_bins)


@dataclass(frozen=True)
class CalibrationReport:
    """A reliability read on a policy's emitted confidences vs observed survival — reported, never
    asserted as a gate. ``skill`` is the Brier skill score against always predicting the base rate:
    positive means the confidences carry information beyond the overall survival frequency, zero
    means they are no better than that constant, negative means worse. ``ece`` is the count-weighted
    mean gap between predicted and observed frequency across the reliability ``bins`` (each
    ``(lo, hi, count, mean_pred, mean_obs)``)."""

    n: int
    base_rate: float
    brier: float
    baseline_brier: float
    skill: float
    ece: float
    bins: tuple[tuple[float, float, int, float, float], ...]


def calibration_report(log, n_bins: int = 10) -> CalibrationReport:
    """Summarize ``log`` (``(predicted_probability, observed_survival)`` pairs) into a
    :class:`CalibrationReport`. Pure and deterministic (values round to :data:`_ROUND` dp); an empty
    log yields the all-zero report. This only *measures* the policy's confidence — it can never
    weaken the ``validate -> verify -> certify`` gate that alone decides acceptance."""
    n = len(log)
    if n == 0:
        return CalibrationReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, ())
    base = math.fsum(y for _, y in log) / n
    brier = math.fsum((p - y) ** 2 for p, y in log) / n
    baseline = math.fsum((base - y) ** 2 for _, y in log) / n
    skill = 0.0 if baseline == 0.0 else 1.0 - brier / baseline
    bins: list[tuple[float, float, int, float, float]] = []
    ece = 0.0
    for k in range(n_bins):
        lo, hi = k / n_bins, (k + 1) / n_bins
        last = k == n_bins - 1
        members = [(p, y) for p, y in log if lo <= p < hi or (last and p >= hi)]
        count = len(members)
        if count == 0:
            bins.append((round(lo, _ROUND), round(hi, _ROUND), 0, 0.0, 0.0))
            continue
        mean_pred = math.fsum(p for p, _ in members) / count
        mean_obs = math.fsum(y for _, y in members) / count
        ece += (count / n) * abs(mean_pred - mean_obs)
        bins.append(
            (round(lo, _ROUND), round(hi, _ROUND), count,
             round(mean_pred, _ROUND), round(mean_obs, _ROUND))
        )
    return CalibrationReport(
        n, round(base, _ROUND), round(brier, _ROUND), round(baseline, _ROUND),
        round(skill, _ROUND), round(ece, _ROUND), tuple(bins),
    )


__all__ = ["CalibrationReport", "ContextualBandit", "ContextualPolicy", "calibration_report"]
