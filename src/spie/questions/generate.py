"""Generate one proven-answer question — the registry and the seed→question entry point.

:func:`generate_question` is the whole public surface: pick a category's :class:`Domain`, check it
can pose the requested :class:`QuestionType` with a proof, derive a deterministic RNG from the seed,
and build the question. Two guards make the result trustworthy:

* the domain has already produced a :class:`Proof` (Z3 or exact computation) for the answer, and
* :meth:`Question.check` re-asserts the shape invariants before the question is returned,

so a question is emitted only if it is both well-formed and backed by a decision procedure. The
answer path contains no learned model at any point.
"""

from __future__ import annotations

from .domains import Domain, derive_rng
from .domains.arithmetic import ArithmeticDomain
from .domains.propositional import LogicDomain
from .domains.sequences import SequenceDomain
from .domains.sets import SetsDomain
from .domains.syllogism import SyllogismDomain
from .types import Question, QuestionType

# The category registry. Insertion order is the presentation order; keys are the CLI category names.
_DOMAINS: dict[str, Domain] = {
    d.name: d
    for d in (
        SetsDomain(),
        LogicDomain(),
        ArithmeticDomain(),
        SequenceDomain(),
        SyllogismDomain(),
    )
}

CATEGORIES: tuple[str, ...] = tuple(_DOMAINS)

# Rendering styles: "plain" is the abstract form; "realistic" wraps the same proven answer in an
# everyday scenario (a skin that only labels the atoms). "plain" is the default everywhere so all
# existing byte-reproducibility pins are untouched.
STYLES: tuple[str, ...] = ("plain", "realistic")
_STYLES = frozenset(STYLES)


def categories() -> tuple[str, ...]:
    """The supported category names, in presentation order."""
    return CATEGORIES


def realistic_categories() -> tuple[str, ...]:
    """Category names that can render at least one question type as a realistic skin."""
    return tuple(name for name, d in _DOMAINS.items() if d.realistic)


def supported_types(category: str) -> tuple[QuestionType, ...]:
    """The question types ``category`` can pose with a proven answer.

    Ordered by :class:`QuestionType`'s enum-definition order (tf, mcq, blank), never by the salted
    iteration order of the domain's internal ``frozenset`` - so this accessor, and anything built by
    iterating it (CLI help, generated question sets), is byte-reproducible across processes."""
    supported = _domain(category).supported
    return tuple(qt for qt in QuestionType if qt in supported)


def _domain(category: str) -> Domain:
    key = category.strip().lower()
    if key not in _DOMAINS:
        valid = ", ".join(CATEGORIES)
        raise ValueError(f"unknown category {category!r} (supported: {valid})")
    return _DOMAINS[key]


def _qid(category: str, qtype: QuestionType, seed: int) -> str:
    """A stable, human-readable question id, mirroring the puzzle engine's ``gen_XXXX`` style."""
    return f"q_{category}_{qtype.value}_{seed:04d}"


def generate_question(
    category: str,
    qtype: str | QuestionType,
    seed: int = 0,
    words: tuple[str, ...] = (),
    style: str = "plain",
) -> Question:
    """Build one proven-answer question. Deterministic in ``(category, qtype, seed, words, style)``.

    ``words`` are optional seed words: a domain uses them when they name objects it understands
    (e.g. ``("square", "rectangle")`` for :mod:`~spie.questions.domains.sets`) and ignores them
    otherwise. ``style`` is ``"plain"`` (the abstract form) or ``"realistic"`` (the same
    formally-decided answer, worded as an everyday scenario -- a *skin* that only labels the atoms,
    so the answer is unchanged). Raises :class:`ValueError` for an unknown category, an unsupported
    question type, an unknown style, or a ``"realistic"`` request a category cannot yet skin.
    """
    domain = _domain(category)
    qt = QuestionType.parse(qtype)
    if qt not in domain.supported:
        ok = ", ".join(sorted(t.value for t in domain.supported))
        raise ValueError(
            f"category {domain.name!r} cannot pose a {qt.value!r} question with a proven answer "
            f"(supported: {ok})"
        )
    if style not in _STYLES:
        raise ValueError(f"unknown style {style!r} (supported: {', '.join(_STYLES)})")
    if style == "realistic" and qt not in domain.realistic:
        skinnable = ", ".join(sorted(t.value for t in domain.realistic)) or "none"
        raise ValueError(
            f"category {domain.name!r} has no realistic skin for a {qt.value!r} question "
            f"(realistic types: {skinnable})"
        )
    rng = derive_rng(domain.name, qt, seed)
    question = domain.build(qt, _qid(domain.name, qt, seed), seed, rng, tuple(words), style=style)
    question.check()  # shape invariants: hard failure if the domain built something malformed
    return question


def generate_series(
    category: str,
    qtype: str | QuestionType,
    count: int,
    start: int = 0,
    words: tuple[str, ...] = (),
    style: str = "plain",
) -> list[Question]:
    """``count`` consecutive-seed questions from one category/type — a small deterministic set."""
    return [
        generate_question(category, qtype, start + i, words, style=style) for i in range(count)
    ]


__all__ = [
    "CATEGORIES",
    "STYLES",
    "categories",
    "generate_question",
    "generate_series",
    "realistic_categories",
    "supported_types",
]
