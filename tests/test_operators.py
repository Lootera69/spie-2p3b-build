"""Phase 4.4 tests — Invention operators (the four mutation families over a Puzzle genome).

Each operator is proven to (a) change the puzzle in its intended dimension on an applicable
puzzle, (b) preserve well-formedness by construction (its result is always ``None`` or
``validate``-clean), (c) be deterministic given a fixed ``random.Random`` seed, and (d) return
``None`` rather than a malformed puzzle where it does not apply. Invertible operators
(``reverse_edge``, ``flip_persistence``) are shown to round-trip."""

from __future__ import annotations

import random

from spie.examples_src import BUILDERS
from spie.expr import Not
from spie.ir import Observability
from spie.operators import (
    FAMILIES,
    OPERATORS,
    add_decoy_action,
    add_reset_action,
    add_resource_budget,
    compose_actions,
    couple_variables,
    delay_effect,
    flip_persistence,
    hide_variable,
    invert_goal,
    make_observation_costly,
    remove_redundant_clue,
    require_invariant,
    reveal_variable,
    reverse_edge,
    synchronize_subsystems,
    transfer_property,
)
from spie.validate import validate

BY_NAME = {b.__name__: b for b in BUILDERS}


def _first_applicable(op, seed: int = 0):
    """The first (builder-name, puzzle, mutated) triple over the corpus where ``op`` applies."""
    for name, builder in BY_NAME.items():
        p = builder()
        out = op(p, random.Random(seed))
        if out is not None:
            return name, p, out
    return None


# --- Cross-cutting invariants over every operator -------------------------------------------


def test_operator_registry_is_complete() -> None:
    assert len(OPERATORS) == 16
    assert sum(len(fam) for fam in FAMILIES.values()) == len(OPERATORS)
    assert set(OPERATORS) == {op for fam in FAMILIES.values() for op in fam}


def test_every_operator_preserves_well_formedness() -> None:
    # An operator applied to any corpus puzzle yields either None or a validate-clean puzzle —
    # a malformed mutation is never offered to the search.
    for op in OPERATORS:
        for builder in BUILDERS:
            out = op(builder(), random.Random(1))
            assert out is None or validate(out) == [], f"{op.__name__} on {builder().id}"


def test_every_operator_is_deterministic() -> None:
    # Same puzzle + same seed => identical mutation (byte-reproducibility lifted to the operators).
    for op in OPERATORS:
        for builder in BUILDERS:
            a = op(builder(), random.Random(7))
            b = op(builder(), random.Random(7))
            assert a == b, f"{op.__name__} not deterministic on {builder().id}"


def test_every_operator_applies_somewhere() -> None:
    # Each operator is genuinely usable: it applies to at least one corpus puzzle.
    for op in OPERATORS:
        assert _first_applicable(op) is not None, f"{op.__name__} applies to no corpus puzzle"


def test_operators_do_not_mutate_input() -> None:
    for op in OPERATORS:
        for builder in BUILDERS:
            p = builder()
            before = (p.variables, p.actions, p.edges, p.objective, p.initial_belief)
            op(p, random.Random(3))
            after = (p.variables, p.actions, p.edges, p.objective, p.initial_belief)
            assert before == after, f"{op.__name__} mutated its input {p.id}"


# --- Structural -----------------------------------------------------------------------------


def test_couple_variables_adds_a_coupling_effect() -> None:
    name, p, out = _first_applicable(couple_variables)
    total_before = sum(len(a.effects) for a in p.actions)
    total_after = sum(len(a.effects) for a in out.actions)
    assert total_after == total_before + 1
    assert out.variables == p.variables and out.actions != p.actions


def test_transfer_property_marks_a_variable_persistent() -> None:
    p = BY_NAME["assembly_loop"]()  # has a persistent + a non-persistent same-Kind (INT) var
    out = transfer_property(p, random.Random(0))
    assert out is not None
    before = sum(v.persistent for v in p.variables)
    after = sum(v.persistent for v in out.variables)
    assert after == before + 1
    assert {v.key for v in out.variables} == {v.key for v in p.variables}


def test_reverse_edge_flips_one_edge_and_round_trips() -> None:
    name, p, out = _first_applicable(reverse_edge)
    assert set(out.edges) != set(p.edges)
    assert len(out.edges) == len(p.edges)
    # Reversing the same edge again restores the graph (invertible).
    back = reverse_edge(out, random.Random(0))
    assert back is not None
    assert set(back.edges) == set(p.edges)


def test_compose_actions_adds_a_macro_action() -> None:
    name, p, out = _first_applicable(compose_actions)
    assert len(out.actions) == len(p.actions) + 1
    macro = next(a for a in out.actions if a.name not in {x.name for x in p.actions})
    assert "__" in macro.name


# --- Temporal -------------------------------------------------------------------------------


def test_delay_effect_makes_a_variable_delayed() -> None:
    name, p, out = _first_applicable(delay_effect)
    delayed = [v for v in out.variables if v.obs is Observability.DELAYED]
    was = [v for v in p.variables if v.obs is Observability.DELAYED]
    assert len(delayed) == len(was) + 1
    assert all(v.delay >= 1 for v in delayed)


def test_flip_persistence_toggles_and_round_trips() -> None:
    p = BY_NAME["move"]()
    out = flip_persistence(p, random.Random(0))
    assert out is not None
    diff = [a.key for a, b in zip(p.variables, out.variables, strict=True) if a != b]
    assert len(diff) == 1
    # Toggling the same variable again restores the puzzle.
    back = flip_persistence(out, random.Random(0))
    assert back is not None
    assert back.variables == p.variables


def test_synchronize_subsystems_adds_an_equality_invariant() -> None:
    name, p, out = _first_applicable(synchronize_subsystems)
    assert len(out.objective.invariants) == len(p.objective.invariants) + 1


def test_add_reset_action_adds_one_reset_and_is_idempotent() -> None:
    name, p, out = _first_applicable(add_reset_action)
    assert len(out.actions) == len(p.actions) + 1
    assert any(a.name == "loop_reset" for a in out.actions)
    # A puzzle that already has a reset action is refused.
    assert add_reset_action(out, random.Random(0)) is None


# --- Information ----------------------------------------------------------------------------


def test_hide_variable_hides_and_seeds_belief() -> None:
    name, p, out = _first_applicable(hide_variable)
    hidden = [v for v in out.variables if v.obs is Observability.HIDDEN]
    was = [v for v in p.variables if v.obs is Observability.HIDDEN]
    assert len(hidden) == len(was) + 1
    new_key = ({v.key for v in hidden} - {v.key for v in was}).pop()
    assert new_key in out.initial_belief
    assert len(out.initial_belief[new_key]) >= 2


def test_reveal_variable_adds_a_sensing_action() -> None:
    name, p, out = _first_applicable(reveal_variable)
    new = next(a for a in out.actions if a.name not in {x.name for x in p.actions})
    assert new.name.startswith("sense_")
    assert new.senses and new.effects == ()


def test_make_observation_costly_raises_a_sense_cost() -> None:
    p = BY_NAME["which_door"]()  # peek senses the hidden prize
    out = make_observation_costly(p, random.Random(0))
    assert out is not None
    before = sum(a.cost for a in p.actions if a.senses)
    after = sum(a.cost for a in out.actions if a.senses)
    assert after == before + 1


def test_make_observation_costly_none_without_sensing() -> None:
    assert make_observation_costly(BY_NAME["move"](), random.Random(0)) is None


def test_add_decoy_action_adds_an_inert_action() -> None:
    name, p, out = _first_applicable(add_decoy_action)
    assert any(a.name == "decoy" for a in out.actions)
    assert len(out.actions) == len(p.actions) + 1
    assert add_decoy_action(out, random.Random(0)) is None  # only one decoy


# --- Goal / constraint ----------------------------------------------------------------------


def test_invert_goal_negates_the_goal() -> None:
    p = BY_NAME["move"]()
    out = invert_goal(p, random.Random(0))
    assert out is not None
    assert out.objective.goal == Not(p.objective.goal)


def test_add_resource_budget_introduces_a_budget_counter() -> None:
    name, p, out = _first_applicable(add_resource_budget)
    assert "budget" not in p.variables_by_key()
    assert "budget" in out.variables_by_key()
    assert out.initial["budget"] == out.variables_by_key()["budget"].hi
    # A puzzle that already has a budget is refused.
    assert add_resource_budget(out, random.Random(0)) is None


def test_require_invariant_adds_an_invariant() -> None:
    name, p, out = _first_applicable(require_invariant)
    assert len(out.objective.invariants) == len(p.objective.invariants) + 1


def test_remove_redundant_clue_drops_an_invariant() -> None:
    p = BY_NAME["synchronize"]()  # carries an equality invariant
    out = remove_redundant_clue(p, random.Random(0))
    assert out is not None
    assert len(out.objective.invariants) == len(p.objective.invariants) - 1


def test_remove_redundant_clue_none_without_invariants() -> None:
    p = BY_NAME["move"]()
    assert not p.objective.invariants
    assert remove_redundant_clue(p, random.Random(0)) is None
