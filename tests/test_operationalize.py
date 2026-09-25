"""Phase 4.3 tests — Operationalize (rule graph -> executable Puzzle).

Covers the full third pipeline stage: the compiled puzzle validates clean, certifies solvable +
unique through the ordinary gates (no privileged path), the pipeline is deterministic
(byte-identical JSON for the same rule graph + seed), and epistemic/temporal modifiers are
refused rather than emitted unproven. Also exercises the end-to-end Sense->…->Operationalize
path on concrete concepts."""

from __future__ import annotations

import pytest

from spie.afford import MechanicKind, RuleGraph, afford, blend
from spie.certificate import certify
from spie.concepts import expand, sense
from spie.operationalize import SUPPORTED_MODIFIERS, operationalize
from spie.serialize import dumps, puzzle_to_json
from spie.validate import validate
from spie.verify import verify


def _rg(base: MechanicKind, modifiers: tuple[MechanicKind, ...], length: int = 3) -> RuleGraph:
    """A hand-built well-formed rule graph with synthetic provenance for every mechanic."""
    prov = {base: base.value}
    prov.update({m: m.value for m in modifiers})
    rg = RuleGraph(base=base, modifiers=modifiers, provenance=prov, length=length)
    rg.check()
    return rg


def _assert_certifiable(rg: RuleGraph) -> None:
    """A rule graph must operationalize into a puzzle that validates clean and passes every
    verify gate (which itself runs the full cross-solver certificate)."""
    puzzle = operationalize(rg, seed=7)
    assert validate(puzzle) == [], f"validation findings: {validate(puzzle)}"
    report = verify(puzzle)
    assert report.ok, f"verify failed: {report}"
    cert = certify(puzzle)
    assert cert.solvable
    assert cert.unique
    assert cert.conformance_ok


def test_connect_plain_certifies() -> None:
    _assert_certifiable(_rg(MechanicKind.CONNECT, ()))


def test_chain_plain_certifies() -> None:
    _assert_certifiable(_rg(MechanicKind.CHAIN, ()))


@pytest.mark.parametrize("mod", sorted(SUPPORTED_MODIFIERS, key=lambda m: m.value))
def test_each_modifier_certifies_on_chain(mod: MechanicKind) -> None:
    _assert_certifiable(_rg(MechanicKind.CHAIN, (mod,)))


@pytest.mark.parametrize("mod", sorted(SUPPORTED_MODIFIERS, key=lambda m: m.value))
def test_each_modifier_certifies_on_connect(mod: MechanicKind) -> None:
    _assert_certifiable(_rg(MechanicKind.CONNECT, (mod,)))


def test_all_supported_modifiers_together_certify() -> None:
    mods = tuple(sorted(SUPPORTED_MODIFIERS, key=lambda m: m.value))
    _assert_certifiable(_rg(MechanicKind.CHAIN, mods, length=len(mods)))
    _assert_certifiable(_rg(MechanicKind.CONNECT, mods, length=len(mods)))


def test_operationalize_is_deterministic() -> None:
    rg = _rg(MechanicKind.CONNECT, (MechanicKind.CONSUME, MechanicKind.NEGATE))
    a = operationalize(rg, seed=3)
    b = operationalize(rg, seed=3)
    assert dumps(puzzle_to_json(a)) == dumps(puzzle_to_json(b))


def test_seed_only_affects_identity_not_structure() -> None:
    rg = _rg(MechanicKind.CHAIN, (MechanicKind.NEGATE,))
    p0 = operationalize(rg, seed=0)
    p1 = operationalize(rg, seed=1)
    assert p0.id != p1.id
    assert p0.seed != p1.seed
    # The mechanic content (actions/variables/objective) is identical regardless of seed.
    assert p0.actions == p1.actions
    assert p0.variables == p1.variables
    assert p0.objective == p1.objective


def test_defers_epistemic_modifiers() -> None:
    for mod in (MechanicKind.REVEAL, MechanicKind.DELAY):
        rg = _rg(MechanicKind.CHAIN, (mod,))
        with pytest.raises(NotImplementedError):
            operationalize(rg, seed=0)


def test_pipeline_end_to_end_bridge() -> None:
    # bridge -> path/travel : CONNECT only, a bare movement puzzle.
    rg = blend(afford(expand(sense("bridge"), depth=1)))
    assert rg.base == MechanicKind.CONNECT
    assert rg.modifiers == ()
    _assert_certifiable(rg)


def test_pipeline_end_to_end_fuel() -> None:
    # fuel -> resource/travel/deplete : CONNECT base + CONSUME modifier.
    rg = blend(afford(expand(sense("fuel"), depth=1)))
    assert rg.base == MechanicKind.CONNECT
    assert MechanicKind.CONSUME in rg.modifiers
    _assert_certifiable(rg)


def test_pipeline_end_to_end_door() -> None:
    # door -> barrier/travel : CONNECT base + NEGATE modifier.
    rg = blend(afford(expand(sense("door"), depth=1)))
    assert rg.base == MechanicKind.CONNECT
    assert MechanicKind.NEGATE in rg.modifiers
    _assert_certifiable(rg)


def test_pipeline_validates_clean_over_supported_kb() -> None:
    # Every curated concept whose blended rule graph uses only supported modifiers must
    # operationalize into a validation-clean puzzle (the unsupported ones are explicitly deferred).
    # Scoped to the curated core, not all of ``KB``: the additive ConceptNet layer is certify-gated
    # exhaustively offline by ``tools/conceptnet_build``, so suite runtime stays independent of
    # vocabulary size without opening a soundness hole.
    from spie.concepts import CURATED_WORDS

    seen = False
    for name in CURATED_WORDS:
        rg = blend(afford(expand(sense(name), depth=1)))
        if any(m not in SUPPORTED_MODIFIERS for m in rg.modifiers):
            with pytest.raises(NotImplementedError):
                operationalize(rg, seed=0)
            continue
        seen = True
        assert validate(operationalize(rg, seed=0)) == []
    assert seen  # at least some concepts are fully supported
