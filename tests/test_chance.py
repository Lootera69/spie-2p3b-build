"""Item-4 tests: the *chance* layer — a random (weighted) hidden initial state whose exact optimal
expected success probability ``P`` is certified as an exact :class:`~fractions.Fraction`, never a
float, and cross-checked three independent ways (belief-DP ``P_A``, per-world replay ``P_B``, and
the reachability upper bound ``U``).

The layer is strictly additive: with an empty :attr:`~spie.ir.Puzzle.initial_dist` (every
deterministic and every existing epistemic puzzle) none of the chance code runs and the puzzle /
certificate serialize byte-for-byte as before. These tests pin that reduction *and* the exactness
and load-bearing-ness of the three-way cross-check.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from fractions import Fraction

import spie.verify as verify_mod
from epistemic_fixtures import which_switch
from spie import epistemic
from spie.certificate import certify
from spie.chance import chance_cross_solve
from spie.examples_src import move
from spie.expr import Assign, Const, Eq, Var
from spie.ir import Action, Kind, Objective, Observability, Puzzle, Variable
from spie.operators import weight_belief
from spie.serialize import (
    _fraction_from_json,
    _fraction_to_json,
    certificate_to_json,
    dumps,
    puzzle_from_json,
    puzzle_to_json,
)
from spie.validate import validate
from spie.verify import verify


def _rules(puzzle: Puzzle) -> set[str]:
    return {f.rule for f in validate(puzzle)}


def guess_and_grab(dist: dict | None = None) -> Puzzle:
    """A hidden coin ``key`` ∈ {0, 1}: only the ``key == 0`` world is winnable (``grab`` is legal
    solely there), so a best-effort plan senses ``key`` and grabs when it can. With weights
    ``key=0 -> 2/3``, ``key=1 -> 1/3`` the exact optimal success probability is ``Fraction(2, 3)``.
    ``look`` is a pure sense (a framing self-assignment keeps it a legal no-op effect)."""
    if dist is None:
        dist = {"key": ((0, Fraction(2, 3)), (1, Fraction(1, 3)))}
    return Puzzle(
        id="chance_guess_grab",
        title="Guess and grab",
        nodes=("room",),
        edges=(),
        variables=(
            Variable("key", Kind.BOOL, obs=Observability.HIDDEN),
            Variable("got", Kind.BOOL),
        ),
        initial={"key": 0, "got": 0},
        actions=(
            Action(
                name="look",
                precondition=Const(True),
                effects=(Assign("got", Var("got")),),
                senses=("key",),
            ),
            Action(
                name="grab",
                precondition=Eq(Var("key"), Const(0)),
                effects=(Assign("got", Const(1)),),
            ),
        ),
        objective=Objective(goal=Eq(Var("got"), Const(1)), max_horizon=2, requires_unique=False),
        initial_belief={"key": (0, 1)},
        initial_dist=dist,
    )


def which_switch_weighted() -> Puzzle:
    """The strong-solvable branching fixture with a uniform deal over the hidden target — every
    world is winnable, so the exact optimal ``P`` is ``Fraction(1)`` and equals the reachability
    bound ``U``, while the plan still genuinely branches on the sensed value."""
    base = which_switch()
    return replace(base, initial_dist={"target": ((0, Fraction(1, 2)), (1, Fraction(1, 2)))})


# --- additivity / omit-when-default -----------------------------------------------------------


def test_deterministic_puzzle_emits_no_dist_keys():
    """A fully-observable puzzle carries no distribution — its JSON is unchanged by this layer."""
    text = dumps(puzzle_to_json(move()))
    assert '"initial_dist"' not in text
    # ...and a chance puzzle genuinely emits it (the field is not silently dropped).
    assert '"initial_dist"' in dumps(puzzle_to_json(guess_and_grab()))


def test_chance_reduces_to_epistemic_when_dist_absent():
    """With no ``initial_dist`` the epistemic certificate takes the unchanged epistemic path: no
    chance solver, no probability fields — byte-for-byte the pre-Item-4 shape."""
    cert = certify(which_switch())
    assert cert.solver == epistemic.SOLVER_NAME
    assert cert.success_probability is None
    assert cert.success_probability_upper_bound is None
    text = dumps(certificate_to_json(cert))
    assert '"success_probability"' not in text
    assert '"success_probability_upper_bound"' not in text
    # Determinism: two certifies of the reduced puzzle are byte-identical.
    assert text == dumps(certificate_to_json(certify(which_switch())))


# --- exact-Fraction serialization -------------------------------------------------------------


def test_fraction_roundtrip_is_canonical():
    """Weights cross the JSON boundary as fully-reduced ``[num, den]`` (never a float) and rebuild
    exactly; a non-reduced input reduces canonically and re-serialization is byte-stable."""
    assert _fraction_to_json(Fraction(4, 6)) == [2, 3]  # reduces
    assert _fraction_to_json(Fraction(-2, 4)) == [-1, 2]  # sign in the numerator
    assert _fraction_to_json(Fraction(0)) == [0, 1]
    for fr in (Fraction(2, 3), Fraction(1), Fraction(0), Fraction(7, 10)):
        assert _fraction_from_json(_fraction_to_json(fr)) == fr

    puzzle = guess_and_grab()
    once = dumps(puzzle_to_json(puzzle))
    restored = puzzle_from_json(json.loads(once))
    assert restored.initial_dist == puzzle.initial_dist  # exact Fractions survive
    assert dumps(puzzle_to_json(restored)) == once  # byte-stable across the round-trip
    assert puzzle_to_json(puzzle)["initial_dist"] == {"key": [[0, [2, 3]], [1, [1, 3]]]}


# --- the certified quantity and its three-way cross-check -------------------------------------


def test_uniform_weights_recover_probability_one():
    """When every initial world is winnable the exact optimum is ``1`` and is sandwiched by the
    reachability bound (``P == U == 1``); the certificate reports it solvable."""
    puzzle = which_switch_weighted()
    cross = chance_cross_solve(puzzle)
    assert cross.agree
    assert cross.probability == Fraction(1)
    assert cross.probability == cross.probability_replay == cross.upper_bound
    cert = certify(puzzle)
    assert cert.success_probability == Fraction(1)
    assert cert.success_probability_upper_bound == Fraction(1)
    assert cert.solvable is True
    assert verify(puzzle).ok


def test_partial_success_probability_is_exact_and_cross_checked():
    """A puzzle only some of whose worlds are winnable pins the exact rational optimum: the two
    independent tallies agree (``P_A == P_B``) and both are bounded by ``U`` — here all three are
    exactly ``Fraction(2, 3)`` (an exact rational, not a float)."""
    puzzle = guess_and_grab()
    cross = chance_cross_solve(puzzle)
    assert cross.probability == Fraction(2, 3)
    assert cross.probability == cross.probability_replay  # P_A == P_B, exactly
    assert cross.probability <= cross.upper_bound
    assert cross.upper_bound == Fraction(2, 3)
    assert cross.agree and cross.uniform and not cross.truncated
    assert isinstance(cross.probability, Fraction)  # never a float
    cert = certify(puzzle)
    assert cert.success_probability == Fraction(2, 3)
    assert cert.solvable is False  # P < 1: not *fully* winnable
    assert verify(puzzle).ok


# --- the cross-check is load-bearing, not decorative ------------------------------------------


def test_verify_fails_on_injected_probability_disagreement(monkeypatch):
    """Force ``P_A != P_B`` and confirm the chance reachability gate FAILs with
    ``probability-disagreement`` — proof the cross-check actually gates acceptance."""
    puzzle = guess_and_grab()
    honest = chance_cross_solve(puzzle)
    doctored = replace(
        honest,
        probability_replay=honest.probability + Fraction(1, 5),
        agree=False,
        discrepancies=("probability disagreement (injected)",),
    )
    monkeypatch.setattr(verify_mod, "chance_cross_solve", lambda _p: doctored)

    report = verify(puzzle)
    assert not report.ok
    reach = next(g for g in report.gates if g.name == "reachability")
    assert reach.status is verify_mod.GateStatus.FAIL
    assert "probability-disagreement" in {f.rule for f in reach.findings}


# --- static validation of a malformed distribution --------------------------------------------


def test_validation_flags_bad_distribution():
    assert "dist-not-normalized" in _rules(
        guess_and_grab({"key": ((0, Fraction(1, 2)), (1, Fraction(1, 3)))})
    )
    assert "dist-support-mismatch" in _rules(
        guess_and_grab({"key": ((0, Fraction(1)),)})  # omits value 1 from the support
    )
    assert "dist-negative-weight" in _rules(
        guess_and_grab({"key": ((0, Fraction(4, 3)), (1, Fraction(-1, 3)))})
    )
    # A well-formed distribution raises none of the dist-* findings.
    clean = _rules(guess_and_grab())
    assert not {r for r in clean if r.startswith("dist-")}


# --- the weight_belief generation operator ----------------------------------------------------


def test_weight_belief_operator_produces_valid_distribution():
    """The operator turns an epistemic puzzle into a well-formed chance puzzle: a normalized,
    support-spanning, strictly-positive distribution that validates, verifies, and certifies with
    a well-defined exact ``P``. It never clobbers an existing deal or touches a beliefless one."""
    base = which_switch()
    dealt = weight_belief(base, random.Random(0))
    assert dealt is not None
    assert set(dealt.initial_dist) == {"target"}
    pairs = dealt.initial_dist["target"]
    assert {v for v, _ in pairs} == set(base.initial_belief["target"])  # spans the support
    assert all(w > 0 for _, w in pairs)  # strictly positive
    assert sum((w for _, w in pairs), Fraction(0)) == Fraction(1)  # exact normalization
    assert validate(dealt) == []
    assert verify(dealt).ok
    cert = certify(dealt)
    assert isinstance(cert.success_probability, Fraction)
    assert Fraction(0) < cert.success_probability <= Fraction(1)

    # Guards: never clobber an authored deal, never fire on a beliefless (deterministic) puzzle.
    assert weight_belief(guess_and_grab(), random.Random(0)) is None
    assert weight_belief(move(), random.Random(0)) is None
