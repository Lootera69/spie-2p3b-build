"""Cross-solver agreement (gate G2): Z3, explicit-state search and ASP must agree on every
corpus puzzle, the certificate must carry independent evidence from all three methods, and a
genuine disagreement must be surfaced as a warning — never swallowed.
"""

from __future__ import annotations

import json

from spie import asp_solver, search, solver
from spie.certificate import certify
from spie.crosscheck import cross_solve
from spie.examples_src import BUILDERS, move
from spie.results import Solution
from spie.serialize import certificate_from_json, certificate_to_json, dumps

_METHOD_NAMES = {solver.SOLVER_NAME, search.SOLVER_NAME, asp_solver.SOLVER_NAME}


def test_both_solvers_agree_across_corpus():
    for builder in BUILDERS:
        puzzle = builder()
        cross = cross_solve(puzzle)
        assert cross.agree, f"{puzzle.id}: {cross.discrepancies}"
        # Three independent, named-and-versioned methods stand behind the verdict.
        assert {e.name for e in cross.evidence} == _METHOD_NAMES
        for e in cross.evidence:
            assert e.solvable == cross.solvable
            assert e.horizon == cross.horizon
            assert e.unique == cross.unique


def test_certificate_carries_both_evidence_and_round_trips():
    cert = certify(move())
    assert len(cert.solvers) == 3
    assert {e.name for e in cert.solvers} == _METHOD_NAMES
    # Evidence survives the canonical JSON round-trip.
    restored = certificate_from_json(json.loads(dumps(certificate_to_json(cert))))
    assert restored.solvers == cert.solvers


def test_disagreement_is_reported_not_swallowed(monkeypatch):
    # Force the search backend to lie about the horizon; the cross-check must catch it.
    real = search.solve

    def fake_solve(puzzle, *a, **k):
        s = real(puzzle, *a, **k)
        return Solution(s.solvable, s.horizon + 1, s.trace, s.state_path, s.cost)

    monkeypatch.setattr("spie.crosscheck.search.solve", fake_solve)
    cross = cross_solve(move())
    assert not cross.agree
    assert any("horizon" in d for d in cross.discrepancies)
    # And certification turns that disagreement into a visible warning rather than passing.
    cert = certify(move())
    assert any(w.startswith("cross-solver:") for w in cert.warnings)
