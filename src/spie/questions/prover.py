"""The Z3 bridge for proven answers: decide validity, return a concrete counter-model when false.

Every question category that reduces to logical validity (``sets`` subsumption, propositional
``logic``) goes through :func:`decide`. It is the exact analogue of the puzzle engine's
UNSAT-of-the-negation proof: a claim is *valid* iff its negation is unsatisfiable, and when it is
*not* valid Z3 hands back a satisfying assignment of the negation — i.e. a real counterexample,
so a "False" answer is a disproof, never an assertion. A ``z3`` ``unknown`` verdict raises: an
undecided result must never be silently reported as a proof.
"""

from __future__ import annotations

import platform

import z3

Z3 = "z3"
PYTHON = "python"


def z3_version() -> str:
    return z3.get_version_string()


def python_version() -> str:
    return platform.python_version()


def decide(claim: z3.BoolRef) -> tuple[bool, z3.ModelRef | None]:
    """Return ``(valid, counter_model)``: ``(True, None)`` if ``claim`` is a tautology (its
    negation is UNSAT), otherwise ``(False, model)`` where ``model`` satisfies ``Not(claim)`` and
    thus witnesses the claim's failure. Raises on ``unknown`` (a determinism guard)."""
    solver = z3.Solver()
    solver.add(z3.Not(claim))
    result = solver.check()
    if result == z3.unsat:
        return True, None
    if result == z3.sat:
        return False, solver.model()
    raise RuntimeError(f"z3 returned {result!r} deciding validity — refusing to assert a proof")


def satisfiable(formula: z3.BoolRef) -> tuple[bool, z3.ModelRef | None]:
    """Return ``(sat, model)`` for ``formula``; raise on ``unknown``."""
    solver = z3.Solver()
    solver.add(formula)
    result = solver.check()
    if result == z3.sat:
        return True, solver.model()
    if result == z3.unsat:
        return False, None
    raise RuntimeError(f"z3 returned {result!r} deciding satisfiability")


__all__ = ["PYTHON", "Z3", "decide", "python_version", "satisfiable", "z3_version"]
