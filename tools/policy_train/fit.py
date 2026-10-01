"""Fit the frozen decision model — per-operator ridge stats — from a harvested corpus.

This is the offline counterpart of :meth:`spie.context_policy.ContextualBandit.credit`: it folds
each ``(context, operator, survived)`` triple into that operator's ridge accumulators
``A = ridge*I + Σ x·xᵀ`` and ``b = Σ survived·x`` using the *same* arithmetic, but does it once, over
the whole corpus, in a **canonical sorted order**. Float addition is not associative, so a fixed
fold order is what makes the fitted weights byte-reproducible; a final rounding to
:data:`spie.context_policy._ROUND` (6) decimal places absorbs the last-bit noise so the emitted
literal's ``repr`` is stable across platforms.
"""

from __future__ import annotations

from spie.context_policy import _ROUND, ContextualBandit

from .collect import Triple


def fit(
    corpus: list[Triple], dim: int, alpha: float, ridge: float
) -> tuple[dict[str, list[list[float]]], dict[str, list[float]]]:
    """Return ``(a_mat, b_vec)`` — the per-operator ridge weights fitted on ``corpus``.

    The corpus is folded in ascending ``(context, operator, survived)`` order (the canonical order
    that fixes float summation), reusing :class:`ContextualBandit`'s exact accumulation. Every stored
    value is rounded to 6 dp and both dicts are returned keyed in sorted-operator order, so the
    weights — and therefore the artifact hash — are a deterministic function of the corpus alone."""
    bandit = ContextualBandit(alpha=alpha, ridge=ridge, dim=dim)
    for context, operator_name, survived in sorted(corpus):
        bandit.credit(operator_name, context, survived)
    a_mat = {
        name: [[round(v, _ROUND) for v in row] for row in bandit.a_mat[name]]
        for name in sorted(bandit.a_mat)
    }
    b_vec = {
        name: [round(v, _ROUND) for v in bandit.b_vec[name]] for name in sorted(bandit.b_vec)
    }
    return a_mat, b_vec


__all__ = ["fit"]
