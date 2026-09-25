"""Line-level parsing and filtering of the ConceptNet assertions dump.

The dump is a 5-column tab-separated file, one assertion per line::

    /a/[/r/IsA/,/c/en/door/,/c/en/barrier/]<TAB>/r/IsA<TAB>/c/en/door<TAB>/c/en/barrier<TAB>{...}

Only columns 2-5 matter: the relation URI, the two endpoint URIs, and a JSON metadata blob whose
``weight`` field is a confidence proxy. Parsing happens on **bytes** so the ~34M-line stream never
pays for decoding lines that are rejected on the relation or the language prefix — the vast
majority. Every filter here is a hard, documented contract the shipped test suite re-asserts on
the emitted artifact (see ``tests/test_conceptnet_data.py``).
"""

from __future__ import annotations

import re

# ConceptNet relation URI -> the value of the matching :class:`spie.concepts.Relation` member.
# The engine models exactly six relation kinds; every other ConceptNet relation is dropped here,
# at ingest, so no unmodellable edge can reach the artifact.
RELATIONS: dict[bytes, str] = {
    b"/r/IsA": "IsA",
    b"/r/UsedFor": "UsedFor",
    b"/r/CapableOf": "CapableOf",
    b"/r/HasProperty": "HasProperty",
    b"/r/Causes": "Causes",
    b"/r/PartOf": "PartOf",
}

# English concepts only. Multi-word ConceptNet terms are spelled with underscores
# (``/c/en/front_door``), so the single-token contract below rejects them by construction.
_EN_PREFIX = b"/c/en/"

# A concept term is a single lower-case ASCII token. The renderer is ASCII-only and concept names
# become puzzle element names, so anything else is refused rather than transliterated.
TERM_RE = re.compile(r"^[a-z0-9-]+$")
_HAS_LETTER = re.compile(r"[a-z]")
MIN_TERM_LEN = 2

_WEIGHT_RE = re.compile(rb'"weight":\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)')
DEFAULT_WEIGHT = 1.0


def term_of(uri: bytes) -> str | None:
    """The bare concept term of an endpoint URI, or ``None`` if it fails the single-token contract.

    ConceptNet endpoints carry optional part-of-speech and sense suffixes
    (``/c/en/door``, ``/c/en/door/n``, ``/c/en/door/n/wn/artifact``); all of them denote the same
    term, which is always the fourth path segment."""
    parts = uri.split(b"/")
    if len(parts) < 4:
        return None
    term = parts[3].decode("utf-8", "replace")
    if len(term) < MIN_TERM_LEN or not TERM_RE.match(term) or not _HAS_LETTER.search(term):
        return None
    return term


def weight_of(meta: bytes) -> float:
    """The assertion's ``weight`` from its JSON metadata column.

    Extracted with a regex rather than ``json.loads`` because this runs tens of millions of times
    and the field is a flat number; a line without a weight is treated as unit confidence."""
    match = _WEIGHT_RE.search(meta)
    return float(match.group(1)) if match else DEFAULT_WEIGHT


def parse_line(raw: bytes) -> tuple[str, str, str, float] | None:
    """Parse one dump line into ``(start, relation, end, weight)``, or ``None`` if it is filtered.

    Rejects, in the cheapest-first order: malformed lines, relations the engine does not model,
    non-English endpoints, endpoints that are not single lower-case ASCII tokens, and self-loops
    (a ``w -> w`` edge is meaningless to ``expand`` and would make the word its own ancestor)."""
    parts = raw.split(b"\t", 4)
    if len(parts) < 5:
        return None
    relation = RELATIONS.get(parts[1])
    if relation is None:
        return None
    start_uri, end_uri = parts[2], parts[3]
    if not start_uri.startswith(_EN_PREFIX) or not end_uri.startswith(_EN_PREFIX):
        return None
    start = term_of(start_uri)
    if start is None:
        return None
    end = term_of(end_uri)
    if end is None or end == start:
        return None
    return start, relation, end, weight_of(parts[4])


__all__ = [
    "RELATIONS",
    "TERM_RE",
    "MIN_TERM_LEN",
    "DEFAULT_WEIGHT",
    "term_of",
    "weight_of",
    "parse_line",
]
