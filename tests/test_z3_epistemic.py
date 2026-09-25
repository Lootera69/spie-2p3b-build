"""Phase 3.3 — the symbolic epistemic solver (:mod:`spie.z3_epistemic`), Method B.

Gate **G2** lifted to partial observability: Method B (bounded multi-world SMT) must agree
with Method A (belief-space AND/OR fixpoint) on strong solvability, minimal worst-case depth,
and plan uniqueness — while sharing no solving code. Two anchors:

1. **Reduction.** On the 14 fully-observable corpus puzzles ``B0`` is a singleton, so Method B
   collapses to ordinary single-world BMC and must match not only Method A but also
   :mod:`spie.solver` (the Phase-2 ground truth) exactly — depth and uniqueness alike.

2. **Contingency.** On hidden-then-sense fixtures (which no single linear trace can solve)
   Method B must reproduce Method A's branching verdicts: solvable, worst-case depth, unique.
"""

from __future__ import annotations

from epistemic_fixtures import which_switch, which_switch_three
from spie import epistemic, solver, z3_epistemic
from spie.examples_src import BUILDERS

# --- reduction + agreement on the fully-observable corpus ----------------------------


def test_method_b_matches_method_a_on_corpus():
    for builder in BUILDERS:
        puzzle = builder()
        a = epistemic.solve_strong(puzzle)
        b = z3_epistemic.solve_strong(puzzle)
        assert b.solvable == a.solvable, puzzle.id
        assert b.depth == a.depth, f"{puzzle.id}: A depth {a.depth}, B depth {b.depth}"


def test_method_b_reduces_to_solver_on_corpus():
    """Fully-observable ⇒ Method B is single-world BMC, so it must reproduce ``spie.solver``."""
    for builder in BUILDERS:
        puzzle = builder()
        if puzzle.initial_belief:  # hidden puzzles are multi-world by design — see agreement test
            continue
        sol = solver.solve(puzzle)
        b = z3_epistemic.solve_strong(puzzle)
        assert b.solvable == sol.solvable, puzzle.id
        assert b.depth == sol.horizon, f"{puzzle.id}: solver {sol.horizon}, B {b.depth}"
        assert b.world_count == 1, f"{puzzle.id}: fully-observable B0 should be a singleton"


def test_method_b_uniqueness_matches_on_corpus():
    for builder in BUILDERS:
        puzzle = builder()
        a = epistemic.check_uniqueness(puzzle)
        b = z3_epistemic.check_uniqueness(puzzle)
        # A ≡ B holds in both regimes (the lifted G2); the fully-observable solver is only a
        # meaningful oracle when B0 is a singleton, so compare to it only there.
        assert b.unique == a.unique, f"{puzzle.id}: A {a.unique}, B {b.unique}"
        assert b.equivalence == a.equivalence
        if puzzle.initial_belief:
            continue
        s = solver.check_uniqueness(puzzle, solver.solve(puzzle))
        assert b.unique == s.unique, f"{puzzle.id}: solver {s.unique}, B {b.unique}"


# --- genuine contingency: hidden-then-sense fixtures ---------------------------------


def test_which_switch_methods_agree():
    puzzle = which_switch()
    a = epistemic.solve_strong(puzzle)
    b = z3_epistemic.solve_strong(puzzle)
    assert a.solvable and b.solvable
    assert a.depth == 2 and b.depth == 2  # probe, then one flip
    assert b.world_count == 2
    assert z3_epistemic.check_uniqueness(puzzle).unique is True
    assert epistemic.check_uniqueness(puzzle).unique is True


def test_which_switch_three_methods_agree():
    """Three possible worlds — stresses the multi-world encoding past a single pair."""
    puzzle = which_switch_three()
    a = epistemic.solve_strong(puzzle)
    b = z3_epistemic.solve_strong(puzzle)
    assert a.solvable and b.solvable
    assert a.depth == 2 and b.depth == 2
    assert b.world_count == 3
    assert z3_epistemic.check_uniqueness(puzzle).unique is True
    assert epistemic.check_uniqueness(puzzle).unique is True


def test_which_switch_needs_sensing_not_a_blind_guess():
    """Sanity: worst-case depth is genuinely 2. A blind first flip cannot be a strong plan
    (it is illegal in the mismatched world), so no depth-1 plan exists under either method."""
    puzzle = which_switch()
    assert z3_epistemic.solve_strong(puzzle).depth == 2
    assert epistemic.solve_strong(puzzle).depth == 2
