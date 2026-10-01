"""Deterministic, rule-based recognizers: bank record -> :class:`Problem`, or ``None`` (abstain).

This is the honest core of the Path-B auditor. There is **no** language model here — only fixed
regular expressions over normalised text — and the guiding principle is *abstain unless certain*.
A recognizer fires only when it can parse the record's premises **and** conclusion completely and
classify the authored answer as a clean Yes/No (or True/False); anything paraphrased, relational,
self-referential, or otherwise outside the templates is returned as ``None`` and reported as
UNRECOGNIZED, never guessed. Abstention is the safe failure mode: it can only *understate* coverage,
never manufacture a false accusation that an authored answer is wrong.

Only the *polarity* frame is recognized ("does X follow?", "is this valid?", "is the argument
valid?") — questions whose answer is a bare Yes/No/True/False. There the formal verdict maps to the
answer with no dependence on how the answer's prose is worded, which is what keeps the mapping
exact.
"""

from __future__ import annotations

import re

from .bank import BankRecord, normalize
from .categorical import CatStmt
from .problem import Problem

_WS = re.compile(r"\s+")

# --- authored-answer polarity ------------------------------------------------------------------

def classify_polarity(answer: str) -> bool | None:
    """Classify an authored answer as asserting the entailment holds (Yes/True), fails (No/False),
    or neither (``None`` -> the caller abstains). Only ever applied to a polarity-framed question,
    where the answer space genuinely is yes/no/true/false."""
    a = normalize(answer).strip().lower().lstrip("'\" ")
    head = a.split(maxsplit=1)[0].strip(".,:;!?'\"") if a else ""
    if head in ("yes", "true", "correct", "valid"):
        return True
    if head in ("no", "false", "incorrect", "invalid"):
        return False
    return None


# --- categorical statement parsing -------------------------------------------------------------

_ARTICLES = ("the ", "a ", "an ", "any ")
# ordered: O before I ("some X are not Y" is a special "some X are Y"); E/A keyed by their word.
_STMT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("O", re.compile(r"^some (?P<x>.+?) are not (?P<y>.+)$")),
    ("E", re.compile(r"^no (?P<x>.+?) (?:are|is) (?P<y>.+)$")),
    ("A", re.compile(r"^(?:all|every|each) (?P<x>.+?) (?:are|is) (?P<y>.+)$")),
    ("I", re.compile(r"^some (?P<x>.+?) (?:are|is) (?P<y>.+)$")),
)
_QUANT = re.compile(r"\b(all|every|each|no|some)\b")
_RELATIONAL = (" than ", " more ", " less ", " if ", " then ", " because ", ",")


def _canon_term(phrase: str) -> str:
    """Canonical key for a term: lowercase, article-stripped, whitespace-collapsed, with a single
    trailing plural 's' folded (so 'generals' and 'general' are one term). Used only for identity
    within a single problem, where the same surface word recurs."""
    t = phrase.strip().strip(".,;:!?'\" ").lower()
    for art in _ARTICLES:
        if t.startswith(art):
            t = t[len(art):]
    t = _WS.sub(" ", t).strip()
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    return t


def _parse_statement(clause: str) -> tuple[str, str, str] | None:
    """Parse one clause into ``(form, x_key, y_key)`` or ``None``. Rejects relational/comparative
    predicates ('harder than') and empty terms, so only genuine A/E/I/O statements pass."""
    c = clause.strip().lower().strip(".;:!?'\" ")
    for form, pat in _STMT_RULES:
        m = pat.match(c)
        if not m:
            continue
        x_raw, y_raw = m.group("x"), m.group("y")
        if any(tok in f" {y_raw} " or tok in f" {x_raw} " for tok in _RELATIONAL):
            return None
        x, y = _canon_term(x_raw), _canon_term(y_raw)
        if not x or not y or len(x) > 40 or len(y) > 40:
            return None
        return form, x, y
    return None


# --- frame detection: locate a polarity question and split premises | conclusion ---------------

# Each pattern captures group 'c' = the conclusion clause; the premises are the text before it.
_FRAMES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("does-quoted-follow", re.compile(r"does\s+['\"](?P<c>.+?)['\"]\s+follow")),
    ("does-it-follow-that", re.compile(r"does it follow that\s+(?P<c>.+?)\s*[?.]*\s*$")),
    ("conclusion-valid", re.compile(
        r"is the conclusion\s+['\"](?P<c>.+?)['\"]\s+(?:logically\s+)?valid")),
    ("quoted-valid", re.compile(r"\bis\s+['\"](?P<c>.+?)['\"]\s+(?:logically\s+)?valid\b")),
    ("intern-claim", re.compile(
        r"(?:\b(?:an?|the|our|my|your|their)\s+\w+\s+)?"
        r"(?:claims?|says?|argues?|concludes?|insists?|reasons?)\b[^']*"
        r"'(?:so|therefore|thus|hence)\s+(?P<c>[^']+)'")),
)


def _find_frame(low: str) -> tuple[str, str, str] | None:
    """Return ``(premise_text, conclusion_text, frame_tag)`` for the earliest polarity frame, or
    ``None``. ``premise_text`` is everything before the frame match."""
    best: tuple[int, str, str, str] | None = None
    for tag, pat in _FRAMES:
        m = pat.search(low)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), low[: m.start()], m.group("c").strip(), tag)
    if best is None:
        return None
    return best[1], best[2], best[3]


# --- categorical recognizer --------------------------------------------------------------------

_FRAG = re.compile(r"[.?!;]")
_LABEL = re.compile(r"^(?:premise\s*\d*\s*:?|conclusion\s*:?|true or false\s*:?)\s*", re.I)


def _premise_fragments(premise_text: str) -> list[str]:
    frags = []
    for raw in _FRAG.split(premise_text):
        frag = _LABEL.sub("", raw.strip()).strip()
        if len(frag.split()) >= 3:
            frags.append(frag)
    return frags


def _categorical_from(
    premise_text: str, concl_text: str, pol: bool, tag: str, strict: bool = False
) -> Problem | None:
    """Build a categorical :class:`Problem`, or abstain. Strict: every substantive premise fragment
    must parse as an A/E/I/O statement (an unparsed one that carries a quantifier means we did not
    understand the argument -> abstain, never drop a premise).

    When ``strict`` (used for the select-conclusion frame, where the *conclusion* is the authored
    answer), **every** substantive fragment must parse -- a dropped premise there could turn a valid
    argument invalid and manufacture a false DISAGREE, so we abstain on any fragment we cannot read.
    """
    concl = _parse_statement(concl_text)
    if concl is None:
        return None
    premises: list[tuple[str, str, str]] = []
    for frag in _premise_fragments(premise_text):
        st = _parse_statement(frag)
        if st is not None:
            premises.append(st)
        elif strict or _QUANT.search(frag):
            return None  # a premise we could not parse -> abstain rather than drop it
    if not premises:
        return None
    order: list[str] = []
    for _form, x, y in [*premises, concl]:
        for term in (x, y):
            if term not in order:
                order.append(term)
    if not 2 <= len(order) <= 4:
        return None
    return Problem(
        family="categorical",
        answer_polarity=pol,
        frame=f"categorical/{tag}",
        terms=tuple(order),
        cat_premises=tuple(CatStmt(f, x, y) for f, x, y in premises),
        cat_conclusion=CatStmt(*concl),
    )


# --- propositional recognizer ------------------------------------------------------------------

_FILLERS = (
    "we also know that ", "we know that ", "we know ", "it is the case that ",
    "then ", "so ", "therefore ", "hence ", "but ", "and ", "that ",
)
_COND_THEN = re.compile(r"^if (?P<a>.+?)(?:,)?\s+then\s+(?P<b>.+)$")
_COND_COMMA = re.compile(r"^if (?P<a>.+?),\s*(?P<b>.+)$")
_FACT_LEAD = ("we know that ", "we know ", "we also know that ")


def _atom_key(clause: str) -> str:
    t = clause.strip().strip(".,;:!?'\" ").lower()
    changed = True
    while changed:
        changed = False
        for f in _FILLERS:
            if t.startswith(f):
                t, changed = t[len(f):].strip(), True
    return _WS.sub(" ", t).strip()


def _polarity_atom(clause: str) -> tuple[str, bool]:
    """``(atom_key, truth)`` for a fact or conclusion clause, extracting a leading or framed
    negation."""
    t = clause.strip().strip(".;:!?").lower()
    for lead in _FACT_LEAD:
        if t.startswith(lead):
            t = t[len(lead):].strip()
    truth = True
    for neg in ("it is not the case that ", "not the case that "):
        if neg in t:
            t, truth = t.replace(neg, ""), False
    for neg in ("not ", "no "):
        if t.startswith(neg):
            t, truth = t[len(neg):], False
    if t.endswith(" is false") or t.endswith(" is not true"):
        t, truth = t.rsplit(" is ", 1)[0], False
    elif t.endswith(" is true"):
        t = t.rsplit(" is ", 1)[0]
    return _atom_key(t), truth


def _propositional_from(
    premise_text: str, concl_text: str, pol: bool, tag: str, strict: bool = False
) -> Problem | None:
    """Build a propositional :class:`Problem`, or abstain. Full-match guard: every fact and the
    conclusion must reuse a clause already named by some conditional's antecedent/consequent, so we
    only judge a completely-understood argument (letter/verbatim forms), never a paraphrase.

    When ``strict`` (select-conclusion frame), every premise fragment must parse as a conditional or
    a fact -- a silently-dropped disguised conditional ('whenever X, Y') could flip a valid chain to
    invalid against the authored conclusion, so we abstain on anything we cannot read as one."""
    conds: list[tuple[str, str]] = []
    facts: list[tuple[str, bool]] = []
    for raw in _FRAG.split(premise_text):
        frag = raw.strip()
        if len(frag.split()) < 1:
            continue
        if frag.startswith("if "):
            m = _COND_THEN.match(frag) or _COND_COMMA.match(frag)
            if m is None:
                return None  # an 'if' we could not parse -> abstain
            conds.append((_atom_key(m.group("a")), _atom_key(m.group("b"))))
        elif any(frag.startswith(lead) for lead in _FACT_LEAD) or _looks_atomic(frag):
            facts.append(_polarity_atom(frag))
        elif strict:
            return None  # a premise clause we could not read as a conditional or fact -> abstain
    if not conds:
        return None
    known = {a for a, _ in conds} | {b for _, b in conds}
    concl = _polarity_atom(concl_text)
    checkset = [a for a, _ in facts] + [concl[0]]
    if any(atom not in known for atom in checkset) or not concl[0]:
        return None  # unmatched clause -> we did not fully understand the argument
    atoms: list[str] = []
    for a, b in conds:
        for x in (a, b):
            if x not in atoms:
                atoms.append(x)
    return Problem(
        family="propositional",
        answer_polarity=pol,
        frame=f"propositional/{tag}",
        conditionals=tuple(conds),
        facts=tuple(facts),
        prop_conclusion=concl,
        atoms=tuple(atoms),
    )


def _looks_atomic(frag: str) -> bool:
    """A short, quantifier-free assertion that could be a bare fact ('A', 'not B', 'A is false')."""
    return len(frag.split()) <= 6 and not _QUANT.search(frag) and "?" not in frag


# --- select-conclusion frame: "..premises.. what follows?" with the answer as the conclusion -----

# Deductive "what follows" cues. Unlike the polarity frames, the conclusion here is the *authored
# answer*, not a clause in the question. Firing broadly is safe: the strict parsers below judge only
# when the premises AND the answer both read as literal formal statements, and abstain otherwise, so
# lateral-thinking / probability / strategy items (whose answers are prose) fall through untouched.
_SELECT = re.compile(
    r"\bwhat (?:necessarily |validly )?follows?(?: (?:necessarily|validly|with certainty))?\b"
    r"|\bwhat can (?:you|we) conclude\b"
    r"|\bwhich (?:statement|conclusion) follows\b"
    r"|\bwhat must (?:be true|follow)\b"
    r"|\bwhat do we know\b"
)


def _find_select(low: str) -> str | None:
    """Return the premise text (everything before a deductive 'what follows?' cue), or ``None``."""
    m = _SELECT.search(low)
    return low[: m.start()] if m else None


# --- top-level dispatch -------------------------------------------------------------------------

# Surface cues that mark a frame we deliberately do NOT handle (select-an-option among distractors,
# named-fallacy, or paraphrase-heavy) -> abstain outright rather than risk mis-mapping the answer.
_ABSTAIN_CUES = (
    "odd one out", "not follow", "n't follow", "never follow", "not guaranteed",
    "best described", "equivalent", "commits", "fallacy", "ad hominem", "straw man",
)


def recognize(record: BankRecord) -> Problem | None:
    """Bank record -> a formally decidable :class:`Problem`, or ``None`` (honest abstention).

    Only ``logic`` true/false and multiple-choice records reach a recognizer. Two exact frames fire:

    * **polarity** -- the question asks "does X follow / is this valid" and the authored answer is a
      bare Yes/No/True/False, so the formal verdict maps to the answer's polarity with no dependence
      on prose wording.
    * **select-conclusion** -- the question asks "what follows?" and the authored answer *is* the
      candidate conclusion; recognized only when premises and the answer both parse as literal
      formal statements (strict, so no dropped premise can manufacture a false DISAGREE), with the
      author taken to assert the conclusion follows (``answer_polarity=True``).

    Everything else abstains."""
    if record.category != "logic" or record.rec_type not in ("multiple-choice", "true-false"):
        return None
    low = normalize(record.question).lower()
    if any(cue in f" {low} " for cue in _ABSTAIN_CUES):
        return None
    # 1) polarity frame -----------------------------------------------------------------------
    pol = classify_polarity(record.correct_answer)
    if pol is not None:
        frame = _find_frame(low)
        if frame is not None:
            premise_text, concl_text, tag = frame
            prob = _categorical_from(premise_text, concl_text, pol, tag) or _propositional_from(
                premise_text, concl_text, pol, tag
            )
            if prob is not None:
                return prob
    # 2) select-conclusion frame --------------------------------------------------------------
    premise_text = _find_select(low)
    if premise_text is not None:
        answer = normalize(record.correct_answer).lower()
        return _categorical_from(
            premise_text, answer, True, "select", strict=True
        ) or _propositional_from(premise_text, answer, True, "select", strict=True)
    return None


__all__ = ["classify_polarity", "recognize"]
