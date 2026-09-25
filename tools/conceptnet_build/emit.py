"""Emit the frozen artifact ``src/spie/conceptnet_data.py`` and audit the repository ``NOTICE``.

Two things make emission delicate:

* **The artifact lives inside ``src``.** Unlike the rest of ``tools/`` it is *shipped*, so it must
  pass ``ruff check src tests`` — every line <= 100 columns. A ConceptNet record can nest four
  tuples deep, so the records literal is written by a recursive pretty-printer
  (:func:`render_value`) that breaks any value that would overflow, guaranteeing the column bound
  for arbitrary data.
* **The content hash must not depend on the formatting.** ``ARTIFACT_HASH`` is
  ``"sha256:" + sha256(repr(records))`` — over the *runtime tuple*, not the emitted text — so the
  pretty-printer's line breaks and quote style are irrelevant to it. Parsing the emitted literal
  back yields a tuple whose ``repr`` reproduces the hash; that identity is what
  ``tests/test_conceptnet_data.py`` checks.

The module header (docstring, imports, type alias, version, attribution, ``compute_artifact_hash``,
``__all__``) is a fixed template held here verbatim, so only four things ever vary between builds:
``SOURCE_DUMP_SHA256``, ``BUILD_PARAMS``, ``CONCEPTNET_RECORDS`` and the derived ``ARTIFACT_HASH``.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence

from .prune import Record

_MAX_COLS = 100


def _flat(value: object) -> str:
    """The compact single-line rendering of a records value (double-quoted ASCII strings)."""
    if isinstance(value, str):
        return '"' + value + '"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, tuple):
        if len(value) == 1:
            return "(" + _flat(value[0]) + ",)"
        return "(" + ", ".join(_flat(item) for item in value) + ")"
    raise TypeError(f"non-artifact value {value!r}")


def render_value(value: object, indent: int, *, width: int = _MAX_COLS) -> str:
    """A <=``width`` rendering of ``value``; the first line is unindented, the rest indented.

    Reserves one column for a trailing comma at every level, so an element line ``"    " + text +
    ","`` still fits. Only tuples can be broken; a leaf too long to fit is emitted whole (our terms
    never approach the limit, so this never happens in practice)."""
    flat = _flat(value)
    if indent + len(flat) + 1 <= width or not isinstance(value, tuple):
        return flat
    inner = indent + 4
    lines = ["("]
    for item in value:
        lines.append(" " * inner + render_value(item, inner, width=width) + ",")
    lines.append(" " * indent + ")")
    return "\n".join(lines)


def _render_build_params(params: Mapping[str, object]) -> str:
    """``BUILD_PARAMS`` as a stable, one-key-per-line dict literal (keys sorted)."""
    if not params:
        return "{}"
    lines = ["{"]
    for key in sorted(params):
        lines.append(f'    {key!r}: {params[key]!r},')
    lines.append("}")
    return "\n".join(lines)


_HEADER = '''\
"""Step 2 — the generated ConceptNet vocabulary layer (offline, additive, **never hand-edited**).

GENERATED FILE — produced by ``tools/conceptnet_build`` from a pinned ConceptNet 5.7 dump and
checked in as a frozen artifact. Regenerate it with the command recorded in :data:`BUILD_PARAMS`;
never edit it by hand: :data:`ARTIFACT_HASH` pins the exact content the offline build gate proved
certifiable, and ``tests/test_conceptnet_data.py`` recomputes that hash.

Why a generated ``.py`` literal of *plain data*:

* **Offline and reproducible.** ConceptNet is consulted once, at build time, from a dump pinned by
  :data:`SOURCE_DUMP_SHA256`. Importing this module touches no network, no API and no model, so
  the engine's LLM-free, byte-reproducible thesis is untouched.
* **Plain primitives, not :class:`~spie.concepts.Concept` objects.** A record is nothing but
  ``str`` and ``tuple``, so this module imports nothing from :mod:`spie`: there is no
  ``conceptnet_data`` <-> ``concepts`` import cycle, and every record stays hashable.
* **Additive by construction.** :mod:`spie.concepts` seats its hand-curated core *first* and only
  then admits these records under still-unused names, so a ConceptNet entry can never shadow a
  curated concept nor add an out-edge onto one — and since ``expand`` walks *outgoing* edges only,
  every curated word's invented puzzle stays byte-identical.
* **Certify-gated vocabulary.** Every word stored here was proven offline to invent a puzzle that
  ``validate``s clean, ``certify``s solvable/unique/conformant and passes ``verify`` at seeds 0-8.
  Vocabulary growth is therefore gated by the formal solvers, exactly like the rest of the engine.

ConceptNet is CC BY-SA 4.0: see :data:`CONCEPTNET_ATTRIBUTION`, which travels *with* the data, and
the repository ``NOTICE``.
"""

from __future__ import annotations

import hashlib

# One artifact record: (name, ((relation_value, (target, ...)), ...), (affordance_value, ...)).
# The relation/affordance strings are the *values* of spie.concepts.Relation / .Affordance, spelled
# as plain ``str`` to keep this module dependency-free; ``concepts._record_to_concept`` re-types
# them (an unknown value therefore fails loudly at import, not silently at invention time).
ConceptNetRecord = tuple[str, tuple[tuple[str, tuple[str, ...]], ...], tuple[str, ...]]

CONCEPTNET_VERSION = "5.7.0"
"""The ConceptNet release these records were derived from."""

SOURCE_DUMP_SHA256 = "{source_dump_sha256}"
"""sha256 of the input assertions dump — input provenance. Empty only while the artifact is
empty (no dump has been read yet)."""

BUILD_PARAMS: dict[str, object] = {build_params}
"""The exact selection parameters the build ran with, so the artifact can be regenerated.
Empty only while the artifact is empty."""

CONCEPTNET_ATTRIBUTION = (
    "This vocabulary layer is derived from ConceptNet 5.7 (https://conceptnet.io), licensed "
    "under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). Attribution: Robyn "
    "Speer, Joshua Chin, and Catherine Havasi. 2017. 'ConceptNet 5.5: An Open Multilingual "
    "Graph of General Knowledge.' In Proceedings of the Thirty-First AAAI Conference on "
    "Artificial Intelligence (AAAI-17), pages 4444-4451. Share-alike: redistributions of this "
    "derived data must carry the same license."
)
"""The CC BY-SA 4.0 attribution, embedded here so it can never be separated from the data it
covers (the repository ``NOTICE`` carries the same text)."""

CONCEPTNET_RECORDS: tuple[ConceptNetRecord, ...] = {records}
"""The derived vocabulary, sorted canonically: records by ``name``, each record's relations by
relation value, each relation's targets and each record's affordances sorted and deduplicated.
Empty until ``tools/conceptnet_build`` populates it."""

ARTIFACT_HASH = "{artifact_hash}"
"""The content hash the build tool emitted for :data:`CONCEPTNET_RECORDS` — a *pinned literal*,
not a recomputation, so any later hand edit to the records is caught by the test that recomputes
it. Hashed over ``repr(records)`` (the data structure) rather than the file bytes, so reformatting
the generated source cannot break it."""


def compute_artifact_hash(records: tuple[ConceptNetRecord, ...] = CONCEPTNET_RECORDS) -> str:
    """The canonical content hash of a records tuple — the recipe :data:`ARTIFACT_HASH` pins.

    A pure function of the data structure (via ``repr``), shared by the offline build tool and the
    test that verifies the shipped artifact is exactly what the build gate certified."""
    return "sha256:" + hashlib.sha256(repr(records).encode("utf-8")).hexdigest()


__all__ = [
    "ConceptNetRecord",
    "CONCEPTNET_VERSION",
    "SOURCE_DUMP_SHA256",
    "BUILD_PARAMS",
    "CONCEPTNET_ATTRIBUTION",
    "CONCEPTNET_RECORDS",
    "ARTIFACT_HASH",
    "compute_artifact_hash",
]
'''


def compute_artifact_hash(records: Sequence[Record]) -> str:
    """``ARTIFACT_HASH`` for ``records`` — identical recipe to the shipped module's own function."""
    return "sha256:" + hashlib.sha256(repr(tuple(records)).encode("utf-8")).hexdigest()


def render_module(
    records: Sequence[Record], *, source_dump_sha256: str, build_params: Mapping[str, object]
) -> str:
    """The full text of ``conceptnet_data.py`` for ``records`` and its build provenance."""
    return _HEADER.format(
        source_dump_sha256=source_dump_sha256,
        build_params=_render_build_params(build_params),
        records=render_value(tuple(records), 0),
        artifact_hash=compute_artifact_hash(records),
    )


def write_artifact(
    path: str,
    records: Sequence[Record],
    *,
    source_dump_sha256: str,
    build_params: Mapping[str, object],
) -> str:
    """Write the artifact module and return its ``ARTIFACT_HASH`` (for the build's own logging)."""
    text = render_module(
        records, source_dump_sha256=source_dump_sha256, build_params=build_params
    )
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return compute_artifact_hash(records)


# --- NOTICE ----------------------------------------------------------------------------------

# The exact tokens ``tests/test_conceptnet_data.py`` requires the NOTICE to carry.
_NOTICE_TOKENS: tuple[str, ...] = (
    "ConceptNet",
    "CC BY-SA 4.0",
    "creativecommons.org/licenses/by-sa/4.0",
    "Speer",
    "Havasi",
    "AAAI",
    "src/spie/conceptnet_data.py",
)

NOTICE_TEXT = """\
NOTICE
======

This project is original work. One generated data file bundles a derivative of a third-party
dataset, and this NOTICE records its provenance and license so attribution can never be
separated from the data.

Covered file
------------

    src/spie/conceptnet_data.py

That file is a *generated* vocabulary layer produced offline by ``tools/conceptnet_build`` from a
pinned ConceptNet 5.7 assertions dump. It is checked in as a frozen artifact; it is never edited
by hand and is not required to build or run the rest of the engine.

ConceptNet license and attribution
----------------------------------

ConceptNet is made available under the Creative Commons Attribution-ShareAlike 4.0 International
license (CC BY-SA 4.0): https://creativecommons.org/licenses/by-sa/4.0/

    Robyn Speer, Joshua Chin, and Catherine Havasi. 2017. "ConceptNet 5.5: An Open Multilingual
    Graph of General Knowledge." In Proceedings of the Thirty-First AAAI Conference on Artificial
    Intelligence (AAAI-17), pages 4444-4451.

Share-alike: because CC BY-SA 4.0 is a share-alike license, any redistribution of the derived
data in ``src/spie/conceptnet_data.py`` must carry this same license and attribution. The same
attribution text is embedded in that module as ``CONCEPTNET_ATTRIBUTION`` so it travels with the
data even when this NOTICE does not.

What was derived, and how
-------------------------

ConceptNet supplies typed relations (IsA, UsedFor, CapableOf, HasProperty, Causes, PartOf) but no
notion of a puzzle mechanic. The build tool streams the dump, keeps only single-token English
endpoints on those six relations, selects a bounded neighbourhood of the engine's hand-curated
core, and *derives* each word's puzzle affordances by a deterministic rule table plus IsA
inheritance (no model, no learning). Only words that provably invent a puzzle the formal solvers
certify are kept. The result is the plain-data records tuple in the covered file.

The engine's hand-curated concept core (in ``src/spie/concepts.py``) is original work and remains
the default vocabulary; the ConceptNet layer is a clearly-attributed additive extension.
"""


def check_notice(path: str) -> list[str]:
    """The required attribution tokens missing from the NOTICE at ``path`` (``[]`` when all
    present).

    An absent file counts as every token missing."""
    if not os.path.exists(path):
        return list(_NOTICE_TOKENS)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return [token for token in _NOTICE_TOKENS if token not in text]


def write_notice(path: str) -> None:
    """(Over)write the repository NOTICE from :data:`NOTICE_TEXT`."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(NOTICE_TEXT)


__all__ = [
    "render_value",
    "compute_artifact_hash",
    "render_module",
    "write_artifact",
    "NOTICE_TEXT",
    "check_notice",
    "write_notice",
]
