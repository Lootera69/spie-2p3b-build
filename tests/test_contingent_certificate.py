"""Phase 3.4 — the contingent certificate: epistemic conformance, cross-solver evidence, and
plan serialization, all guarded by the fully-observable reduction anchor.

Four things are proved here:

1. **Reduction.** On the 14 fully-observable corpus puzzles the epistemic conformance check
   collapses to the linear one — a singleton ``B0`` whose single world replays to exactly the
   trace :func:`spie.search.canonical_solution` returns — and their certificates carry none of
   the epistemic fields (byte-identical to Phase 1/2).
2. **Contingent certification.** The genuinely epistemic ``which_switch`` fixtures certify with
   a branching plan, Method A ≡ Method B evidence recorded, and every ``B0`` world replayed to
   the goal.
3. **Serialization.** The contingent plan and per-world replay round-trip byte-identically and
   reconstruct an equal certificate.
4. **The obligations bite.** ``check_plan_conformance`` fails a plan that is unsafe in some
   world, and the uniformity audit fails clairvoyant behaviour — neither is assumed away.
"""

from __future__ import annotations

import json

from epistemic_fixtures import which_switch, which_switch_three
from spie import epistemic, search
from spie.certificate import certify
from spie.conformance import _check_uniformity, check_conformance, check_plan_conformance
from spie.examples_src import BUILDERS
from spie.results import Plan
from spie.serialize import (
    certificate_from_json,
    certificate_to_json,
    dumps,
    plan_from_json,
    plan_to_json,
)

EPISTEMIC_FIXTURES = (which_switch, which_switch_three)


# ---------------------------------------------------------------------------
# 1. Reduction anchor — the fully-observable corpus
# ---------------------------------------------------------------------------


def test_plan_conformance_reduces_to_linear_on_corpus():
    """On every fully-observable puzzle, replaying the contingent plan over ``B0`` is a single
    world whose induced trace is exactly the canonical linear solution, and it is uniform."""
    for builder in BUILDERS:
        puzzle = builder()
        if puzzle.initial_belief:  # hidden puzzles branch by design — checked in the fixtures below
            continue
        plan = epistemic.canonical_plan(puzzle)
        pc = check_plan_conformance(puzzle, plan)
        linear = check_conformance(puzzle, search.canonical_solution(puzzle))

        assert pc.ok, f"{puzzle.id}: plan conformance failed: {pc.detail}"
        assert pc.uniform, f"{puzzle.id}: singleton belief cannot be non-uniform"
        assert pc.reached_goal_all
        assert len(pc.world_replays) == 1, f"{puzzle.id}: |B0| must be 1 when nothing is hidden"
        replay = pc.world_replays[0]
        assert replay.ok and replay.reached_goal
        assert replay.trace == tuple(search.canonical_solution(puzzle).trace)
        # The linear checker and the contingent checker agree on the verdict.
        assert pc.ok == linear.ok


def test_corpus_certificates_carry_no_epistemic_fields():
    """The reduction anchor at the certificate level: fully-observable certificates keep the
    Phase-1/2 shape — no plan, no epistemic evidence, no world replays — so their canonical
    JSON is byte-identical to before Phase 3.4 (the epistemic keys are simply absent)."""
    for builder in BUILDERS:
        cert = certify(builder())
        if builder().initial_belief:  # epistemic certificates legitimately carry these fields
            continue
        assert cert.plan is None
        assert cert.epistemic == ()
        assert cert.world_replays == ()
        blob = certificate_to_json(cert)
        assert "plan" not in blob
        assert "epistemic" not in blob
        assert "world_replays" not in blob
        # Three independent (fully-observable) solvers still stand behind the claim.
        assert len(cert.solvers) == 3


# ---------------------------------------------------------------------------
# 2. Contingent certification — the epistemic fixtures
# ---------------------------------------------------------------------------


def test_which_switch_certifies_as_contingent():
    puzzle = which_switch()
    cert = certify(puzzle)

    assert cert.solvable
    assert cert.conformance_ok
    assert cert.warnings == [], f"unexpected warnings (A/B disagreement?): {cert.warnings}"
    # The epistemic solver is credited, not the linear Z3-BMC one.
    assert cert.solver == epistemic.SOLVER_NAME
    assert cert.horizon == 2
    assert cert.unique is True

    # A genuine branching plan: the linear spine is empty, the policy tree carries the proof.
    assert cert.plan is not None
    assert not cert.plan.is_leaf
    assert cert.plan.linear_trace() is None
    assert cert.plan.depth() == 2
    assert cert.solution == ()
    assert cert.plan.action == "probe"
    assert len(cert.plan.branches) == 2  # one per observed value of the hidden target


def test_which_switch_records_A_equals_B_evidence():
    cert = certify(which_switch())
    assert len(cert.epistemic) == 2
    names = {e.name for e in cert.epistemic}
    assert names == {epistemic.SOLVER_NAME, "z3-epistemic-bmc"}
    # The two independent methods agree on the whole cross-checked triple.
    a, b = cert.epistemic
    assert (a.solvable, a.depth, a.unique) == (b.solvable, b.depth, b.unique)
    assert a.solvable and a.depth == 2 and a.unique


def test_which_switch_replays_every_world_to_goal():
    cert = certify(which_switch())
    # |B0| = 2 (target ∈ {0, 1}); both worlds must reach the goal legally.
    assert len(cert.world_replays) == 2
    for replay in cert.world_replays:
        assert replay.ok, f"world {replay.world} not ok"
        assert replay.reached_goal
    worlds = {r.world for r in cert.world_replays}
    assert len(worlds) == 2  # the two worlds are distinct (hidden target differs)


def test_which_switch_three_certifies_across_three_worlds():
    cert = certify(which_switch_three())
    assert cert.solvable and cert.conformance_ok
    assert cert.warnings == []
    assert cert.horizon == 2 and cert.unique is True
    assert len(cert.world_replays) == 3  # target ∈ {0, 1, 2}
    assert all(r.ok and r.reached_goal for r in cert.world_replays)
    assert cert.plan is not None and cert.plan.depth() == 2
    # probe splits three ways here.
    assert len(cert.plan.branches) == 3


# ---------------------------------------------------------------------------
# 3. Serialization — plan + replays round-trip, byte-reproducibly
# ---------------------------------------------------------------------------


def test_contingent_certificate_round_trips():
    for builder in EPISTEMIC_FIXTURES:
        cert = certify(builder())
        once = dumps(certificate_to_json(cert))
        restored = certificate_from_json(json.loads(once))
        twice = dumps(certificate_to_json(restored))
        assert once == twice, f"{builder().id}: certificate not byte-reproducible"
        # Full structural equality survives the JSON round-trip.
        assert restored == cert


def test_plan_round_trips_byte_identically():
    for builder in EPISTEMIC_FIXTURES:
        plan = epistemic.canonical_plan(builder())
        assert plan is not None
        restored = plan_from_json(json.loads(dumps(plan_to_json(plan))))
        assert restored == plan


def test_contingent_certification_is_deterministic():
    for builder in EPISTEMIC_FIXTURES:
        first = dumps(certificate_to_json(certify(builder())))
        second = dumps(certificate_to_json(certify(builder())))
        assert first == second, f"{builder().id}: epistemic certificate is not reproducible"


# ---------------------------------------------------------------------------
# 4. The obligations genuinely bite — negative controls
# ---------------------------------------------------------------------------


def test_plan_conformance_rejects_a_world_unsafe_plan():
    """A plausible-looking plan that skips sensing and commits to ``flip0`` is safe in the
    ``target=0`` world but *illegal* in the ``target=1`` world. Per-world replay must catch
    that: goal not reached on all, and the offending world's replay flagged not-ok."""
    puzzle = which_switch()
    # In the target=0 world, flip0 sets done=1; its post-observation over the visible ["done"]
    # is (1,), leading to a goal leaf. In the target=1 world flip0's precondition fails first.
    reckless = Plan(action="flip0", branches=(((1,), Plan(action=None)),))

    pc = check_plan_conformance(puzzle, reckless)
    assert not pc.ok
    assert not pc.reached_goal_all
    bad = [r for r in pc.world_replays if not r.ok]
    assert bad, "the target=1 world should fail the replay"
    assert any(r.ok for r in pc.world_replays), "the target=0 world should still succeed"


def test_uniformity_audit_flags_clairvoyant_behaviour():
    """The uniformity audit is an independent check on the *replayed* behaviour, so exercise it
    directly: two worlds that produced identical observations but took different first actions
    are clairvoyant and must be rejected; the same observations with a later, information-split
    branch are fine."""
    done0 = (("done", 0),)

    # Clairvoyant: identical initial observation, yet different first actions.
    clairvoyant = [
        ([done0], ["flip0"]),
        ([done0], ["flip1"]),
    ]
    uniform, detail = _check_uniformity(clairvoyant)
    assert not uniform and "uniformity" in detail

    # Legitimate: same first observation + action (probe), branch only after target is sensed.
    lawful = [
        ([done0, (("done", 0), ("target", 0))], ["probe", "flip0"]),
        ([done0, (("done", 0), ("target", 1))], ["probe", "flip1"]),
    ]
    ok, _ = _check_uniformity(lawful)
    assert ok
