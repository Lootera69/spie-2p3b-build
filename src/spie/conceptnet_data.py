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

SOURCE_DUMP_SHA256 = "accd65fe94038584295574ddc26e1500c1919c8c4532bf771811cafd0948af7e"
"""sha256 of the input assertions dump — input provenance. Empty only while the artifact is
empty (no dump has been read yet)."""

BUILD_PARAMS: dict[str, object] = {
    'cap': 120,
    'conceptnet_version': '5.7.0',
    'dump': 'conceptnet-assertions-5.7.0.csv.gz',
    'isa_hops': 3,
    'max_hops': 1,
    'max_out_edges': 6,
    'min_out_edges': 1,
    'seeds': 9,
    'size_max': 200,
    'size_min': 1,
    'target': 0,
    'weight_min': 1.0,
}
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

CONCEPTNET_RECORDS: tuple[ConceptNetRecord, ...] = (
    ("action", (("PartOf", ("gun",)),), ("connect",)),
    ("airplane", (("IsA", ("vehicle",)), ("UsedFor", ("travel",))), ("connect",)),
    ("alcohol", (("IsA", ("beverage", "drink", "fuel", "liquid")),), ("consume", "propagate")),
    ("animals", (("CapableOf", ("drink", "travel")), ("IsA", ("food",))), ("connect", "consume")),
    ("area", (("IsA", ("place", "structure")),), ("connect", "preserve")),
    (
        "bag",
        (("Causes", ("travel",)), ("IsA", ("container",)), ("UsedFor", ("hold",))),
        ("connect", "preserve", "propagate"),
    ),
    (
        "bar",
        (("IsA", ("barrier", "business", "place", "support")), ("PartOf", ("court",))),
        ("connect", "consume", "negate"),
    ),
    (
        "beam",
        (("IsA", ("light",)), ("UsedFor", ("hold", "support"))),
        ("connect", "consume", "preserve"),
    ),
    ("bed", (("IsA", ("place",)), ("UsedFor", ("hold",))), ("connect", "preserve")),
    ("beverage", (("IsA", ("food", "liquid")),), ("consume", "propagate")),
    ("blue", (("IsA", ("organization",)),), ("preserve",)),
    ("boat", (("IsA", ("vehicle", "vessel")), ("UsedFor", ("travel",))), ("connect", "preserve")),
    ("book", (("UsedFor", ("resource",)),), ("consume",)),
    (
        "box",
        (("IsA", ("area", "container")), ("UsedFor", ("hold", "store"))),
        ("connect", "preserve"),
    ),
    ("building", (("IsA", ("structure",)),), ("preserve",)),
    ("business", (("IsA", ("organization",)),), ("preserve",)),
    ("case", (("IsA", ("container",)),), ("preserve",)),
    ("cell", (("IsA", ("room",)),), ("connect",)),
    ("chemical", (("IsA", ("material",)),), ("connect",)),
    ("cleaning", (("UsedFor", ("organization",)),), ("connect",)),
    (
        "computer",
        (("HasProperty", ("machine",)), ("IsA", ("machine", "tool")), ("UsedFor", ("writing",))),
        ("connect",),
    ),
    ("cooking", (("Causes", ("food",)), ("IsA", ("action",))), ("consume", "propagate")),
    ("court", (("IsA", ("area", "room")), ("PartOf", ("building",))), ("connect", "preserve")),
    ("direction", (("IsA", ("path",)),), ("connect",)),
    (
        "dish",
        (("IsA", ("container",)), ("UsedFor", ("cooking", "food", "hold"))),
        ("consume", "preserve"),
    ),
    ("drink", (("IsA", ("liquid",)),), ("consume", "propagate")),
    ("driving", (("IsA", ("action", "travel")),), ("connect",)),
    ("earth", (("HasProperty", ("finite",)), ("IsA", ("material", "thing"))), ("consume",)),
    ("enclosure", (("IsA", ("area", "space")),), ("connect", "consume", "preserve")),
    ("energy", (("IsA", ("force",)),), ("consume",)),
    (
        "floor",
        (("IsA", ("room", "structure")), ("PartOf", ("building",)), ("UsedFor", ("walk",))),
        ("connect", "preserve"),
    ),
    ("flow", (("IsA", ("motion",)),), ("consume", "propagate")),
    ("flower", (("CapableOf", ("open",)),), ("connect",)),
    ("food", (("IsA", ("fuel",)), ("UsedFor", ("energy",))), ("consume",)),
    ("force", (("IsA", ("organization",)),), ("preserve",)),
    ("game", (("IsA", ("meat",)),), ("consume",)),
    ("gas", (("UsedFor", ("cooking", "fuel", "heat", "light")),), ("consume", "propagate")),
    ("glass", (("IsA", ("container", "vehicle")), ("UsedFor", ("hold",))), ("connect", "preserve")),
    ("gun", (("UsedFor", ("fire",)),), ("connect",)),
    ("hair", (("PartOf", ("head",)),), ("connect",)),
    ("handle", (("PartOf", ("door",)),), ("connect",)),
    ("happiness", (("CapableOf", ("spread",)),), ("propagate",)),
    ("head", (("IsA", ("pressure", "structure")),), ("preserve", "propagate")),
    (
        "hole",
        (("IsA", ("opening", "space")), ("UsedFor", ("water",))),
        ("connect", "consume", "preserve", "propagate"),
    ),
    (
        "house",
        (("IsA", ("building", "place", "structure", "thing")), ("PartOf", ("street",))),
        ("connect", "preserve"),
    ),
    (
        "ice",
        (("IsA", ("drink", "material", "water")), ("UsedFor", ("drink",))),
        ("consume", "propagate"),
    ),
    ("leg", (("IsA", ("support",)), ("UsedFor", ("hold",))), ("consume", "preserve")),
    ("life", (("HasProperty", ("energy", "finite")),), ("consume",)),
    ("light", (("CapableOf", ("travel",)), ("IsA", ("energy",))), ("connect", "consume")),
    ("liquid", (("CapableOf", ("flow",)),), ("propagate",)),
    ("machine", (("IsA", ("organization",)),), ("preserve",)),
    ("material", (("IsA", ("information",)),), ("connect",)),
    ("meat", (("IsA", ("food",)), ("UsedFor", ("food", "fuel"))), ("consume",)),
    ("motion", (("IsA", ("energy",)),), ("consume",)),
    ("newspaper", (("HasProperty", ("light",)),), ("connect",)),
    ("number", (("IsA", ("information",)),), ("connect",)),
    (
        "opening",
        (("IsA", ("motion", "performing", "space")),),
        ("connect", "consume", "preserve", "propagate"),
    ),
    ("organization", (("IsA", ("structure",)),), ("preserve",)),
    ("pain", (("PartOf", ("life",)),), ("connect",)),
    ("passage", (("IsA", ("structure", "way")),), ("connect", "preserve")),
    ("performing", (("Causes", ("action", "happiness")), ("IsA", ("action",))), ("propagate",)),
    ("pipe", (("IsA", ("container",)),), ("preserve",)),
    ("pistol", (("IsA", ("gun",)), ("UsedFor", ("fire",))), ("connect",)),
    ("place", (("IsA", ("passage",)),), ("connect", "preserve")),
    ("practice", (("IsA", ("information",)),), ("connect",)),
    ("rain", (("HasProperty", ("water",)), ("IsA", ("water",))), ("consume", "propagate")),
    (
        "remembering",
        (("Causes", ("pain",)), ("IsA", ("action",)), ("UsedFor", ("happiness", "memory"))),
        ("propagate",),
    ),
    ("round", (("IsA", ("path",)),), ("connect",)),
    ("shop", (("IsA", ("store",)),), ("preserve",)),
    ("space", (("IsA", ("area", "time")),), ("connect", "consume", "preserve")),
    ("street", (("UsedFor", ("driving", "travel")),), ("connect",)),
    ("structure", (("IsA", ("system",)),), ("preserve",)),
    ("support", (("IsA", ("resource",)),), ("consume",)),
    ("symbol", (("IsA", ("signal",)),), ("propagate",)),
    ("system", (("UsedFor", ("organization", "store")),), ("preserve",)),
    ("thing", (("IsA", ("action",)),), ("connect",)),
    (
        "time",
        (("HasProperty", ("finite",)), ("IsA", ("case", "resource"))),
        ("consume", "preserve"),
    ),
    ("title", (("IsA", ("writing",)), ("UsedFor", ("book", "information"))), ("connect",)),
    ("tool", (("UsedFor", ("building",)),), ("connect",)),
    (
        "vehicle",
        (("CapableOf", ("travel",)), ("IsA", ("machine",)), ("UsedFor", ("travel",))),
        ("connect",),
    ),
    ("vessel", (("IsA", ("boat", "container")),), ("connect", "preserve")),
    ("walk", (("IsA", ("path", "travel")),), ("connect",)),
    ("wall", (("PartOf", ("building", "house", "room", "structure")),), ("negate",)),
    ("way", (("IsA", ("path",)),), ("connect",)),
    ("wood", (("IsA", ("fuel", "material")), ("UsedFor", ("building",))), ("consume",)),
    ("writing", (("UsedFor", ("information",)),), ("connect",)),
)
"""The derived vocabulary, sorted canonically: records by ``name``, each record's relations by
relation value, each relation's targets and each record's affordances sorted and deduplicated.
Empty until ``tools/conceptnet_build`` populates it."""

ARTIFACT_HASH = "sha256:3c9b78630a451e86c9351a37b837858970faa3ec77cc4bef0acee580db96ae65"
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
