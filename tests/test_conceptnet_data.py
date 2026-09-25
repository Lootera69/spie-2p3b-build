"""Step 2 tests — the ConceptNet vocabulary layer is *provably* additive and *provably* the
artifact the offline build gate certified.

The heavy proof for this layer happens **offline**: ``tools/conceptnet_build`` runs every candidate
word through ``invent`` -> ``validate`` -> ``certify`` -> ``verify`` at seeds 0-8 (plus the
presentation bijection) and keeps only the words that pass, so the shipped vocabulary is sound *by
construction*. That offline proof only transfers to the running engine if the shipped artifact is
exactly what was gated — which is what :func:`test_artifact_content_hash_is_stable` establishes.
It is the bridge between the build-time gate and run time, and the reason the solver-bearing
full-KB sweeps may be scoped to :data:`~spie.concepts.CURATED_WORDS` without opening a soundness
hole.

The rest of the module proves the *additivity* claim the whole step rests on: the curated core is
byte-unperturbed, the merged KB is still closed (no dangling edge, which would crash every
KB-importing test at import), and the CC BY-SA attribution cannot become separated from the data.
"""

from __future__ import annotations

import hashlib
import os
import re

from spie import conceptnet_data
from spie.conceptnet_data import (
    ARTIFACT_HASH,
    BUILD_PARAMS,
    CONCEPTNET_ATTRIBUTION,
    CONCEPTNET_RECORDS,
    CONCEPTNET_VERSION,
    SOURCE_DUMP_SHA256,
)
from spie.concepts import _CONCEPTS, CURATED_WORDS, KB, Affordance, Relation, _check_integrity

# The ConceptNet layer as it was re-typed into Concepts, and the repo-root NOTICE.
_CN = tuple(c for c in KB.values() if c.name not in set(CURATED_WORDS))
_NOTICE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "NOTICE"))

# A ConceptNet term is a single lower-case ASCII token (the offline filter's contract).
_TERM = re.compile(r"^[a-z0-9-]+$")


# --- The rigor bridge: the shipped artifact is what the offline gate certified ---------------


def test_artifact_content_hash_is_stable() -> None:
    """The bridge from the build-time certify gate to run time.

    ``ARTIFACT_HASH`` is a *pinned literal* the build tool emitted alongside the records it had
    just proven certifiable. Recomputing it here from ``repr(CONCEPTNET_RECORDS)`` — the data
    structure, so reformatting the generated source is irrelevant — proves the shipped vocabulary
    is byte-identical to the gated one. Any later hand edit to the records breaks this test."""
    recomputed = "sha256:" + hashlib.sha256(repr(CONCEPTNET_RECORDS).encode("utf-8")).hexdigest()
    assert recomputed == ARTIFACT_HASH, "the artifact was edited after the build gate certified it"
    # The module's own published recipe must agree with the recomputation above.
    assert conceptnet_data.compute_artifact_hash() == ARTIFACT_HASH


def test_declared_build_provenance_is_consistent_with_the_data() -> None:
    """Provenance and data never drift apart: an empty artifact declares no source dump and no
    build parameters, and a populated one declares both *and* lands inside its own declared size
    band. So neither emptying the records nor widening them past the approved scope can pass
    silently."""
    assert CONCEPTNET_VERSION == "5.7.0"
    if not CONCEPTNET_RECORDS:
        assert SOURCE_DUMP_SHA256 == "" and BUILD_PARAMS == {}, "provenance without data"
        return
    assert len(SOURCE_DUMP_SHA256) == 64, "a populated artifact must pin its source dump"
    assert BUILD_PARAMS, "a populated artifact must record how to regenerate it"
    lo, hi = BUILD_PARAMS["size_min"], BUILD_PARAMS["size_max"]
    assert lo <= len(CONCEPTNET_RECORDS) <= hi, f"{len(CONCEPTNET_RECORDS)} outside [{lo}, {hi}]"


# --- Additivity: the curated core is untouched and the merged KB is still closed --------------


def test_curated_core_is_unperturbed_by_the_merge() -> None:
    """Every curated concept survives the merge *by value* and the curated core still has exactly
    its 35 authored words. This is the structural half of the byte-identity argument: since
    ``expand`` follows outgoing edges only, an unperturbed curated concept expands — and so
    invents — exactly as before (the invention pins in ``test_invent`` are the other half)."""
    assert len(CURATED_WORDS) == 35
    assert CURATED_WORDS == tuple(sorted(c.name for c in _CONCEPTS))
    for concept in _CONCEPTS:
        assert KB[concept.name] == concept, f"curated concept {concept.name!r} was perturbed"
        assert KB[concept.name] is concept, "curated entry replaced by an equal ConceptNet record"


def test_merged_kb_is_closed_and_well_typed() -> None:
    """The merged KB satisfies the same invariants the curated KB always did: no dangling relation
    target (an unclosed subgraph would raise at import and take every KB-importing test with it),
    and every relation/affordance is a real enum member."""
    _check_integrity()  # re-assert the import-time invariant explicitly
    assert len(KB) == len(CURATED_WORDS) + len(_CN)
    for concept in KB.values():
        for relation, targets in concept.relations.items():
            assert isinstance(relation, Relation)
            for target in targets:
                assert target in KB, f"dangling edge {concept.name!r} -> {target!r}"
        for affordance in concept.affordances:
            assert isinstance(affordance, Affordance)


def test_conceptnet_terms_are_single_token_ascii() -> None:
    """The offline filter's contract: ConceptNet names are single lower-case ASCII tokens, so no
    rendered puzzle can carry a non-ASCII or multi-word concept name (the renderer is ASCII-only).
    Vacuous while the artifact is empty; binding from the first generated vocabulary on."""
    assert len(_CN) == len(CONCEPTNET_RECORDS)
    for concept in _CN:
        assert _TERM.match(concept.name), f"{concept.name!r} is not a single ASCII token"
        assert concept.name not in set(CURATED_WORDS), "a ConceptNet record shadows a curated word"


# --- Licensing: attribution cannot be separated from the data --------------------------------


def test_attribution_travels_with_the_data() -> None:
    """CC BY-SA 4.0 is a share-alike license, so attribution must survive any redistribution: it is
    embedded in the generated module itself *and* stated in the repository NOTICE, and both name
    the license and the required citation."""
    for text in (CONCEPTNET_ATTRIBUTION, open(_NOTICE, encoding="utf-8").read()):
        assert "ConceptNet" in text
        assert "CC BY-SA 4.0" in text
        assert "creativecommons.org/licenses/by-sa/4.0" in text
        assert "Speer" in text and "Havasi" in text and "AAAI" in text
    notice = open(_NOTICE, encoding="utf-8").read()
    assert "src/spie/conceptnet_data.py" in notice, "the NOTICE must name the covered file"
    assert all(ord(ch) < 128 for ch in CONCEPTNET_ATTRIBUTION), "attribution must be ASCII"
