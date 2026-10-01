"""Real-world "skins" for the ``logic`` domain: everyday labellings of a proven argument form.

A :class:`Scenario` supplies concrete natural-language clauses for a schema's atoms (p, q, r), and
a :class:`SkinSchema` renders a named propositional law as an argument in those words ("If it rains,
then the match is cancelled. We know that it rains. Therefore, the match is cancelled."). The skin
never touches the proof: validity is decided by Z3 on the *abstract* claim over Boolean atoms, and
the scenario only *labels* those atoms -- exactly as the ``sets`` domain proves property-set
inclusion and merely labels the classes "square"/"rectangle", and the ``syllogism`` domain proves an
occupancy pattern and merely labels the terms. So a skin can never change an answer; it changes only
the surface wording. This keeps the thesis intact -- no learned model, and nothing but a formal
solver in the correctness path -- while letting a question read like real life.

The scenario pool is a fixed, curated, checked-in library (mined from the question bank and
hand-vetted for faithful phrasing), and every choice is driven by the domain's seeded ``rng``, so a
realistic question is byte-reproducible just like an abstract one.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

import z3

from ..prover import decide


@dataclass(frozen=True)
class Scenario:
    """A real-world labelling of an argument's atoms. ``clauses`` are present-tense declarative
    clauses -- ``clauses[i]`` labels atom ``i`` (p, q, r) -- each phrased to read correctly after
    "If", after "We know that", after "it is not the case that", and standing alone after
    "Therefore,". ``concepts`` are short tags folded into the question's concept list."""

    concepts: tuple[str, ...]
    clauses: tuple[str, ...]


@dataclass(frozen=True)
class SkinSchema:
    """A named propositional law paired with (a) a Z3 ``claim`` whose validity *is* the answer and
    (b) a ``render`` that states the law as an everyday argument over a :class:`Scenario`. Both
    describe the same form; ``render`` is presentation only and cannot affect the proof."""

    key: str
    arity: int
    law: str  # human-readable name of the law/fallacy
    claim: Callable[..., z3.BoolRef]  # abstract claim over Z3 Bools; validity decided by the prover
    render: Callable[[Scenario], str]  # the argument, worded through a scenario


def _neg(clause: str) -> str:
    """Faithful negation of a clause, unambiguous for a validity question."""
    return f"it is not the case that {clause}"


# -- argument renderers: each mirrors the logical structure of its law exactly ------------------


def _mp(s: Scenario) -> str:  # modus ponens: (p->q), p |= q
    p, q = s.clauses
    return f"If {p}, then {q}. We know that {p}. Therefore, {q}."


def _mt(s: Scenario) -> str:  # modus tollens: (p->q), ~q |= ~p
    p, q = s.clauses
    return f"If {p}, then {q}. But {_neg(q)}. Therefore, {_neg(p)}."


def _hs(s: Scenario) -> str:  # hypothetical syllogism: (p->q), (q->r) |= (p->r)
    p, q, r = s.clauses
    return f"If {p}, then {q}. If {q}, then {r}. Therefore, if {p}, then {r}."


def _ac(s: Scenario) -> str:  # affirming the consequent (INVALID): (p->q), q =/= p
    p, q = s.clauses
    return f"If {p}, then {q}. We know that {q}. Therefore, {p}."


def _da(s: Scenario) -> str:  # denying the antecedent (INVALID): (p->q), ~p =/= ~q
    p, q = s.clauses
    return f"If {p}, then {q}. But {_neg(p)}. Therefore, {_neg(q)}."


def _cv(s: Scenario) -> str:  # converse error (INVALID): (p->q) =/= (q->p)
    p, q = s.clauses
    return f"If {p}, then {q}. Therefore, if {q}, then {p}."


SKINS: tuple[SkinSchema, ...] = (
    SkinSchema(
        "modus-ponens", 2, "modus ponens",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), p), q),
        _mp,
    ),
    SkinSchema(
        "modus-tollens", 2, "modus tollens",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), z3.Not(q)), z3.Not(p)),
        _mt,
    ),
    SkinSchema(
        "hypothetical-syllogism", 3, "hypothetical syllogism",
        lambda p, q, r: z3.Implies(z3.And(z3.Implies(p, q), z3.Implies(q, r)), z3.Implies(p, r)),
        _hs,
    ),
    SkinSchema(
        "affirming-consequent", 2, "affirming the consequent",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), q), p),
        _ac,
    ),
    SkinSchema(
        "denying-antecedent", 2, "denying the antecedent",
        lambda p, q: z3.Implies(z3.And(z3.Implies(p, q), z3.Not(p)), z3.Not(q)),
        _da,
    ),
    SkinSchema(
        "converse-error", 2, "the converse error",
        lambda p, q: z3.Implies(z3.Implies(p, q), z3.Implies(q, p)),
        _cv,
    ),
)

_ATOMS = ("p", "q", "r")


def decide_claim(claim: Callable[..., z3.BoolRef], arity: int) -> tuple[bool, str]:
    """``(valid, counter_row)`` for an abstract claim over ``arity`` Boolean atoms. ``counter_row``
    names the falsifying assignment when invalid (a Z3 counter-model), else ``""``. This is the one
    place a propositional claim is decided, shared by the abstract and realistic logic paths."""
    atoms = tuple(z3.Bool(n) for n in _ATOMS[:arity])
    valid, model = decide(claim(*atoms))
    if valid:
        return True, ""

    def _val(a: z3.BoolRef) -> str:
        return "true" if model and z3.is_true(model.eval(a, model_completion=True)) else "false"

    row = ", ".join(f"{n}={_val(a)}" for n, a in zip(_ATOMS[:arity], atoms, strict=False))
    return False, row


# Binary scenarios (p -> q). Each clause must read naturally in every slot, negation included.
_BINARY: tuple[Scenario, ...] = (
    Scenario(("weather", "sport"), ("it rains", "the match is cancelled")),
    Scenario(("power", "lighting"), ("the power goes out", "the lights turn off")),
    Scenario(("security", "access"), ("the password is correct", "access is granted")),
    Scenario(("billing", "service"), ("the invoice is unpaid", "the service is suspended")),
    Scenario(("temperature", "water"), ("the temperature falls below zero", "the water freezes")),
    Scenario(("travel", "boarding"), ("the passport is valid", "the traveller may board")),
    Scenario(("library", "fees"), ("the book is returned late", "a fine is charged")),
    Scenario(("garden", "growth"), ("the soil is watered", "the seeds sprout")),
    Scenario(("network", "request"), ("the token is valid", "the request is accepted")),
    Scenario(("traffic", "movement"), ("the light is green", "the traffic may move")),
    Scenario(("health", "alert"), ("the patient has a fever", "the nurse is alerted")),
    Scenario(("shopping", "pricing"), ("the coupon is applied", "the price is reduced")),
)

# Ternary scenarios (p -> q -> r): genuine causal chains, for hypothetical syllogism.
_TERNARY: tuple[Scenario, ...] = (
    Scenario(
        ("weather", "sport"),
        ("it rains", "the pitch is waterlogged", "the match is postponed"),
    ),
    Scenario(
        ("power", "web"),
        ("the power fails", "the server shuts down", "the website goes offline"),
    ),
    Scenario(
        ("study", "career"),
        ("you study hard", "you pass the exam", "you earn the diploma"),
    ),
    Scenario(
        ("cold", "recreation"),
        ("the temperature falls below zero", "the lake freezes", "the skaters can go out"),
    ),
    Scenario(
        ("economy", "prices"),
        ("the harvest fails", "the wheat supply drops", "the price of bread rises"),
    ),
    Scenario(
        ("fuel", "travel"),
        ("the tank runs dry", "the engine stalls", "the car comes to a halt"),
    ),
)


def pick_scenario(arity: int, rng: random.Random) -> Scenario:
    """Choose a scenario of the right shape (a binary one for 2-atom laws, a chained one for the
    3-atom law) via the seeded ``rng``, so the choice is deterministic and byte-reproducible."""
    pool = _TERNARY if arity >= 3 else _BINARY
    return pool[rng.randrange(len(pool))]


__all__ = ["SKINS", "Scenario", "SkinSchema", "decide_claim", "pick_scenario"]

