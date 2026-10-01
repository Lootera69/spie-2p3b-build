"""Phase 0 tests — cross-run de-duplication ("generate a unique puzzle each time").

Two things are proven. (1) The *structural* digest is a mechanics-only content address: it is
blind to a puzzle's generated id / title / notes / seed (so a renamed puzzle is recognised as the
same puzzle to play) yet tracks any change to the playable mechanics. (2) Wired into ``evolve`` via
the opt-in ``history`` set it stays *thesis-safe and byte-reproducible*: ``history=None`` is
byte-identical to the historical search, an empty history never changes which puzzles occupy cells,
a run fed a prior archive's :func:`archive_digests` never re-emits one of those puzzles as a fresh
elite (the re-generated candidates are rejected as ``"duplicate"`` before the gate ever runs), every
surviving elite still clears the full validate -> verify -> certify gate, and two identical
(seeds, iterations, seed, history) runs serialize identically.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from spie import mapelites
from spie.certificate import certify
from spie.examples_src import BUILDERS
from spie.operators import add_decoy_action
from spie.serialize import dumps
from spie.validate import validate
from spie.verify import verify

BY_NAME = {b.__name__: b for b in BUILDERS}

_SEED_NAMES = ("move", "which_door", "combination_lock")
_ITERATIONS = 6


def _seeds() -> list:
    return [BY_NAME[n]() for n in _SEED_NAMES]


def _occupancy(archive: mapelites.Archive) -> dict:
    """niche -> content digest of its elite: which puzzle sits in which cell (ignoring tallies)."""
    return {niche: cell.puzzle_digest for niche, cell in archive.cells.items()}


# --- the structural digest is a mechanics-only content address ----------------------------------


def test_structural_digest_ignores_identity_and_presentation_metadata() -> None:
    p = BY_NAME["move"]()
    renamed = replace(p, id="renamed", title="Renamed", notes="fresh provenance", seed=999)
    # Same mechanics under a different name/seed -> one structural digest ...
    assert mapelites._structural_digest(p) == mapelites._structural_digest(renamed)
    assert len(mapelites._structural_digest(p)) == 64
    # ... but the full puzzle digest is a distinct notion that DOES track the metadata.
    assert mapelites._puzzle_digest(p) != mapelites._puzzle_digest(renamed)


def test_structural_digest_tracks_the_playable_mechanics() -> None:
    p = BY_NAME["move"]()
    assert mapelites._structural_digest(p) != mapelites._structural_digest(BY_NAME["which_door"]())
    # A mechanical mutation (an added action) changes the mechanics -> changes the digest.
    mutant = add_decoy_action(p, random.Random(0))
    assert mutant is not None
    assert mapelites._structural_digest(mutant) != mapelites._structural_digest(p)


# --- wired into evolve: opt-in, thesis-safe, byte-reproducible -----------------------------------


@pytest.fixture(scope="module")
def chained() -> tuple[mapelites.Archive, set[str], mapelites.Archive]:
    # One run, then a second run fed the first's digests over the *same* candidate stream (seed 0):
    # every elite the first run kept is re-generated and must now be turned away as a duplicate.
    run1 = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0)
    history = mapelites.archive_digests(run1)
    run2 = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, history=history)
    return run1, history, run2


def test_history_none_is_byte_identical_to_the_historical_search() -> None:
    a = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0)
    b = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, history=None)
    assert dumps(mapelites.archive_to_json(a)) == dumps(mapelites.archive_to_json(b))


def test_empty_history_preserves_cell_occupancy() -> None:
    # Turning de-dup ON with nothing pre-seen only ever relabels a would-be "dominated" repeat as
    # "duplicate"; a structural repeat can never out-rank its identical incumbent, so WHICH puzzle
    # occupies each cell is unchanged.
    off = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, history=None)
    on = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, history=set())
    assert _occupancy(off) == _occupancy(on)


def test_archive_digests_are_one_per_cell_and_structural(chained) -> None:
    run1, _history, _run2 = chained
    digests = mapelites.archive_digests(run1)
    # Distinct cells are mechanically distinct (identical mechanics share a niche), so the digests
    # are collision-free across cells.
    assert len(digests) == len(run1.cells) >= 2
    assert all(len(d) == 64 for d in digests)


def test_chained_run_never_re_emits_a_puzzle_from_history(chained) -> None:
    _run1, history, run2 = chained
    # The dedup path actually fired: re-generated prior elites were rejected before the gate.
    assert run2.tally.get("duplicate", 0) >= 1
    # No freshly generated (mutant) elite is a puzzle we had already produced.
    generated = [c for c in run2.cells.values() if c.lineage is not None]
    for cell in generated:
        assert mapelites._structural_digest(cell.puzzle) not in history
    # Every "duplicate" rejection is recorded in the history, not just tallied.
    dup_rejections = [r for r in run2.rejections if r.reason == "duplicate"]
    assert len(dup_rejections) == run2.tally["duplicate"]
    for r in dup_rejections:
        assert r.lineage is not None and len(r.puzzle_digest) == 64


def test_de_dup_never_weakens_the_formal_gate(chained) -> None:
    # The thesis guard: history changes only *what is tried*; every surviving elite still passes
    # the full validate -> verify -> certify gate, exactly as under the un-deduplicated search.
    _run1, _history, run2 = chained
    assert run2.cells
    for cell in run2.cells.values():
        assert validate(cell.puzzle) == []
        assert verify(cell.puzzle).ok
        assert certify(cell.puzzle).solvable


def test_history_driven_run_is_byte_reproducible(chained) -> None:
    _run1, history, _run2 = chained
    a = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, history=set(history))
    b = mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, history=set(history))
    assert dumps(mapelites.archive_to_json(a)) == dumps(mapelites.archive_to_json(b))


def test_evolve_copies_history_and_never_mutates_the_callers_set(chained) -> None:
    _run1, history, _run2 = chained
    passed = set(history)
    snapshot = set(passed)
    mapelites.evolve(_seeds(), iterations=_ITERATIONS, seed=0, history=passed)
    assert passed == snapshot  # evolve works on its own copy; the caller's history is untouched
