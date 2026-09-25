"""Suite-level tests (Milestone C): every hand-encoded puzzle certifies, with the expected
minimal horizon and uniqueness verdict, the corpus is clean, serialization round-trips, and
certification is deterministic (byte-identical canonical JSON on repeat runs).
"""

from __future__ import annotations

import json

from spie import epistemic
from spie.certificate import certify
from spie.examples_src import BUILDERS
from spie.serialize import (
    certificate_to_json,
    dumps,
    puzzle_from_json,
    puzzle_to_json,
)
from spie.solver import check_uniqueness, solve
from spie.validate import validate


def _horizon_and_unique(puzzle):
    """Minimal solving depth and uniqueness for either regime: the fully-observable Z3 BMC
    solver for singleton-belief puzzles, the belief-space epistemic solver when the puzzle
    declares hidden initial state. Both report the same two facts (depth, uniqueness), so the
    EXPECTED lock is regime-agnostic."""
    if puzzle.initial_belief:
        strong = epistemic.solve_strong(puzzle)
        return strong.depth, epistemic.check_uniqueness(puzzle).unique
    solution = solve(puzzle)
    return solution.horizon, check_uniqueness(puzzle, solution).unique

# Expected minimal horizon and uniqueness per puzzle — a regression lock on the design.
EXPECTED = {
    "01_move": (3, True),
    "02_transform": (2, True),
    "03_resource": (3, True),
    "04_lockkey": (4, True),
    "05_irreversible": (3, True),
    "06_synchronize": (5, True),
    "07_hidden": (2, True),
    "08_two_solutions": (2, False),
    "09_combined": (4, True),
    "10_pressure": (4, True),
    "11_signaled_trap": (3, True),
    "12_toll_bridge": (2, True),
    "13_two_agents": (3, True),
    "14_push_block": (3, True),
    # Phase 3.7 — epistemic + reset corpus (depth from the belief-space solver where hidden).
    "15_which_door": (3, True),
    "16_combination_lock": (3, True),
    "17_assembly_loop": (6, True),
    "18_scout_reset": (3, True),
    # Phase 3.9a — DELAYED (standing lagged observation, compiled to a hidden shift register).
    "19_delayed_signal": (3, True),
    # Phase 3.9b — REMEMBERED (transient sensed value latched into a persistent visible fact).
    "20_remembered_recall": (3, True),
}


def test_all_examples_certify():
    for builder in BUILDERS:
        cert = certify(builder())
        assert cert.solvable, f"{cert.puzzle_id} not solvable"
        assert cert.conformance_ok, f"{cert.puzzle_id} not conformant"
        assert cert.warnings == [], f"{cert.puzzle_id} has warnings: {cert.warnings}"


def test_expected_horizon_and_uniqueness():
    for builder in BUILDERS:
        puzzle = builder()
        horizon, unique = _horizon_and_unique(puzzle)
        exp_h, exp_u = EXPECTED[puzzle.id]
        assert horizon == exp_h, f"{puzzle.id}: horizon {horizon} != {exp_h}"
        assert unique is exp_u, f"{puzzle.id}: unique {unique} != {exp_u}"


def test_corpus_is_clean():
    for builder in BUILDERS:
        puzzle = builder()
        assert validate(puzzle) == [], f"{puzzle.id} has validation findings"


def test_serialization_round_trips():
    for builder in BUILDERS:
        puzzle = builder()
        once = dumps(puzzle_to_json(puzzle))
        restored = puzzle_from_json(json.loads(once))
        twice = dumps(puzzle_to_json(restored))
        assert once == twice, f"{puzzle.id} did not round-trip byte-identically"
        # Behaviour is preserved: the restored puzzle solves at the same depth (either regime).
        assert _horizon_and_unique(restored)[0] == _horizon_and_unique(puzzle)[0]


def test_certification_is_deterministic():
    for builder in BUILDERS:
        first = dumps(certificate_to_json(certify(builder())))
        second = dumps(certificate_to_json(certify(builder())))
        assert first == second, f"{builder().id} certificate is not reproducible"
