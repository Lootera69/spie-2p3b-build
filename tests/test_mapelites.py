"""Phase 4.5 tests — hand-rolled deterministic MAP-Elites.

The archive is proven to (a) map puzzles to stable, documented niches and rank them by the fixed
novelty+elegance blend, (b) admit a candidate *only* through the hard gates (validate -> verify ->
certify) — an uncertifiable mutant is rejected with the gate that turned it away, (c) place by
strict within-niche fitness (ties keep the incumbent), and (d) be **byte-reproducible**: two runs
with the same (seeds, iterations, seed) serialize identically, and every archived elite
re-certifies. The determinism run is the standing oracle, mirrored from the certificate tests.

Phase 5.2 (ARCHIVE completion) adds the roadmap-p14 record-keeping: every cell carries its
content-address ``puzzle_digest`` and the ``lineage`` of the mutation that produced it (``None``
for a seed); every rejected candidate is retained in ``Archive.rejections`` *in addition to* the
integer tally; and the write-only archive gains an inverse ``archive_from_json`` that round-trips
byte-for-byte and whose parsed cells recompute to their stored quality.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from spie import mapelites
from spie.certificate import certify
from spie.examples_src import BUILDERS
from spie.operators import FAMILIES, add_decoy_action
from spie.quality import descriptors, quality_to_json
from spie.serialize import dumps, puzzle_from_json
from spie.validate import validate
from spie.verify import verify
from test_strategy import greedy_trap

BY_NAME = {b.__name__: b for b in BUILDERS}


# --- Niche / fitness helpers (pure) ---------------------------------------------------------


def test_bucket_is_first_fit_index() -> None:
    b = (1, 3, 7)
    assert mapelites._bucket(0, b) == 0
    assert mapelites._bucket(1, b) == 0
    assert mapelites._bucket(2, b) == 1
    assert mapelites._bucket(7, b) == 2
    assert mapelites._bucket(8, b) == 3  # past the last boundary -> len(boundaries)


def test_niche_and_fitness_are_read_from_the_quality_vector() -> None:
    q = descriptors(BY_NAME["move"]())
    d = q.difficulty
    assert mapelites.niche_of(q) == (
        d.band,
        mapelites._bucket(d.belief_count, mapelites._BELIEF_BUCKETS),
        mapelites._bucket(d.plan_branching, mapelites._BRANCH_BUCKETS),
        mapelites._bucket(q.strategy.backtracks, mapelites._BACKTRACK_BUCKETS),
    )
    assert mapelites.fitness_of(q) == round(
        mapelites._W_NOVELTY * q.novelty.score + mapelites._W_ELEGANCE * q.elegance.score, 6
    )


# --- Gates: a candidate enters only by proving itself ---------------------------------------


def test_backtracks_axis_separates_deceptive_from_clean_puzzles() -> None:
    # Phase 5.5: the fourth niche axis is the strategy solver's physical backtracks. A clean
    # puzzle (never backtracks) and a deceptive one (lured into a dead end, backtracks >= 1) must
    # land in *different* backtracks buckets -- so the archive keeps both in the same
    # difficulty/belief/branching cell instead of one crowding the other out. This proves the
    # axis fires (checked, not assumed).
    clean_q = descriptors(BY_NAME["move"]())
    deceptive_q = descriptors(greedy_trap())
    assert clean_q.strategy.backtracks == 0
    assert deceptive_q.strategy.backtracks >= 1
    clean_axis = mapelites.niche_of(clean_q)[3]
    deceptive_axis = mapelites.niche_of(deceptive_q)[3]
    assert clean_axis == 0  # clean puzzle -> backtracks bucket 0
    assert deceptive_axis >= 1  # deceptive puzzle -> a distinct, higher bucket
    assert clean_axis != deceptive_axis


def test_evaluate_admits_a_corpus_puzzle_and_builds_its_cell() -> None:
    p = BY_NAME["move"]()
    adm = mapelites.evaluate(p)
    assert adm.ok and adm.reason == "admitted" and adm.cell is not None
    q = descriptors(p)
    assert adm.cell.niche == mapelites.niche_of(q)
    assert adm.cell.fitness == mapelites.fitness_of(q)
    assert adm.cell.certificate_digest == mapelites._certificate_digest(p)


def test_evaluate_rejects_a_malformed_candidate_at_the_validate_gate() -> None:
    bad = replace(BY_NAME["move"](), initial={})  # missing initial values -> validate fails
    adm = mapelites.evaluate(bad)
    assert not adm.ok and adm.reason == "invalid" and adm.cell is None


def test_evaluate_rejects_an_uncertifiable_mutant_at_a_hard_gate() -> None:
    # A decoy is a genuine-but-inert affordance: validate-clean, but verify's gates reject it.
    mutant = add_decoy_action(BY_NAME["move"](), random.Random(0))
    assert mutant is not None and validate(mutant) == []  # well-formed by construction
    adm = mapelites.evaluate(mutant)
    assert not adm.ok and adm.reason == "verify-failed" and adm.cell is None


def test_place_ties_keep_the_incumbent() -> None:
    archive = mapelites.Archive(seed=0, iterations=0)
    p = BY_NAME["move"]()
    first = mapelites.place(archive, p)
    assert first.ok and archive.tally == {"placed": 1}
    incumbent = archive.cells[first.cell.niche]
    again = mapelites.place(archive, p)  # identical fitness -> not strictly higher
    assert not again.ok and again.reason == "dominated"
    assert archive.cells[first.cell.niche] is incumbent  # unchanged
    assert archive.tally == {"placed": 1, "dominated": 1}


# --- A bounded, fully-seeded run: determinism + admission discipline -------------------------

# One expensive run, shared: three seeds in distinct niches (bands 1/2/4) + a small budget,
# executed twice so the determinism oracle and the structural checks share the cost.
_SEED_NAMES = ("move", "which_door", "combination_lock")
_ITERATIONS = 4


@pytest.fixture(scope="module")
def evolved() -> tuple[mapelites.Archive, mapelites.Archive]:
    def seeds() -> list:
        return [BY_NAME[n]() for n in _SEED_NAMES]

    return (
        mapelites.evolve(seeds(), iterations=_ITERATIONS, seed=0),
        mapelites.evolve(seeds(), iterations=_ITERATIONS, seed=0),
    )


def test_evolve_is_byte_reproducible(evolved) -> None:
    a, b = evolved
    assert dumps(mapelites.archive_to_json(a)) == dumps(mapelites.archive_to_json(b))


def test_evolve_tally_accounts_for_every_seed_and_iteration(evolved) -> None:
    a, _ = evolved
    assert sum(a.tally.values()) == len(_SEED_NAMES) + _ITERATIONS
    # This run exercises the full placement machinery: fresh cells, a fitness replacement, and
    # gate rejections all occur (a divergence here means a mechanic silently stopped firing).
    assert a.tally.get("placed", 0) >= 1
    assert a.tally.get("replaced", 0) >= 1
    assert a.tally.get("verify-failed", 0) >= 1


def test_every_archived_elite_is_proven_and_correctly_niched(evolved) -> None:
    a, _ = evolved
    assert len(a.cells) >= 2  # the distinct-niche seeds guarantee real diversity
    for niche, cell in a.cells.items():
        assert validate(cell.puzzle) == []
        assert verify(cell.puzzle).ok
        assert certify(cell.puzzle).solvable
        q = descriptors(cell.puzzle)
        assert cell.niche == niche == mapelites.niche_of(q)
        assert cell.fitness == mapelites.fitness_of(q)
        assert cell.certificate_digest == mapelites._certificate_digest(cell.puzzle)


def test_archive_json_is_niche_sorted_and_puzzles_round_trip(evolved) -> None:
    a, _ = evolved
    j = mapelites.archive_to_json(a)
    niches = [tuple(cell["niche"]) for cell in j["cells"]]
    assert niches == sorted(niches)  # canonical order for byte-stable serialization
    for cell in j["cells"]:
        puzzle = puzzle_from_json(cell["puzzle"])
        assert mapelites.niche_of(descriptors(puzzle)) == tuple(cell["niche"])


# --- Phase 5.2: lineage, rejection history, content-addressing, read-back -------------------

_REJECTION_REASONS = ("invalid", "verify-failed", "unsolvable", "dominated")


def test_puzzle_digest_is_stable_and_addresses_the_puzzle_not_the_proof() -> None:
    # Content-addressing (roadmap p14): a stable sha256 over the puzzle's own canonical JSON,
    # distinct from the certificate digest (which addresses the proof), and content-sensitive.
    p = BY_NAME["move"]()
    d1 = mapelites._puzzle_digest(p)
    assert d1 == mapelites._puzzle_digest(p) and len(d1) == 64  # deterministic sha256 hex
    assert d1 != mapelites._certificate_digest(p)  # the puzzle, not its certificate
    assert mapelites._puzzle_digest(BY_NAME["which_door"]()) != d1  # tracks content


def test_seed_cells_have_no_lineage_and_mutants_record_their_provenance(evolved) -> None:
    a, _ = evolved
    op_family = {op.__name__: fam for fam, ops in FAMILIES.items() for op in ops}
    lineaged = [c for c in a.cells.values() if c.lineage is not None]
    assert lineaged, "the deterministic run places at least one mutant elite"
    for cell in lineaged:
        ln = cell.lineage
        assert ln.generation >= 1  # a seed is generation 0; a mutation adds one
        assert ln.family in FAMILIES  # a real invention family
        assert op_family[ln.operator] == ln.family  # the operator belongs to that family
        assert len(ln.parent_digest) == 64  # the parent puzzle's content address
        assert isinstance(ln.parent_niche, tuple) and len(ln.parent_niche) == 4


def test_place_records_a_rejected_decoy_in_the_history() -> None:
    # The plan's targeted case: a decoy mutant is validate-clean but verify-rejected, and must be
    # retained in the rejection history with its reason and content digest (a bare candidate, so
    # no lineage), *in addition to* the integer tally.
    archive = mapelites.Archive(seed=0, iterations=0)
    mutant = add_decoy_action(BY_NAME["move"](), random.Random(0))
    assert mutant is not None
    adm = mapelites.place(archive, mutant)
    assert not adm.ok and adm.reason == "verify-failed"
    assert archive.tally == {"verify-failed": 1}  # tally semantics unchanged
    assert len(archive.rejections) == 1
    rej = archive.rejections[0]
    assert rej.reason == "verify-failed"
    assert rej.puzzle_digest == mapelites._puzzle_digest(mutant)
    assert rej.detail  # names the failing gate(s)
    assert rej.lineage is None  # placed without a lineage


def test_rejection_history_is_parallel_to_the_tally(evolved) -> None:
    # rejections must record exactly the outcomes the tally counts as rejections (not placed /
    # replaced / no-op), so the two records never drift apart.
    a, _ = evolved
    assert a.rejections, "the run rejects at least one candidate at a gate"
    rejected_by_tally = sum(a.tally.get(r, 0) for r in _REJECTION_REASONS)
    assert len(a.rejections) == rejected_by_tally
    for rej in a.rejections:
        assert rej.reason in _REJECTION_REASONS
        assert len(rej.puzzle_digest) == 64
        assert isinstance(rej.detail, str)


def test_archive_round_trips_through_json(evolved) -> None:
    # The 5.2 deliverable: the archive is no longer write-only. archive_from_json reconstructs an
    # equal archive (structural byte-inverse) AND each parsed cell's descriptors recompute to the
    # stored quality (belt-and-suspenders: structural inverse + recompute-match).
    a, _ = evolved
    j = mapelites.archive_to_json(a)
    back = mapelites.archive_from_json(j)
    assert dumps(mapelites.archive_to_json(back)) == dumps(j)  # byte-identical inverse
    assert back.seed == a.seed and back.iterations == a.iterations
    assert back.tally == a.tally
    assert set(back.cells) == set(a.cells)
    for niche, cell in back.cells.items():
        orig = a.cells[niche]
        assert quality_to_json(descriptors(cell.puzzle)) == quality_to_json(cell.quality)
        assert cell.puzzle_digest == orig.puzzle_digest == mapelites._puzzle_digest(cell.puzzle)
        assert cell.certificate_digest == orig.certificate_digest
        assert cell.lineage == orig.lineage  # lineage survives the round-trip by value
    assert len(back.rejections) == len(a.rejections)
    for r_back, r_orig in zip(back.rejections, a.rejections, strict=True):
        assert r_back == r_orig  # each rejection (with its lineage) round-trips by value
