"""Fingerprints and pairwise novelty (Phase 2, D4).

Two puzzles that share almost every mechanic should look alike to the archive; one that
introduces a new operator, a new variable kind, or a new solution shape should stand out.
We capture that with two deterministic, surface-rename-invariant fingerprints:

* a *mechanic* fingerprint — a feature vector over the constraint graph: the operator
  profile across every precondition / effect / goal / loss / invariant, the variable-kind
  mix, and the sizes of the world and action set; and
* a *solution-trace* fingerprint — the shape of the canonical solution (its length, cost,
  and how many distinct action templates it fires), extended in Phase 3 with four epistemic
  columns (belief size, plan branch factor, depth spread, sensing count) carried as *excess
  over the linear case* so they vanish to zero for a fully-observable puzzle.

Novelty is the distance from a puzzle to its nearest neighbour in a comparison set. The
persistent, growing archive is a later (MAP-Elites) phase; here the neighbourhood is just
the corpus, compared pairwise. Distance is cosine distance over the concatenated feature
vector — it reads *profile shape*, not raw magnitude, and needs no cross-corpus
normalisation, so a puzzle's fingerprint is a pure function of the puzzle alone (the
determinism the quality vector requires). Feature counts are non-negative, so cosine
similarity — and hence novelty — lands in ``[0, 1]``.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from . import epistemic, search
from . import expr as E
from .ground import ground_all
from .ir import Kind, Puzzle
from .results import Plan

# Stable operator vocabulary — the operator-profile columns, in a fixed order so vectors
# from different puzzles are aligned coordinate-for-coordinate.
_OPS = (
    "Const", "Var", "Node", "Edge", "PVal", "Not", "And", "Or",
    "Add", "Sub", "Eq", "Lt", "Le", "Ite",
)


def _count_ops(node: E.Expr, counter: Counter) -> None:
    """Tally operator occurrences over an expression tree — structural recursion mirroring
    the AST exactly as the interpreter and Z3 compiler walk it."""
    counter[type(node).__name__] += 1
    match node:
        case E.Const() | E.Var() | E.Node() | E.PVal():
            return
        case E.Not(operand):
            _count_ops(operand, counter)
        case E.And(operands) | E.Or(operands):
            for o in operands:
                _count_ops(o, counter)
        case E.Add(a, b) | E.Sub(a, b) | E.Eq(a, b) | E.Lt(a, b) | E.Le(a, b) | E.Edge(a, b):
            _count_ops(a, counter)
            _count_ops(b, counter)
        case E.Ite(c, t, e):
            _count_ops(c, counter)
            _count_ops(t, counter)
            _count_ops(e, counter)
        case _:
            raise TypeError(f"unhandled node in fingerprint: {type(node).__name__}")


def _all_exprs(puzzle: Puzzle):
    """Every expression that carries mechanics: action guards and effect values, plus the
    objective's goal, loss, and invariants. A ``Reset`` marker carries no expression of its own
    (grounding expands it into concrete assignments), so it contributes nothing here."""
    for a in puzzle.actions:
        yield a.precondition
        for e in a.effects:
            if isinstance(e, E.Assign):
                yield e.value
    obj = puzzle.objective
    yield obj.goal
    if obj.loss is not None:
        yield obj.loss
    yield from obj.invariants


@dataclass(frozen=True)
class Fingerprint:
    """A puzzle's two fingerprints plus the concatenated vector novelty compares.

    ``mechanic`` and ``trace`` are label->value maps kept for auditability; ``vector`` is
    their values in a fixed key order (mechanic keys sorted, then trace keys sorted)."""

    mechanic: dict[str, float]
    trace: dict[str, float]
    vector: tuple[float, ...]


def _mechanic_features(puzzle: Puzzle) -> dict[str, float]:
    ops: Counter = Counter()
    for e in _all_exprs(puzzle):
        _count_ops(e, ops)
    kinds = Counter(v.kind for v in puzzle.variables)
    feats: dict[str, float] = {f"op:{name}": float(ops.get(name, 0)) for name in _OPS}
    feats["kind:Bool"] = float(kinds.get(Kind.BOOL, 0))
    feats["kind:Int"] = float(kinds.get(Kind.INT, 0))
    feats["kind:Loc"] = float(kinds.get(Kind.LOC, 0))
    feats["n_nodes"] = float(len(puzzle.nodes))
    feats["n_edges"] = float(len(puzzle.edges))
    feats["n_actions"] = float(len(puzzle.actions))
    feats["n_ground_actions"] = float(len(ground_all(puzzle)))
    feats["n_invariants"] = float(len(puzzle.objective.invariants))
    feats["has_loss"] = 1.0 if puzzle.objective.loss is not None else 0.0
    return feats


def _plan_templates(plan: Plan) -> set[str]:
    """The distinct action-name templates fired anywhere in a contingent plan."""
    names: set[str] = set()
    stack = [plan]
    while stack:
        node = stack.pop()
        if node.action is not None:
            names.add(node.action.split("[", 1)[0])
        stack.extend(child for _, child in node.branches)
    return names


def _epistemic_trace_features(puzzle: Puzzle) -> dict[str, float]:
    """Trace features for a puzzle with hidden state, read from its contingent plan. The
    length/cost/template columns mirror the linear case (worst-case depth stands in for both
    length and cost, which epistemic solving does not distinguish), and the four epistemic
    columns carry the *excess over linear* so they are strictly zero for the fully-observable
    case (see :func:`_trace_features`)."""
    strong = epistemic.solve_strong(puzzle)
    belief_count = len(epistemic.build_initial_belief(puzzle))
    sensing = float(sum(1 for a in puzzle.actions if a.senses))
    plan = strong.plan
    if plan is None:
        length = cost = distinct = branch_excess = spread = 0.0
    else:
        length = cost = float(plan.depth())
        distinct = float(len(_plan_templates(plan)))
        branch_excess = float(plan.branch_factor() - 1)
        spread = float(plan.depth() - plan.min_depth())
    return {
        "sol_length": length,
        "sol_cost": cost,
        "sol_distinct_templates": distinct,
        "epistemic_worlds": float(max(belief_count - 1, 0)),
        "plan_branch_excess": branch_excess,
        "plan_depth_spread": spread,
        "sensing_actions": sensing,
    }


def _trace_features(puzzle: Puzzle) -> dict[str, float]:
    """Solution-shape features. The four epistemic columns are defined as *excess over the
    linear case* — ``|B0|-1``, branch factor ``-1``, depth spread, sensing count — so they are
    all zero for a fully-observable puzzle. Appending zero-valued coordinates changes neither a
    vector's norm nor any dot product, so every fully-observable puzzle's fingerprint (and
    hence the corpus's pairwise novelty) is byte-identical to Phase 2 — the reduction anchor
    lifted to the novelty vector."""
    if puzzle.initial_belief:
        return _epistemic_trace_features(puzzle)
    sol = search.canonical_solution(puzzle)
    templates = {name.split("[", 1)[0] for name in sol.trace}
    return {
        "sol_length": float(sol.horizon),
        "sol_cost": float(sol.cost),
        "sol_distinct_templates": float(len(templates)),
        "epistemic_worlds": 0.0,
        "plan_branch_excess": 0.0,
        "plan_depth_spread": 0.0,
        "sensing_actions": 0.0,
    }


def fingerprint(puzzle: Puzzle) -> Fingerprint:
    """The full fingerprint of a puzzle: mechanic features ++ trace features."""
    mech = _mechanic_features(puzzle)
    trace = _trace_features(puzzle)
    vector = tuple(mech[k] for k in sorted(mech)) + tuple(trace[k] for k in sorted(trace))
    return Fingerprint(mechanic=mech, trace=trace, vector=vector)


def cosine_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """``1 - cosine similarity`` of two equal-length non-negative vectors, in ``[0, 1]``.

    A zero vector (no features at all) is treated as maximally distant from anything but
    another zero vector, which never arises for a real puzzle."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0 if na == nb else 1.0
    return 1.0 - dot / (na * nb)


def nearest(
    puzzle: Puzzle, corpus: list[tuple[str, Fingerprint]]
) -> tuple[float, str | None]:
    """Novelty of ``puzzle``: the minimum cosine distance to any corpus entry with a
    *different* id, and that neighbour's id. With no other puzzle to compare against,
    novelty is 1.0 (maximally novel) and the neighbour is ``None``."""
    fp = fingerprint(puzzle)
    best_d = 1.0
    best_id: str | None = None
    for other_id, other_fp in corpus:
        if other_id == puzzle.id:
            continue
        d = cosine_distance(fp.vector, other_fp.vector)
        if best_id is None or d < best_d:
            best_d, best_id = d, other_id
    return best_d, best_id


def corpus_fingerprints(puzzles: list[Puzzle]) -> list[tuple[str, Fingerprint]]:
    """Precompute ``(id, fingerprint)`` for a set of puzzles — the comparison neighbourhood
    novelty is measured against."""
    return [(p.id, fingerprint(p)) for p in puzzles]


__all__ = [
    "Fingerprint",
    "fingerprint",
    "cosine_distance",
    "nearest",
    "corpus_fingerprints",
]
