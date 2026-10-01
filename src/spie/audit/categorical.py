"""A complete, deterministic decision procedure for monadic *categorical* logic (All/No/Some ...),
generalised to any number of terms. This is the formal solver behind the syllogism and
immediate-inference audits — the exact-model analogue of the propositional Z3 path.

``n`` named terms partition any domain into ``2**n`` regions (in/out of each term). A model, *for
validity*, is fixed by which regions are inhabited — ``2**(2**n)`` occupancy patterns. Each
categorical statement is a condition on that occupancy (modern/Boolean reading — universals carry
**no** existential import, exactly as :mod:`spie.questions.domains.syllogism`):

* **A** "All X are Y"      — no inhabited region in X and out of Y.
* **E** "No X is Y"        — no inhabited region in both X and Y.
* **I** "Some X is Y"      — some inhabited region in both X and Y.
* **O** "Some X is not Y"  — some inhabited region in X and out of Y.

An argument is **valid** iff every occupancy pattern modelling all premises also models the
conclusion. Enumerating patterns is exhaustive and finite, so the verdict is complete (never
``unknown``) and an invalid form yields a concrete counter-model — a disproof, not an assertion.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

FORMS = ("A", "E", "I", "O")
MAX_TERMS = 4  # 2**(2**4) = 65536 patterns; beyond this we abstain rather than blow up.


@dataclass(frozen=True)
class CatStmt:
    """A categorical statement ``form`` about ordered terms ``(x, y)`` -- e.g.
    ``('A', 'cats', 'pets')`` is "All cats are pets". ``x``/``y`` are term *names*; identity across
    a problem is by name."""

    form: str
    x: str
    y: str


@dataclass(frozen=True)
class CatVerdict:
    valid: bool
    counter: str  # a description of an inhabited-region counter-model, or "" when valid


def _holds(occ: tuple[bool, ...], stmt: CatStmt, bit: dict[str, int]) -> bool:
    """Does ``stmt`` hold under occupancy ``occ`` (``occ[r]`` = region r inhabited)?"""
    x, y = bit[stmt.x], bit[stmt.y]
    inx = lambda r: bool(r & x)  # noqa: E731 - tiny local predicates keep the loop readable
    iny = lambda r: bool(r & y)  # noqa: E731
    regions = range(len(occ))
    if stmt.form == "A":
        return not any(occ[r] and inx(r) and not iny(r) for r in regions)
    if stmt.form == "E":
        return not any(occ[r] and inx(r) and iny(r) for r in regions)
    if stmt.form == "I":
        return any(occ[r] and inx(r) and iny(r) for r in regions)
    if stmt.form == "O":
        return any(occ[r] and inx(r) and not iny(r) for r in regions)
    raise ValueError(f"unknown categorical form {stmt.form!r}")


def _counter_text(occ: tuple[bool, ...], terms: tuple[str, ...], bit: dict[str, int]) -> str:
    parts = []
    for r, on in enumerate(occ):
        if on:
            memb = [t for t in terms if r & bit[t]] or ["neither category"]
            parts.append("something that is " + " and ".join(memb))
    return "; ".join(parts) if parts else "the empty domain"


def decide_categorical(
    terms: tuple[str, ...], premises: tuple[CatStmt, ...], conclusion: CatStmt
) -> CatVerdict:
    """``CatVerdict`` for *premises therefore conclusion* over the given (unique, ordered) terms.

    Raises ``ValueError`` if a statement mentions an unknown term or there are more than
    :data:`MAX_TERMS` terms (the caller abstains on that record rather than guessing)."""
    if len(terms) > MAX_TERMS:
        raise ValueError(f"too many terms ({len(terms)} > {MAX_TERMS}) to decide exhaustively")
    bit = {t: 1 << i for i, t in enumerate(terms)}
    for stmt in (*premises, conclusion):
        if stmt.x not in bit or stmt.y not in bit:
            raise ValueError(f"statement over unknown term: {stmt}")
    n_regions = 1 << len(terms)
    for pattern in product((False, True), repeat=n_regions):
        if all(_holds(pattern, p, bit) for p in premises) and not _holds(pattern, conclusion, bit):
            return CatVerdict(False, _counter_text(pattern, terms, bit))
    return CatVerdict(True, "")


__all__ = ["CatStmt", "CatVerdict", "FORMS", "MAX_TERMS", "decide_categorical"]
