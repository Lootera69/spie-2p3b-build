"""Quality vector (Phase 2, D4 + Phase 3): the descriptors must be deterministic, in range,
and track the structural facts they claim to measure. Determinism matters most — MAP-Elites
will key niches on these numbers, so a puzzle must map to the same vector every time it is
scored. Phase 3 adds epistemic proxies (``|B0|``, sensing count, plan branching, depth spread,
information gain) that vanish to degenerate values on a fully-observable puzzle, and turns
fairness into a proven uniformity audit rather than a ``1 - trap_density`` estimate.
"""

from __future__ import annotations

import dataclasses

from epistemic_fixtures import which_switch, which_switch_three
from spie import fingerprint
from spie.examples_src import BUILDERS, move, two_solutions
from spie.expr import Const, Eq, Node
from spie.ir import Action, Assign
from spie.quality import descriptors, quality_to_json

CORPUS = fingerprint.corpus_fingerprints([b() for b in BUILDERS])


def test_quality_vector_is_deterministic():
    for builder in BUILDERS:
        p = builder()
        first = quality_to_json(descriptors(p, CORPUS))
        for _ in range(3):
            assert quality_to_json(descriptors(p, CORPUS)) == first


def test_descriptor_ranges():
    for builder in BUILDERS:
        q = descriptors(builder(), CORPUS)
        assert 1 <= q.difficulty.band <= 5
        assert 0.0 <= q.novelty.score <= 1.0
        assert 0.0 <= q.elegance.score <= 1.0
        assert 0.0 <= q.elegance.minimality_ratio <= 1.0
        assert 0.0 <= q.fairness.score <= 1.0
        # Fairness is now a proven property, never an estimate: certified plans are uniform by
        # construction, so every corpus puzzle is decided (not partial) and audited uniform.
        assert not q.fairness.partial
        assert q.fairness.uniform


def test_fully_observable_epistemic_proxies_are_degenerate():
    # On a fully-observable puzzle the epistemic proxies take their reduction-anchor values:
    # a singleton belief, no sensing, no genuine branching, no depth spread or information gain.
    d = descriptors(move(), CORPUS).difficulty
    assert d.belief_count == 1
    assert d.sensing_actions == 0
    assert d.plan_branching == 1
    assert d.depth_spread == 0
    assert d.information_gain == 0.0


def test_hidden_state_lifts_the_epistemic_proxies():
    # which_switch hides one bit (target in {0,1}) resolved by a single sensing branch.
    d = descriptors(which_switch(), CORPUS).difficulty
    assert d.belief_count == 2
    assert d.sensing_actions == 1
    assert d.plan_branching == 2
    assert d.information_gain == 1.0  # log2(2 leaves) = one bit resolved
    # which_switch_three hides a trit (target in {0,1,2}); more worlds, more information gained.
    d3 = descriptors(which_switch_three(), CORPUS).difficulty
    assert d3.belief_count == 3
    assert d3.plan_branching >= 2
    assert d3.information_gain > 1.0


def test_fairness_is_audited_uniform_under_hidden_state():
    for builder in (which_switch, which_switch_three):
        q = descriptors(builder(), CORPUS)
        assert q.fairness.uniform
        assert q.fairness.score == 1.0
        assert not q.fairness.partial


def test_novelty_names_a_distinct_neighbour():
    for builder in BUILDERS:
        p = builder()
        q = descriptors(p, CORPUS)
        assert q.novelty.nearest_id is not None
        assert q.novelty.nearest_id != p.id


def test_fingerprint_ignores_surface_metadata():
    # Renaming a puzzle (id/title/notes) changes no mechanic, so the fingerprint is identical.
    p = move()
    renamed = dataclasses.replace(p, id="renamed", title="Different", notes="x")
    va, vb = fingerprint.fingerprint(p).vector, fingerprint.fingerprint(renamed).vector
    assert va == vb
    assert fingerprint.cosine_distance(va, vb) == 0.0


def test_free_choice_proxy_tracks_branching():
    # The fork has a genuine shortest-path decision; the linear corridor has none.
    assert descriptors(two_solutions(), CORPUS).difficulty.free_choices >= 1
    assert descriptors(move(), CORPUS).difficulty.free_choices == 0


def _with_redundant_action(p):
    dead = Action(
        name="noop", precondition=Eq(Const(0), Const(1)), effects=(Assign("pos", Node("A")),)
    )
    return dataclasses.replace(p, id="fx_redundant_quality", actions=p.actions + (dead,))


def test_elegance_penalises_a_redundant_element():
    clean = descriptors(move(), CORPUS).elegance
    bloated = descriptors(_with_redundant_action(move()), CORPUS).elegance
    assert clean.minimality_ratio == 1.0
    assert bloated.minimality_ratio < 1.0
    assert bloated.score < clean.score


def test_strategy_and_surprise_are_reported_in_range():
    # Phase 5.1 EVALUATION additions: reported descriptors, present and in range on every puzzle.
    for builder in BUILDERS:
        q = descriptors(builder(), CORPUS)
        s = q.strategy
        assert s.inference_depth >= 0 and s.branching_faced >= 0 and s.backtracks >= 0
        assert s.memory_load >= 0 and s.steps_taken >= s.inference_depth
        assert isinstance(s.solvable, bool) and isinstance(s.complete, bool)
        su = q.surprise
        assert 0.0 <= su.score <= 1.0
        assert su.pivot_index >= -1
        assert su.pivot_kind in ("none", "plan-flip", "belief-collapse")
        assert su.prediction_error >= 0.0 and su.bits_resolved >= 0.0 and su.regret_steps >= 0


def test_quality_to_json_carries_the_strategy_and_surprise_blocks():
    j = quality_to_json(descriptors(move(), CORPUS))
    assert set(j["strategy"]) == {
        "solvable", "inference_depth", "branching_faced", "backtracks",
        "memory_load", "steps_taken", "complete",
    }
    assert set(j["surprise"]) == {
        "score", "pivot_index", "pivot_kind", "prediction_error",
        "bits_resolved", "regret_steps",
    }
