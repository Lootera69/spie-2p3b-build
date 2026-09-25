"""Phase 5.1 -- the bounded-rational strategy solver and the surprise proxy.

The deceptive ``greedy_trap`` fixture is the positive oracle: a bait that satisfies a goal
conjunct within the myopic horizon (LOOKAHEAD=2) but dead-ends, forcing a physical backtrack the
optimal solver never makes -- so ``backtracks >= 1`` and ``steps_taken > depth`` prove the read is
behavioural, not a re-encoding of optimal cost. The clean corpus puzzles are the reduction anchor
(``backtracks == 0``, ``surprise == 0``), the belief puzzles exercise the collapse regime, and the
certificate-immunity guard proves the EVALUATION additions never touch the proof artifact.
"""

from __future__ import annotations

from epistemic_fixtures import which_switch
from spie import certificate, fingerprint, search, strategy
from spie.examples_src import BUILDERS, combination_lock, hidden, irreversible, move, which_door
from spie.expr import Const, Eq, Var, all_of
from spie.ir import Action, Assign, Kind, Objective, Puzzle, Variable
from spie.quality import descriptors
from spie.serialize import certificate_to_json, dumps

CORPUS = fingerprint.corpus_fingerprints([b() for b in BUILDERS])


def greedy_trap() -> Puzzle:
    """A bait corridor: ``bait`` sets conjunct ``a`` within the horizon then strands the player at
    a dead end, while the real solution ``c1..c5`` sets ``b`` (step 4) and ``a`` (step 5) only
    deeper than LOOKAHEAD=2. The myopic player is lured into ``bait``, backtracks once, then walks
    the corridor -- optimal depth 5, but 6 forward steps."""
    variables = (
        Variable("x", Kind.INT, 0, 6),
        Variable("a", Kind.BOOL),
        Variable("b", Kind.BOOL),
    )
    bait = Action(
        name="bait",
        precondition=Eq(Var("x"), Const(0)),
        effects=(Assign("a", Const(1)), Assign("x", Const(6))),
    )
    c1 = Action(name="c1", precondition=Eq(Var("x"), Const(0)), effects=(Assign("x", Const(1)),))
    c2 = Action(name="c2", precondition=Eq(Var("x"), Const(1)), effects=(Assign("x", Const(2)),))
    c3 = Action(name="c3", precondition=Eq(Var("x"), Const(2)), effects=(Assign("x", Const(3)),))
    c4 = Action(
        name="c4",
        precondition=Eq(Var("x"), Const(3)),
        effects=(Assign("x", Const(4)), Assign("b", Const(1))),
    )
    c5 = Action(
        name="c5",
        precondition=Eq(Var("x"), Const(4)),
        effects=(Assign("x", Const(5)), Assign("a", Const(1))),
    )
    return Puzzle(
        id="greedy_trap",
        title="The Baited Corridor",
        nodes=("R",),
        edges=(),
        variables=variables,
        initial={"x": 0, "a": 0, "b": 0},
        actions=(bait, c1, c2, c3, c4, c5),
        objective=Objective(
            goal=all_of(Eq(Var("a"), Const(1)), Eq(Var("b"), Const(1))), max_horizon=8
        ),
        seed=0,
        notes="Deceptive: bait satisfies a conjunct within L=2 but dead-ends; goal is deeper.",
    )


# --- the deceptive positive oracle ---------------------------------------------------------


def test_greedy_trap_strategy_is_deceived():
    depth = search.explore(greedy_trap()).min_goal_dist()
    assert depth == 5  # sanity: the corridor is the unique shortest solution
    sr = strategy.strategy_of(greedy_trap())
    assert sr.solvable and sr.complete
    assert sr.inference_depth == depth  # commits to the optimal path in the end
    assert sr.backtracks == 1  # lured into the bait, retreats once
    assert sr.steps_taken == 6 and sr.steps_taken > depth  # non-collapse: fooled into a detour
    assert sr.branching_faced == 2  # the start's bait/corridor fork
    assert sr.memory_load == 6


def test_greedy_trap_surprise_is_plan_flip():
    su = strategy.surprise_of(greedy_trap())
    # regret at the start: greedy takes bait (rd absent -> INF=7), forced move keeps rd=5.
    assert su.pivot_kind == "plan-flip"
    assert su.pivot_index == 0  # the earliest, largest-regret step
    assert su.regret_steps == 3 and su.prediction_error == 3.0
    assert su.bits_resolved == 0.0  # regret regime carries no belief bits
    assert su.score > 0.0 and su.score == round(3 / (3 + 5), 6)  # == 0.375


# --- reduction anchor: clean linear puzzles are undeceived ---------------------------------


def test_linear_puzzles_reduce_to_degenerate():
    for builder in (move, hidden):
        q = descriptors(builder(), CORPUS)
        assert q.strategy.solvable and q.strategy.complete
        assert q.strategy.backtracks == 0  # nothing to backtrack out of
        assert q.strategy.inference_depth == q.difficulty.depth  # optimal == committed
        assert q.strategy.steps_taken == q.difficulty.depth  # no wasted moves
        assert q.surprise.score == 0.0
        assert q.surprise.pivot_kind == "none"
        assert q.surprise.pivot_index == -1


def test_irreversible_never_physically_backtracks():
    # Documented negative: the fatal move is a `loss`, pruned by `_live`, so the greedy player
    # never physically enters it -- backtracking measures dead ends, not danger avoided.
    assert strategy.strategy_of(irreversible()).backtracks == 0


# --- belief-collapse regime ----------------------------------------------------------------


def test_full_belief_collapse():
    # |B0| = 2, one sensing branch resolves the single bit entirely -> score == 1.0.
    for builder in (which_switch, which_door):
        su = strategy.surprise_of(builder())
        assert su.pivot_kind == "belief-collapse"
        assert su.score == 1.0
        sr = strategy.strategy_of(builder())
        assert sr.solvable and sr.complete and sr.backtracks == 0


def test_partial_belief_collapse():
    # |B0| = 4 (2 bits); one probe resolves one bit -> 0 < score < 1 (== 0.5).
    su = strategy.surprise_of(combination_lock())
    assert su.pivot_kind == "belief-collapse"
    assert 0.0 < su.score < 1.0 and su.score == 0.5
    assert strategy.strategy_of(combination_lock()).backtracks == 0


# --- determinism ---------------------------------------------------------------------------


def test_strategy_and_surprise_are_deterministic():
    for builder in (greedy_trap, move, which_door):
        p = builder()
        strat = {strategy.strategy_of(p) for _ in range(3)}
        surp = {strategy.surprise_of(p) for _ in range(3)}
        assert len(strat) == 1 and len(surp) == 1  # frozen + recompute-identical


# --- quality.py wiring ---------------------------------------------------------------------


def test_descriptors_wire_strategy_and_surprise():
    for builder in (move, which_door):
        p = builder()
        q = descriptors(p, CORPUS)
        assert q.strategy == strategy.strategy_of(p)
        assert q.surprise == strategy.surprise_of(p)


# --- certificate immunity (the standing reduction oracle, in-suite) ------------------------


def test_evaluation_additions_never_touch_the_certificate():
    for builder in (move, which_door):
        p = builder()
        first = dumps(certificate_to_json(certificate.certify(p)))
        second = dumps(certificate_to_json(certificate.certify(p)))
        assert first == second  # byte-reproducible proof artifact
        cert_json = certificate_to_json(certificate.certify(p))
        assert "strategy" not in cert_json and "surprise" not in cert_json
