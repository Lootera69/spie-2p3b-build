"""Solver-agnostic result types — the shared vocabulary of the proof loop.

Phase 2 introduces a second, independent solver (:mod:`spie.search`, an explicit-state
search) alongside the Z3 backend (:mod:`spie.solver`). For the two to be *cross-validated*
against each other they must speak in the same result shapes, so those shapes live here,
in a module that imports neither backend (and, crucially, does not import z3). Both solvers
populate these dataclasses; :mod:`spie.crosscheck` compares them field for field.

``Solution`` carries both a length (``horizon`` — the number of action steps) and a
``cost`` (the summed :attr:`~spie.ir.Action.cost` along the trace). A minimal-*length*
solve and a minimal-*cost* solve return the same type; they simply optimise a different
field, which is what lets the shortcut gate reason about them uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The equivalence relation under which two solutions count as "the same". A solution is a
# canonical state-path (the tuple of per-tick state tuples); two action traces that induce
# the same state-path are the same solution. Both solvers and both uniqueness checks use
# this exact relation, so their verdicts are comparable.
EQUIVALENCE = "canonical-state-path"


@dataclass
class Solution:
    """Outcome of a reachability search, from either backend.

    ``horizon`` is the number of steps in ``trace`` (0 when the initial state already
    satisfies the goal). ``state_path`` is the canonical s0..sH sequence — one integer
    tuple per tick, variables in declared order — the same object the uniqueness check
    blocks and conformance compares against. ``cost`` is the summed action cost along the
    trace (equal to ``horizon`` when every action has the default unit cost).
    """

    solvable: bool
    horizon: int
    trace: list[str] = field(default_factory=list)
    state_path: tuple[tuple[int, ...], ...] = ()
    cost: int = 0


@dataclass
class Uniqueness:
    """Verdict of a uniqueness check under :data:`EQUIVALENCE`.

    ``witness`` is a second, genuinely distinct minimal solution (a different state-path of
    the same minimal length) when one exists, else ``None``.
    """

    unique: bool
    equivalence: str
    witness: list[str] | None = None


@dataclass(frozen=True)
class Plan:
    """A contingent plan — the Phase-3 generalization of a linear :class:`Solution`.

    A *leaf* (``action is None``) marks a point where the goal is guaranteed in every world
    the player still considers possible. An *internal* node fires ``action`` and then branches
    on what is observed afterwards: ``branches`` pairs each observed valuation (a tuple of
    observed variable values, in a fixed key order) with the sub-plan to follow for that
    contingency, sorted by that valuation for determinism.

    A plan whose every internal node has exactly one branch encodes no genuine
    choice-of-observation — it *is* a linear trace, the fully-observable degenerate case, and
    :meth:`linear_trace` recovers the classic action list. This is what lets a contingent plan
    reduce, byte for byte, to today's :class:`Solution` when nothing is hidden.
    """

    action: str | None
    branches: tuple[tuple[tuple[int, ...], Plan], ...] = ()

    @property
    def is_leaf(self) -> bool:
        return self.action is None

    def depth(self) -> int:
        """Worst-case number of actions along any root-to-leaf path (analogue of horizon)."""
        if self.is_leaf:
            return 0
        return 1 + max(child.depth() for _, child in self.branches)

    def min_depth(self) -> int:
        """Best-case number of actions along any root-to-leaf path — the *shortest* branch.

        Equals :meth:`depth` for a linear plan; the gap ``depth() - min_depth()`` is the
        depth spread, an epistemic difficulty proxy (how uneven the contingencies are)."""
        if self.is_leaf:
            return 0
        return 1 + min(child.min_depth() for _, child in self.branches)

    def branch_factor(self) -> int:
        """The maximum number of observation outcomes at any single node (1 = linear, never
        branches; ``>= 2`` = a genuine sensing split). A leaf contributes 0."""
        if self.is_leaf:
            return 0
        return max([len(self.branches)] + [child.branch_factor() for _, child in self.branches])

    def leaf_count(self) -> int:
        """Number of leaves — the count of distinct contingencies the plan resolves to."""
        if self.is_leaf:
            return 1
        return sum(child.leaf_count() for _, child in self.branches)

    def internal_count(self) -> int:
        """Number of action (non-leaf) nodes — the plan's decision points."""
        if self.is_leaf:
            return 0
        return 1 + sum(child.internal_count() for _, child in self.branches)

    def is_linear(self) -> bool:
        """True iff the plan never branches — a single line of actions."""
        node = self
        while not node.is_leaf:
            if len(node.branches) != 1:
                return False
            node = node.branches[0][1]
        return True

    def linear_trace(self) -> list[str] | None:
        """The action list if this plan is linear (no branching), else ``None``."""
        trace: list[str] = []
        node = self
        while not node.is_leaf:
            if len(node.branches) != 1:
                return None
            trace.append(node.action)  # type: ignore[arg-type]  # non-leaf ⇒ action is set
            node = node.branches[0][1]
        return trace


__all__ = ["EQUIVALENCE", "Solution", "Uniqueness", "Plan"]
