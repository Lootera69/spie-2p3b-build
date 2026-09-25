"""Phase 4.1 — the concept knowledge base and the pipeline's first two stages (Sense, Expand).

The roadmap's INPUT→MEANING pipeline begins with words. This module supplies the *meaning*
substrate the later stages compile into mechanics:

* a **relation lexicon** (:data:`KB`) — the hand-authored curated core (:data:`CURATED_WORDS`),
  widened by the additive offline ConceptNet layer of :mod:`spie.conceptnet_data` — carrying typed
  edges (IsA / UsedFor / CapableOf / HasProperty / Causes / PartOf) plus, on each concept, the
  **puzzle affordances** it suggests (connect / consume / propagate / delay / reveal / negate /
  preserve);
* :func:`sense` — a word becomes a typed :class:`ConceptNode` (normalized, looked up in the KB);
* :func:`expand` — a bounded, deterministic breadth-first walk of the KB from a root concept into
  a local :class:`SemanticGraph`.

Design commitments (see the Phase-4 plan):

* **Static and deterministic, never a live API or an LLM.** The KB is plain in-repo data — the
  curated core plus a *frozen, generated* artifact derived offline from a pinned ConceptNet dump —
  and every traversal sorts its frontier, so an ``expand`` is byte-reproducible.
* **The curated core is never perturbed.** :func:`_merge_kb` seats the curated concepts first and
  admits a ConceptNet record only under a still-unused name, and the offline build emits no
  out-edge *from* a curated concept. Since :func:`expand` follows outgoing edges only, every
  curated word's semantic graph — and hence its invented puzzle — is byte-identical to what the
  pre-ConceptNet engine produced.
* **No dangling edges.** Every relation *target* is itself a concept key in the KB; this is an
  invariant asserted at import time by :func:`_check_integrity` and exercised by the tests, so the
  semantic graph is always closed.
* **No dependency on the semantic core.** This module constructs no :class:`~spie.ir.Puzzle`; it
  produces meaning only. Stage 4.2 (``afford``) turns affordances into mechanics.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from .conceptnet_data import CONCEPTNET_RECORDS, ConceptNetRecord


class Relation(str, Enum):
    """A typed semantic edge — the roadmap's six curated relation kinds."""

    IS_A = "IsA"
    USED_FOR = "UsedFor"
    CAPABLE_OF = "CapableOf"
    HAS_PROPERTY = "HasProperty"
    CAUSES = "Causes"
    PART_OF = "PartOf"


class Affordance(str, Enum):
    """A puzzle *operation* a concept suggests — the bridge from meaning to mechanic.

    These are the roadmap's Afford-stage operations; stage 4.2 maps each to a mechanic template
    (e.g. :attr:`CONSUME` → a depletable resource variable, :attr:`REVEAL` → a hidden variable
    plus a sensing action, :attr:`DELAY` → a ``DELAYED`` variable, :attr:`PRESERVE` → a
    ``persistent`` variable / ``Reset``).
    """

    CONNECT = "connect"
    CONSUME = "consume"
    PROPAGATE = "propagate"
    DELAY = "delay"
    REVEAL = "reveal"
    NEGATE = "negate"
    PRESERVE = "preserve"


@dataclass(frozen=True)
class Concept:
    """One curated entry of the knowledge base.

    ``relations`` maps each :class:`Relation` present on this concept to the tuple of target
    concept *names* (every target is itself a KB key — see :func:`_check_integrity`).
    ``affordances`` is the set of puzzle operations this concept suggests.
    """

    name: str
    relations: dict[Relation, tuple[str, ...]] = field(default_factory=dict)
    affordances: tuple[Affordance, ...] = ()


@dataclass(frozen=True)
class ConceptNode:
    """A *sensed* concept: the normalized entry point into the KB for one word.

    Carries the concept's canonical ``name`` and its ``affordances`` so the Afford stage can act
    on it directly; :func:`expand` walks the KB from this node."""

    name: str
    affordances: tuple[Affordance, ...]


@dataclass(frozen=True)
class SemanticGraph:
    """A bounded local neighbourhood of the KB around a root concept.

    Both ``concepts`` and ``edges`` are sorted and deduplicated, so the graph is a deterministic
    function of ``(root, depth)`` — the reproducibility the pipeline relies on."""

    root: str
    concepts: tuple[str, ...]
    edges: tuple[tuple[str, Relation, str], ...]

    def affordances(self) -> dict[str, tuple[Affordance, ...]]:
        """Affordances of every concept in the graph, keyed by concept name (sorted keys)."""
        return {name: KB[name].affordances for name in self.concepts}


# ---------------------------------------------------------------------------
# The curated knowledge base
# ---------------------------------------------------------------------------

# Every concept below is a node; every name appearing as a relation target is itself a concept
# here (closure is asserted at import). Abstract categories (barrier/resource/…), property leaves
# (hidden/delayed/…) and capability/use leaves (travel/store/…) are concepts too, mirroring
# ConceptNet's "everything is a node" design, so HasProperty / UsedFor / CapableOf edges resolve.

R = Relation
A = Affordance

_CONCEPTS: tuple[Concept, ...] = (
    # --- abstract categories -----------------------------------------------------------------
    Concept("barrier", {R.HAS_PROPERTY: ("blocking",)}, (A.NEGATE,)),
    Concept("resource", {R.HAS_PROPERTY: ("finite",)}, (A.CONSUME,)),
    Concept("path", {R.USED_FOR: ("travel",)}, (A.CONNECT,)),
    Concept("container", {R.CAPABLE_OF: ("hold",)}, (A.PRESERVE,)),
    Concept("information", {R.HAS_PROPERTY: ("hidden",)}, (A.REVEAL,)),
    # --- property leaves ---------------------------------------------------------------------
    Concept("blocking", affordances=(A.NEGATE,)),
    Concept("finite", affordances=(A.CONSUME,)),
    Concept("hidden", affordances=(A.REVEAL,)),
    Concept("delayed", affordances=(A.DELAY,)),
    Concept("rising", affordances=(A.PROPAGATE,)),
    # --- capability / use leaves -------------------------------------------------------------
    Concept("travel", affordances=(A.CONNECT,)),
    Concept("hold", affordances=(A.PRESERVE,)),
    Concept("unlock", affordances=(A.NEGATE,)),
    Concept("secure", affordances=(A.NEGATE,)),
    Concept("store", affordances=(A.PRESERVE,)),
    Concept("toggle", affordances=(A.NEGATE,)),
    Concept("open", affordances=(A.NEGATE,)),
    Concept("deplete", affordances=(A.CONSUME,)),
    Concept("spread", affordances=(A.PROPAGATE,)),
    Concept("heat", {R.HAS_PROPERTY: ("rising",)}, (A.PROPAGATE,)),
    # --- concrete concepts -------------------------------------------------------------------
    Concept("door", {R.IS_A: ("barrier",), R.USED_FOR: ("travel",)}, (A.CONNECT, A.NEGATE)),
    Concept("gate", {R.IS_A: ("barrier",), R.USED_FOR: ("travel",)}, (A.CONNECT, A.NEGATE)),
    Concept("lock", {R.IS_A: ("barrier",), R.USED_FOR: ("secure",)}, (A.NEGATE, A.REVEAL)),
    Concept("key", {R.USED_FOR: ("unlock",)}, (A.REVEAL,)),
    Concept("lever", {R.CAPABLE_OF: ("toggle",), R.USED_FOR: ("open",)}, (A.NEGATE,)),
    Concept("bridge", {R.IS_A: ("path",), R.USED_FOR: ("travel",)}, (A.CONNECT,)),
    Concept("room", {R.IS_A: ("container",)}, (A.CONNECT,)),
    Concept("fuel", {R.IS_A: ("resource",), R.USED_FOR: ("travel",),
                     R.CAPABLE_OF: ("deplete",)}, (A.CONSUME,)),
    Concept("water", {R.IS_A: ("resource",), R.CAPABLE_OF: ("spread",)}, (A.CONSUME, A.PROPAGATE)),
    Concept("battery", {R.IS_A: ("resource",), R.CAPABLE_OF: ("store",)},
            (A.CONSUME, A.PRESERVE)),
    Concept("fire", {R.CAUSES: ("heat",), R.CAPABLE_OF: ("spread",)}, (A.PROPAGATE, A.CONSUME)),
    Concept("pressure", {R.HAS_PROPERTY: ("rising",)}, (A.PROPAGATE,)),
    Concept("signal", {R.IS_A: ("information",), R.HAS_PROPERTY: ("delayed",)},
            (A.DELAY, A.PROPAGATE)),
    Concept("memory", {R.IS_A: ("information",), R.CAPABLE_OF: ("store",)},
            (A.PRESERVE, A.REVEAL)),
    Concept("prize", {R.IS_A: ("information",)}, (A.REVEAL,)),
)

CURATED_WORDS: tuple[str, ...] = tuple(sorted(c.name for c in _CONCEPTS))
"""The hand-curated core vocabulary, sorted. These are the words whose invented puzzles the test
suite pins *exhaustively*; the wider ConceptNet layer is proven by the offline build gate and
sampled at test time (see :mod:`spie.conceptnet_data`)."""


# ---------------------------------------------------------------------------
# The additive ConceptNet layer (Step 2)
# ---------------------------------------------------------------------------


def _record_to_concept(record: ConceptNetRecord) -> Concept:
    """Re-type one plain-data artifact record into a frozen :class:`Concept`.

    The artifact stores primitives only (see :mod:`spie.conceptnet_data`), so an unrecognized
    relation or affordance value raises here, at import — never silently at invention time."""
    name, relations, affordances = record
    return Concept(
        name=name,
        relations={Relation(r): tuple(targets) for r, targets in relations},
        affordances=tuple(Affordance(a) for a in affordances),
    )


_CN_CONCEPTS: tuple[Concept, ...] = tuple(_record_to_concept(r) for r in CONCEPTNET_RECORDS)


def _merge_kb(curated: tuple[Concept, ...], extra: tuple[Concept, ...]) -> dict[str, Concept]:
    """Merge the two vocabulary layers so the **curated core always wins**.

    ``curated`` is seated first and an ``extra`` entry is admitted only under a name still unused,
    so a ConceptNet record can never shadow — or otherwise perturb — a curated concept."""
    merged = {c.name: c for c in curated}
    for concept in extra:
        merged.setdefault(concept.name, concept)
    return merged


KB: dict[str, Concept] = _merge_kb(_CONCEPTS, _CN_CONCEPTS)
"""The concept knowledge base, indexed by canonical concept name: the curated core
(:data:`CURATED_WORDS`) plus the additive ConceptNet layer, curated entries winning collisions."""


def _check_integrity() -> None:
    """Assert the merged KB is closed: every relation target is a known concept, and no name
    repeats within a vocabulary layer.

    Called at import so a malformed edit — or a ConceptNet artifact whose subgraph the offline
    build failed to close — fails loudly rather than producing a dangling graph."""
    for layer, concepts in (("curated", _CONCEPTS), ("ConceptNet", _CN_CONCEPTS)):
        if len({c.name for c in concepts}) != len(concepts):
            raise ValueError(f"duplicate concept name in the {layer} knowledge base")
    for concept in KB.values():
        for relation, targets in concept.relations.items():
            for target in targets:
                if target not in KB:
                    raise ValueError(
                        f"dangling {relation.value} edge {concept.name!r} -> {target!r}: "
                        "target is not a known concept"
                    )


_check_integrity()


# ---------------------------------------------------------------------------
# Stage 1 (Sense) and stage 2 (Expand)
# ---------------------------------------------------------------------------


def normalize(word: str) -> str:
    """Canonicalize a raw input word to a KB key: strip surrounding whitespace, lower-case."""
    return word.strip().lower()


def sense(word: str) -> ConceptNode:
    """Sense: map a raw word to its typed :class:`ConceptNode`.

    Raises :class:`KeyError` for a word with no KB entry — the pipeline is deliberately *total*
    over its curated vocabulary and refuses to hallucinate meaning for an unknown word."""
    name = normalize(word)
    concept = KB.get(name)
    if concept is None:
        raise KeyError(f"unknown concept {word!r} (normalized {name!r}); not in the curated KB")
    return ConceptNode(name=concept.name, affordances=concept.affordances)


def expand(node: ConceptNode | str, depth: int = 2) -> SemanticGraph:
    """Expand: a bounded, deterministic BFS over the KB from ``node`` out to ``depth`` hops.

    Returns the reachable sub-graph as a :class:`SemanticGraph` with sorted, deduplicated
    ``concepts`` and ``edges``. ``depth`` bounds the number of relation hops from the root
    (``depth=0`` is the root alone). Raises :class:`ValueError` for a negative depth."""
    if depth < 0:
        raise ValueError(f"expand depth must be non-negative, got {depth}")
    root = node.name if isinstance(node, ConceptNode) else normalize(node)
    if root not in KB:
        raise KeyError(f"unknown root concept {root!r}; not in the curated KB")

    seen: set[str] = {root}
    edges: set[tuple[str, Relation, str]] = set()
    frontier: deque[tuple[str, int]] = deque([(root, 0)])
    while frontier:
        name, dist = frontier.popleft()
        if dist >= depth:
            continue
        concept = KB[name]
        # Sorted iteration keeps the traversal (and thus the result) byte-reproducible.
        for relation in sorted(concept.relations, key=lambda r: r.value):
            for target in sorted(concept.relations[relation]):
                edges.add((name, relation, target))
                if target not in seen:
                    seen.add(target)
                    frontier.append((target, dist + 1))

    return SemanticGraph(
        root=root,
        concepts=tuple(sorted(seen)),
        edges=tuple(sorted(edges, key=lambda e: (e[0], e[1].value, e[2]))),
    )


__all__ = [
    "Relation",
    "Affordance",
    "Concept",
    "ConceptNode",
    "SemanticGraph",
    "KB",
    "CURATED_WORDS",
    "normalize",
    "sense",
    "expand",
]
