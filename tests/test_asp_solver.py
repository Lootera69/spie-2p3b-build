"""Phase 3b — the ASP backend (:mod:`spie.asp_solver`) as gate G2's independent *third* method.

clingo/answer-set programming is a third solving paradigm alongside the symbolic Z3 backend and
the concrete explicit-state search, sharing zero encoding code with either. These tests pin its
obligations:

* **Agreement** — on every fully-observable corpus puzzle, ASP agrees with Z3 *and* search on
  the triple (solvable, minimal horizon, uniqueness). This is *checked*, never assumed — a
  discrepancy is a hard failure.
* **Conformance** — the ASP-reported trace is a genuine solution: replayed through the
  independent interpreter it reaches the goal and reproduces ASP's own state-path.
* **Uniqueness (negative)** — the deliberately non-unique fork puzzle is reported non-unique
  with a real, distinct witness trace.
* **Independence** — a distinct, versioned solver name, folded into the certificate as a third
  :class:`~spie.ir.SolverEvidence`.
"""

from __future__ import annotations

from spie import asp_solver, search, solver
from spie.certificate import certify
from spie.examples_src import BUILDERS, move, two_solutions
from spie.interpreter import run
from spie.ir import Puzzle


def _fully_observable() -> list[Puzzle]:
    """The corpus puzzles ASP owns — gate G2 is the fully-observable regime (singleton belief).
    Hidden-state puzzles are the epistemic Methods A/B's job, not this backend's."""
    return [p for b in BUILDERS if not (p := b()).initial_belief]


def _state_path_from_interpreter(puzzle: Puzzle, trace: list[str]):
    """Replay a trace through the ground-truth interpreter and read its per-tick state-path in
    declared-variable order — the same shape ASP reports, so the two can be compared."""
    outcome = run(puzzle, trace)
    keys = [v.key for v in puzzle.variables]
    return outcome, tuple(tuple(s[k] for k in keys) for s in outcome.states)


def test_asp_agrees_with_z3_and_search_across_corpus():
    for puzzle in _fully_observable():
        asp_sol = asp_solver.solve(puzzle)
        asp_uniq = asp_solver.check_uniqueness(puzzle, asp_sol)
        z3_sol = solver.solve(puzzle)
        z3_uniq = solver.check_uniqueness(puzzle, z3_sol)
        se_sol = search.solve(puzzle)
        se_uniq = search.check_uniqueness(puzzle, se_sol)

        assert asp_sol.solvable == z3_sol.solvable == se_sol.solvable, puzzle.id
        assert asp_sol.horizon == z3_sol.horizon == se_sol.horizon, puzzle.id
        assert asp_uniq.unique == z3_uniq.unique == se_uniq.unique, puzzle.id


def test_asp_trace_conforms_through_the_interpreter():
    """Every ASP solution is a genuine one: the interpreter accepts the trace, reaches the goal,
    and its induced state-path is exactly the one ASP reported."""
    for puzzle in _fully_observable():
        asp_sol = asp_solver.solve(puzzle)
        assert asp_sol.solvable, puzzle.id
        assert len(asp_sol.state_path) == asp_sol.horizon + 1, puzzle.id
        outcome, path = _state_path_from_interpreter(puzzle, asp_sol.trace)
        assert outcome.reached_goal, puzzle.id
        assert path == asp_sol.state_path, puzzle.id


def test_asp_reports_the_fork_non_unique_with_a_distinct_witness():
    puzzle = two_solutions()
    sol = asp_solver.solve(puzzle)
    assert sol.solvable
    uniq = asp_solver.check_uniqueness(puzzle, sol)
    assert uniq.unique is False
    # The witness is a real, different minimal trace that also reaches the goal.
    assert uniq.witness is not None and list(uniq.witness) != list(sol.trace)
    outcome, _ = _state_path_from_interpreter(puzzle, list(uniq.witness))
    assert outcome.reached_goal


def test_asp_is_deterministic():
    """The lex-least optimization makes the reported trace/cost a canonical function of the
    puzzle, so repeated solves are byte-identical (the certificate's reproducibility rests on
    this)."""
    puzzle = move()
    first = asp_solver.solve(puzzle)
    second = asp_solver.solve(puzzle)
    assert first == second


def test_asp_folds_into_the_certificate_as_a_third_method():
    cert = certify(move())
    names = {e.name for e in cert.solvers}
    assert asp_solver.SOLVER_NAME in names
    assert names == {solver.SOLVER_NAME, search.SOLVER_NAME, asp_solver.SOLVER_NAME}
    assert asp_solver.solver_version() != "unknown"
