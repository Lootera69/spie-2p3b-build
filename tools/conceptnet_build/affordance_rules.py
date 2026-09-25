"""Deterministic derivation of the puzzle affordances ConceptNet does not carry.

ConceptNet supplies typed *relations* but no notion of a puzzle mechanic, so the affordance tags
the curated core authors by hand (``connect`` / ``consume`` / ``negate`` / ``preserve`` /
``propagate``) must be *derived* for a candidate word. The derivation is a fixed rule table plus
IsA inheritance — no model, no learning, no heuristic randomness — so it is reproducible and
LLM-free like everything else in the pipeline.

The rules, applied in this order:

1. **Rule table.**
   (a) *term-level* — the candidate's own name appears in an affordance lexicon
       (``flow`` -> ``propagate``);
   (b) *edge-level* — the candidate has an out-edge whose **target** appears in an affordance
       lexicon, under a relation that transfers meaning to the subject
       (``x IsA barrier`` / ``x UsedFor travel`` / ``x CapableOf spread`` /
       ``x HasProperty blocking`` / ``x Causes heat``). ``PartOf`` is deliberately excluded:
       being part of a path does not make a thing a path;
   (c) *relation-level* — any ``Causes`` edge implies ``propagate`` (a cause transfers influence),
       which is the one rule that needs no lexicon hit.
2. **IsA inheritance** — breadth-first up the candidate's ``IsA`` out-edges, inheriting each
   ancestor's affordances: a curated ancestor's *authored* tags, a candidate ancestor's *rule
   table* tags. Drawing only on rule-table results (never on other words' inherited results)
   keeps this a two-pass computation with no fixpoint and no ordering dependence.
3. **Union, keep compilable, sort, de-duplicate.** Inherited ``reveal`` / ``delay`` tags are
   dropped here exactly as ``spie.invent._COMPILABLE`` would drop them downstream.
4. **Fallback** ``("connect",)`` when nothing matched, so derivation is total.

**Why a wrong guess is safe.** Every word that reaches the artifact has been proven — by the
offline certify gate, not by this table — to invent a puzzle the formal solvers certify. A
mis-derived affordance therefore costs *interestingness* (in the limit, a bare forced chain),
never correctness. The solvers decide what is true; this table only proposes what to try.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping

# The affordances ``spie.operationalize`` can compile: the CONNECT base skeleton plus the
# supported modifiers. Deriving an affordance outside this set would be wasted work — ``invent``
# filters it out before blending.
COMPILABLE: frozenset[str] = frozenset({"connect", "consume", "negate", "preserve", "propagate"})

FALLBACK: tuple[str, ...] = ("connect",)

# Relations under which a lexicon hit on the *target* transfers the affordance to the subject.
_TARGET_RELATIONS: frozenset[str] = frozenset(
    {"IsA", "UsedFor", "CapableOf", "HasProperty", "Causes"}
)

# Relations that imply an affordance on their own, with no lexicon hit required.
_RELATION_RULES: dict[str, str] = {"Causes": "propagate"}

# Seed lexicons: the terms whose presence (as the candidate itself, or as an edge target) implies
# an affordance. Hand-authored, sorted, and deliberately conservative — a term earns a place only
# when the puzzle operation is the *core* of its meaning, not an incidental association.
AFFORDANCE_TERMS: dict[str, frozenset[str]] = {
    "connect": frozenset(
        """access alley approach arrive attach avenue bridge channel commute conduit connect
        corridor course crossing doorway drive driveway enter entrance entry exit ferry gateway
        go hall hallway highway hike ingress join journey ladder lane leave link move navigate
        network opening passage passageway path pathway portal ramp reach road route sail stair
        staircase stairway street thoroughfare track trail transit transport travel traverse
        trip tunnel visit walk way""".split()
    ),
    "consume": frozenset(
        """ammunition budget burn calorie cash coal consume cost currency deplete depletion diesel
        drain drink eat electricity energy exhaust expend expenditure fee finite food fuel
        gasoline grain kerosene limited meal money nutrient oil payment perishable petrol provision
        ration reserve resource scarce spend stamina stock supply use wage waste""".split()
    ),
    "negate": frozenset(
        """armour bar barricade barrier blockade blocking bolt border cage ceiling closed deny
        deter fence forbid gate guard hinder hindrance impede inhibit lid limit lock locked
        obstacle obstruct obstruction padlock prevent prohibit protect refuse restrain restrict
        seal secure security shield shut shutter stop wall""".split()
    ),
    "preserve": frozenset(
        """archive bag barrel basket bin bottle bowl box bucket cabinet can cargo carton case
        chest closet conserve contain container crate cupboard drawer freezer fridge hold jar keep
        locker maintain persist pocket pot preserve preserved purse record remember reserve
        retain safe save shelf silo stable storage store sustain tank vault vessel wallet
        warehouse""".split()
    ),
    "propagate": frozenset(
        """air broadcast cascade circulate conduct contagion current diffuse disperse emit epidemic
        escalate expand flood flow fluid gas grow heat increase infection leak liquid pour
        propagate pulse radiate ripple rise rising river seep smoke spill splash spread stream
        surge transmit vapour ventilate water wave wind""".split()
    ),
}

# Out-edges of one word, as ``(relation, target)`` pairs.
OutEdges = Mapping[str, tuple[tuple[str, str], ...]]

_INHERIT_MAX_HOPS = 3


def _lexicon_hits(term: str) -> set[str]:
    """Every affordance whose seed lexicon contains ``term`` (rule 1a / the target half of 1b)."""
    return {aff for aff, terms in AFFORDANCE_TERMS.items() if term in terms}


def rule_table_affordances(word: str, edges: tuple[tuple[str, str], ...]) -> set[str]:
    """Rules 1a-1c for one word: term-level, edge-target-level, and relation-level hits."""
    found = _lexicon_hits(word)
    for relation, target in edges:
        if relation in _TARGET_RELATIONS:
            found |= _lexicon_hits(target)
        implied = _RELATION_RULES.get(relation)
        if implied is not None:
            found.add(implied)
    return found


def _isa_ancestors(word: str, out_edges: OutEdges, max_hops: int) -> list[str]:
    """The word's IsA ancestors within ``max_hops``, breadth-first, in a deterministic order."""
    seen = {word}
    order: list[str] = []
    frontier: deque[tuple[str, int]] = deque([(word, 0)])
    while frontier:
        name, hops = frontier.popleft()
        if hops >= max_hops:
            continue
        for relation, target in sorted(out_edges.get(name, ())):
            if relation != "IsA" or target in seen:
                continue
            seen.add(target)
            order.append(target)
            frontier.append((target, hops + 1))
    return order


def derive(
    words: Iterable[str],
    out_edges: OutEdges,
    curated_affordances: Mapping[str, tuple[str, ...]],
    *,
    isa_hops: int = _INHERIT_MAX_HOPS,
) -> dict[str, tuple[str, ...]]:
    """Derive the affordance tuple of every candidate word.

    ``out_edges`` must already be the **pruned, closed** edge set (targets are candidates or
    curated concepts) and ``curated_affordances`` the authored tags of the curated core. The
    result is sorted and de-duplicated per word, so it is a canonical function of its inputs."""
    words = sorted(set(words))
    base = {w: rule_table_affordances(w, tuple(out_edges.get(w, ()))) for w in words}

    derived: dict[str, tuple[str, ...]] = {}
    for word in words:
        found = set(base[word])
        for ancestor in _isa_ancestors(word, out_edges, isa_hops):
            inherited = curated_affordances.get(ancestor)
            found |= set(inherited) if inherited is not None else base.get(ancestor, set())
        compilable = sorted(found & COMPILABLE)
        derived[word] = tuple(compilable) if compilable else FALLBACK
    return derived


__all__ = [
    "COMPILABLE",
    "FALLBACK",
    "AFFORDANCE_TERMS",
    "rule_table_affordances",
    "derive",
]
