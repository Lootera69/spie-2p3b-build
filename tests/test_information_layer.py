"""Phase-3.1 tests: the information layer — Observability, hidden-variable belief support,
and sensing — round-trips byte-identically and validates, while leaving the fully-observable
corpus untouched (the reduction anchor, checked here at the IR/serialization level).
"""

from __future__ import annotations

import json
from dataclasses import replace

from spie.examples_src import move
from spie.expr import Assign, Const, Eq, Var
from spie.ir import Action, Kind, Objective, Observability, Puzzle, Variable
from spie.serialize import dumps, puzzle_from_json, puzzle_to_json
from spie.validate import validate


def _rules(puzzle: Puzzle) -> set[str]:
    return {f.rule for f in validate(puzzle)}


def _hidden_puzzle() -> Puzzle:
    """A tiny well-formed puzzle exercising every new field: a HIDDEN code the player must
    sense, a DELAYED reading, and a REMEMBERED, persistent note."""
    variables = (
        Variable("code", Kind.INT, 0, 2, obs=Observability.HIDDEN),
        Variable("reading", Kind.INT, 0, 2, obs=Observability.DELAYED, delay=1),
        Variable("known", Kind.BOOL, obs=Observability.REMEMBERED, persistent=True),
    )
    probe = Action(
        name="probe",
        precondition=Eq(Var("known"), Const(0)),
        effects=(Assign("known", Const(1)),),
        senses=("code", "reading"),
    )
    return Puzzle(
        id="hidden_fixture",
        title="Sense the Code",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"code": 1, "reading": 0, "known": 0},
        actions=(probe,),
        objective=Objective(goal=Eq(Var("known"), Const(1)), max_horizon=3),
        initial_belief={"code": (0, 1, 2)},
    )


def test_information_puzzle_round_trips_byte_identically():
    puzzle = _hidden_puzzle()
    once = dumps(puzzle_to_json(puzzle))
    restored = puzzle_from_json(json.loads(once))
    twice = dumps(puzzle_to_json(restored))
    assert once == twice
    # The new fields actually survive the round-trip (not silently dropped).
    by_key = restored.variables_by_key()
    assert by_key["code"].obs is Observability.HIDDEN
    assert by_key["reading"].obs is Observability.DELAYED and by_key["reading"].delay == 1
    assert by_key["known"].obs is Observability.REMEMBERED and by_key["known"].persistent
    assert restored.actions[0].senses == ("code", "reading")
    assert restored.initial_belief == {"code": (0, 1, 2)}


def test_information_puzzle_validates_clean():
    assert validate(_hidden_puzzle()) == []


def test_new_fields_are_emitted_when_nondefault():
    text = dumps(puzzle_to_json(_hidden_puzzle()))
    for key in ("obs", "delay", "persistent", "senses", "initial_belief"):
        assert f'"{key}"' in text, f"expected {key!r} in serialized hidden puzzle"


def test_visible_puzzle_emits_no_new_keys():
    """Omit-when-default: a fully-observable puzzle serializes exactly as before Phase 3."""
    text = dumps(puzzle_to_json(move()))
    for key in ("obs", "delay", "persistent", "senses", "initial_belief"):
        assert f'"{key}"' not in text, f"unexpected {key!r} in a VISIBLE puzzle"


def test_hidden_without_belief():
    puzzle = replace(_hidden_puzzle(), initial_belief={})
    assert "hidden-without-belief" in _rules(puzzle)


def test_belief_unknown_var():
    puzzle = replace(move(), initial_belief={"ghost": (0, 1)})
    assert "belief-unknown-var" in _rules(puzzle)


def test_belief_not_hidden():
    puzzle = replace(move(), initial_belief={"pos": (0, 1)})
    assert "belief-not-hidden" in _rules(puzzle)


def test_belief_out_of_range():
    base = _hidden_puzzle()
    assert "belief-out-of-range" in _rules(replace(base, initial_belief={"code": (0, 1, 5)}))


def test_belief_initial_not_in_support():
    base = _hidden_puzzle()
    assert "belief-initial-not-in-support" in _rules(replace(base, initial_belief={"code": (0, 2)}))


def test_negative_delay():
    base = _hidden_puzzle()
    bad = (replace(base.variables[0], delay=-1), *base.variables[1:])
    assert "negative-delay" in _rules(replace(base, variables=bad))


def test_senses_unknown_var():
    base = _hidden_puzzle()
    bad_action = replace(base.actions[0], senses=("ghost",))
    assert "senses-unknown-var" in _rules(replace(base, actions=(bad_action,)))

