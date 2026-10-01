"""Phase C3 — the runtime loader for the frozen, offline-trained SPIE decision model.

Where :mod:`spie.context_policy` fits a LinUCB "decision model" *online* during a single search,
this module loads the model that ``tools/policy_train`` fitted *once*, offline, over a corpus SPIE
harvested from its own search, and froze into the checked-in artifact :mod:`spie.decision_model`.
At runtime it is **propose-only**: it chooses which operator to try and never learns.

**Thesis-safe by construction, and strictly more so than the online policies.**

* :class:`FrozenProposer` picks the operator by ``argmax_op predict(op, context)`` — the model's
  *calibrated mean* survival estimate (``clamp(theta.x, 0, 1)``), pure exploitation with **no**
  LinUCB exploration bonus, scanned in sorted-arm order so ties break deterministically and no RNG
  is ever touched. It only chooses *what to try*.
* Every child it proposes still clears the unchanged ``validate -> verify -> certify`` gate in
  :func:`spie.mapelites.place` before it can occupy a cell — the formal solvers remain the sole
  authority on acceptance, exactly as for the ``policy=None`` baseline.
* :meth:`FrozenProposer.reward` credits **only** the online niche bandit; the frozen operator
  weights are never touched. There is no online learning of the trained artifact — a run cannot
  perturb the shipped weights, so a ``FrozenProposer``-driven ``evolve`` is byte-reproducible for a
  given ``(seeds, iterations, seed)`` just like every other path.

Niche selection is the one online, run-specific choice (which occupied niche to expand is a function
of the run's own archive, not of the trained corpus), so it delegates to a fresh context-free
discounted-UCB :class:`~spie.steering.Bandit` — the Phase C1 mechanism, already thesis-blessed. The
*trained artifact* is the operator model alone.

The artifact is imported lazily inside :func:`load_decision_model`, so importing this module — and
thus :mod:`spie.mapelites`, whose ``Policy`` union includes :class:`FrozenProposer` — never needs
``decision_model.py`` to exist yet. The offline build can therefore regenerate the artifact from a
clean tree with no bootstrap cycle; only *constructing* a :class:`FrozenProposer` reads the weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .context_policy import ContextualBandit
from .steering import Bandit


def load_decision_model() -> ContextualBandit:
    """Build a frozen :class:`~spie.context_policy.ContextualBandit` from the checked-in artifact.

    The artifact (:mod:`spie.decision_model`) is a pure data literal — ``ALPHA`` / ``RIDGE`` /
    ``DIM`` and the per-operator ridge stats ``A_MAT`` / ``B_VEC`` — so the returned bandit carries
    the state the offline fit produced. The literal's nested lists are copied so the module-level
    constants are never aliased into (let alone mutated by) a running search; in practice nothing
    mutates them, since the proposer only ever *reads* the operator model (``predict``), never
    ``credit``s it."""
    from . import decision_model as dm

    return ContextualBandit(
        alpha=dm.ALPHA,
        ridge=dm.RIDGE,
        dim=dm.DIM,
        a_mat={name: [list(row) for row in rows] for name, rows in dm.A_MAT.items()},
        b_vec={name: list(vec) for name, vec in dm.B_VEC.items()},
    )


@dataclass
class FrozenProposer:
    """A propose-only policy satisfying :func:`spie.mapelites.evolve`'s
    ``choose_niche`` / ``choose_operator`` / ``reward`` protocol, driven by the offline-trained,
    frozen operator model plus a fresh online niche bandit.

    Constructing one loads the artifact (see :func:`load_decision_model`); the operator weights are
    then read-only for the life of the proposer. ``operators`` is the frozen model; ``niches`` is a
    per-run context-free bandit that learns which niche to expand, exactly as in Phase C1."""

    operators: ContextualBandit = field(default_factory=load_decision_model)
    niches: Bandit = field(default_factory=Bandit)

    def choose_niche(self, niches):
        """Pick which occupied niche to expand (online context-free discounted-UCB, as Phase C1)."""
        return self.niches.select(niches)

    def choose_operator(self, operator_names, context):
        """Pick the operator with the highest frozen calibrated survival estimate for ``context``.

        Pure exploitation: ``argmax_op predict(op, context)`` with **no** exploration bonus,
        scanning the operator names in sorted order so the first of any (6-dp-rounded) tie wins.
        RNG-free and a deterministic function of the frozen weights and the context — an untried
        operator scores the prior ``predict`` of ``0.0``, so it never beats a trained one.
        ``ValueError`` on empty."""
        keys = sorted(operator_names)
        if not keys:
            raise ValueError("cannot choose from an empty operator set")
        best, best_p = keys[0], -1.0
        for key in keys:
            p = self.operators.predict(key, context)
            if p > best_p:  # strict > keeps the first (sorted) operator on exact ties
                best, best_p = key, p
        return best

    def reward(self, niche, operator_name: str, survived: float, context=None) -> None:
        """Credit the child's survival to the online niche bandit **only**.

        The frozen operator model is deliberately never updated: the trained artifact is
        propose-only and does no online learning, so a run can never perturb the shipped weights.
        ``operator_name`` and ``context`` are accepted for protocol parity and ignored here."""
        self.niches.credit(niche, survived)


__all__ = ["FrozenProposer", "load_decision_model"]
