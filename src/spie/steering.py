"""Phase C1 — deterministic, dependency-free Adaptive Operator Selection (AOS) for MAP-Elites.

A learned *steering* policy, and nothing more. It biases the two choices that
:func:`spie.mapelites.evolve` makes each iteration — **which occupied niche to expand** and **which
of the 16 mutation operators to apply** — with a discounted-UCB bandit whose reward is the survival
signal already computed by
:func:`spie.mapelites.place`: a child that is ``placed`` or ``replaced`` scored 1.0, everything else
(dominated / rejected at a gate / no-op) scored 0.0.

**Thesis-safe by construction.** The policy never decides correctness. Every child it proposes still
passes the unchanged ``validate -> verify -> certify`` gate before it can occupy a cell, and the
reward is *derived from* that gate's verdict — never a substitute for it. The policy chooses only
*what to try*; the formal solvers remain the sole authority on what is *accepted* (roadmap stage 8:
learning "recalibrates search policies", never proof or acceptance).

**Determinism is preserved.** UCB scores are rounded to 6 dp (matching
:func:`spie.mapelites.fitness_of`) and ties break on the sorted arm key, so selection is a pure,
reproducible ``argmax`` that never
touches the run's ``random.Random`` — a policy-driven ``evolve`` is as byte-reproducible as the
uniform one. Non-stationarity (an operator's utility drifts as niches fill) is handled by a discount
factor ``gamma`` applied to both the reward and the pull count on every update.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# UCB exploration weight; 1/sqrt(2) is optimal when the reward lies in [0, 1] (the survival signal
# is exactly {0, 1}), per the QD-as-a-bandit result the design doc settles on.
_LAMBDA = 1.0 / math.sqrt(2.0)
# Discount for non-stationarity: on each update w,n <- gamma*w+r, gamma*n+1. 1.0 == plain UCB1.
_DEFAULT_GAMMA = 0.98
_ROUND = 6  # decimal places; must match the fitness rounding so comparisons are order-stable


def _ucb(w: float, n: float, total: float, lam: float) -> float:
    """The upper-confidence score for an arm with discounted survival ``w``, pull count ``n``, and
    grand total pulls ``total``. An untried arm (``n <= 0``) scores ``+inf`` so every arm is forced
    once before exploitation begins. Rounded to :data:`_ROUND` dp so equal scores compare equal."""
    if n <= 0.0:
        return math.inf
    return round(w / n + lam * math.sqrt(math.log(total) / n), _ROUND)


@dataclass
class Bandit:
    """A discounted-UCB bandit over hashable, sortable arm keys. Pure deterministic counters:
    ``stats[arm] = (w, n)`` with ``w`` the discounted survival mass and ``n`` the discounted pull
    count. No RNG — selection is an ``argmax`` with sorted-key tie-breaking."""

    gamma: float = _DEFAULT_GAMMA
    lam: float = _LAMBDA
    stats: dict[object, tuple[float, float]] = field(default_factory=dict)

    def select(self, arms) -> object:
        """Return the arm maximizing the UCB score, considering ``arms`` (the current candidate
        set) in sorted order so the first of any tie wins deterministically. Raises ``ValueError``
        on an empty candidate set."""
        keys = sorted(arms)
        if not keys:
            raise ValueError("cannot select from an empty arm set")
        total = sum(n for _, n in self.stats.values()) or 1.0
        best, best_u = keys[0], -math.inf
        for k in keys:
            w, n = self.stats.get(k, (0.0, 0.0))
            u = _ucb(w, n, total, self.lam)
            if u > best_u:  # strict > keeps the first (sorted) arm on exact ties
                best, best_u = k, u
        return best

    def credit(self, arm, reward: float) -> None:
        """Fold one observed ``reward`` into ``arm``'s discounted stats."""
        w, n = self.stats.get(arm, (0.0, 0.0))
        self.stats[arm] = (self.gamma * w + reward, self.gamma * n + 1.0)

    def mean(self, arm) -> float:
        """The current discounted survival estimate for ``arm`` (0.0 if never pulled) — a reporting
        convenience, never consulted for acceptance."""
        w, n = self.stats.get(arm, (0.0, 0.0))
        return round(w / n, _ROUND) if n > 0.0 else 0.0


@dataclass
class SteeringPolicy:
    """The pair of bandits :func:`spie.mapelites.evolve` consults: one over parent niches, one over
    operator names. A fresh instance has empty stats (so it explores every arm once), and a single
    instance carried across successive ``evolve`` calls accumulates the survival history — the
    minimal learned proposer, with the formal gate untouched behind it."""

    niches: Bandit = field(default_factory=Bandit)
    operators: Bandit = field(default_factory=Bandit)

    def choose_niche(self, niches):
        """Pick which occupied niche to expand."""
        return self.niches.select(niches)

    def choose_operator(self, operator_names, context=None):
        """Pick which mutation operator (by ``__name__``) to apply. ``context`` is accepted so this
        context-free policy satisfies the same protocol as
        :class:`~spie.context_policy.ContextualPolicy`; it is ignored here."""
        return self.operators.select(operator_names)

    def reward(self, niche, operator_name: str, survived: float, context=None) -> None:
        """Credit both the parent niche and the operator with the child's survival outcome.
        ``context`` is accepted for protocol parity with the contextual policy and ignored."""
        self.niches.credit(niche, survived)
        self.operators.credit(operator_name, survived)


__all__ = ["Bandit", "SteeringPolicy"]
