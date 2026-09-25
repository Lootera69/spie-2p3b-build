"""Phase 4.3 — Operationalize: compile a mechanic-level :class:`~spie.afford.RuleGraph` into an
executable :class:`~spie.ir.Puzzle` in the existing DSL.

This is the third pipeline stage (Sense → Expand → Afford → Blend → **Operationalize** → Ablate).
:func:`operationalize` turns the backend-agnostic rule graph into real ``ir`` values — nodes,
edges, variables, actions, objective — and nothing more: the emitted puzzle has *no privileged
path*, it flows through the same :mod:`spie.validate` / :mod:`spie.verify` / :mod:`spie.certificate`
gates every hand-authored puzzle does.

Design — a *forced-linear* skeleton, decorated by *forced-insertion* gadgets:

* The **base** is a single forced line of length ``L`` — either a
  :attr:`~spie.afford.MechanicKind.CHAIN` (an INT ``progress`` variable stepped ``0 → L``) or a
  :attr:`~spie.afford.MechanicKind.CONNECT` movement over a line graph ``loc_00 → … → loc_L``
  (a ``pos`` LOC variable). A bare line has a unique shortest solution and every step/edge is
  load-bearing.
* Each **modifier** is compiled at its own *distinct* checkpoint into a small gadget: some state,
  one or two forced auxiliary actions, and a ``pass`` predicate that gates the forward transition.
  Because from a checkpoint the only enabled action is the gadget's aux action(s) — and the step
  only unlocks once they have run — the line stays a single forced path (still **unique** and
  **minimal**) with the mechanic genuinely layered in. Distinct checkpoints keep any two gadgets
  from ever being simultaneously enabled, which is what would break uniqueness.

Determinism: the puzzle is a pure, canonical function of ``(rule_graph, seed)`` — fixed variable
order, zero-padded names, actions sorted by name — so the same rule graph always serializes to
byte-identical JSON. The epistemic/temporal modifiers (``REVEAL`` / ``DELAY``) need the
belief-space cross-check to certify and are deferred behind :data:`SUPPORTED_MODIFIERS`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .afford import MechanicKind, RuleGraph
from .expr import Const, Edge, Eq, Expr, Le, Node, Not, PVal, Sub, Var, all_of, any_of
from .ir import Action, Assign, Kind, Objective, Param, Puzzle, Variable

# Element-level provenance: each source concept -> the action names it produced in the compiled
# puzzle. This is the thread stage 4.6 (concept-relevance) follows to ablate a concept and prove
# it is load-bearing. Built alongside the puzzle so it can never drift from the emitted names.
Provenance = dict[str, tuple[str, ...]]


def _freeze_provenance(prov: dict[str, list[str]]) -> Provenance:
    """Canonicalize a concept -> action-name map: names sorted and de-duplicated per concept so
    the provenance is a deterministic function of the rule graph."""
    return {concept: tuple(sorted(set(names))) for concept, names in prov.items()}

# The modifier kinds this stage compiles into fully-observable, certifiable gadgets. REVEAL and
# DELAY are epistemic/temporal (HIDDEN/DELAYED observability); certifying them requires the
# belief-space A≡B cross-check, so they are refused here rather than emitted unproven.
SUPPORTED_MODIFIERS: frozenset[MechanicKind] = frozenset(
    {
        MechanicKind.CONSUME,
        MechanicKind.NEGATE,
        MechanicKind.PRESERVE,
        MechanicKind.PROPAGATE,
    }
)

# Slack added over the exact minimal solution length so the Z3 bounded-model-checker has room to
# find (and prove minimal) the forced path; kept fixed so certificates stay byte-reproducible.
_AUX_HORIZON_SLACK = 2

@dataclass(frozen=True)
class _Gadget:
    """The compiled pieces of one modifier at one checkpoint.

    * ``variables`` / ``initial`` — the state the gadget introduces.
    * ``aux_actions`` — the forced auxiliary action(s) that must run at the checkpoint.
    * ``pass_condition`` — the predicate the forward transition (a chain step / a graph edge)
      must satisfy to advance; it holds only *after* the aux actions have run."""

    variables: tuple[Variable, ...]
    initial: dict[str, int]
    aux_actions: tuple[Action, ...]
    pass_condition: Expr


def _gadget(kind: MechanicKind, checkpoint: int, at: Expr) -> _Gadget:
    """Build the gadget for ``kind`` at ``checkpoint``, gated on being ``at`` the checkpoint
    (``progress == c`` for a chain, ``pos == n_c`` for a graph).

    Every gadget is a *forced insertion*: from the checkpoint the only enabled action is the
    gadget's aux action(s); only once they have run does ``pass_condition`` hold and the forward
    transition unlock. So the skeleton stays a single forced line — unique and minimal — with the
    mechanic layered in. Each aux action also self-disables once run, so it never idles."""
    s = f"{checkpoint:02d}"
    if kind is MechanicKind.CONSUME:
        # A resource that must be spent (1 → 0) before the step; the step requires it depleted.
        v = f"res_{s}"
        return _Gadget(
            (Variable(v, Kind.INT, 0, 1),),
            {v: 1},
            (Action(f"spend_{s}", all_of(at, Le(Const(1), Var(v))),
                    (Assign(v, Sub(Var(v), Const(1))),)),),
            Eq(Var(v), Const(0)),
        )
    if kind is MechanicKind.NEGATE:
        # A guard/gate opened by a forced action; the step requires it open.
        v = f"gate_{s}"
        return _Gadget(
            (Variable(v, Kind.BOOL),),
            {v: 0},
            (Action(f"open_{s}", all_of(at, Eq(Var(v), Const(0))), (Assign(v, Const(1)),)),),
            Eq(Var(v), Const(1)),
        )
    if kind is MechanicKind.PRESERVE:
        # Persistent state latched by a forced action; identical shape to NEGATE but the variable
        # survives a Reset (introduced by later temporal operators), so it is marked persistent.
        v = f"kept_{s}"
        return _Gadget(
            (Variable(v, Kind.BOOL, persistent=True),),
            {v: 0},
            (Action(f"store_{s}", all_of(at, Eq(Var(v), Const(0))), (Assign(v, Const(1)),)),),
            Eq(Var(v), Const(1)),
        )
    if kind is MechanicKind.PROPAGATE:
        # A coupled transfer src → dst: emit sets src, flow carries it to dst; the step needs dst.
        a, b = f"src_{s}", f"dst_{s}"
        return _Gadget(
            (Variable(a, Kind.BOOL), Variable(b, Kind.BOOL)),
            {a: 0, b: 0},
            (
                Action(f"emit_{s}", all_of(at, Eq(Var(a), Const(0))), (Assign(a, Const(1)),)),
                Action(f"flow_{s}", all_of(at, Eq(Var(a), Const(1)), Eq(Var(b), Const(0))),
                       (Assign(b, Const(1)),)),
            ),
            Eq(Var(b), Const(1)),
        )
    raise NotImplementedError(f"operationalize cannot compile modifier {kind}")


def _effective_length(rule_graph: RuleGraph) -> int:
    """The forced-line length: at least the requested length, and enough distinct checkpoints to
    host every modifier one-per-checkpoint (distinctness is what preserves uniqueness)."""
    return max(rule_graph.length, len(rule_graph.modifiers))


def _finish(rule_graph: RuleGraph, seed: int, meta: tuple[str, str, str],
            nodes: tuple[str, ...], edges: tuple[tuple[str, str], ...],
            variables: tuple[Variable, ...], initial: dict[str, object],
            actions: list[Action], goal: Expr, horizon: int) -> Puzzle:
    """Assemble the canonical Puzzle: actions sorted by name so serialization is byte-stable."""
    return Puzzle(
        id=meta[0],
        title=meta[1],
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial=initial,
        actions=tuple(sorted(actions, key=lambda a: a.name)),
        objective=Objective(goal=goal, max_horizon=horizon),
        seed=seed,
        notes=meta[2],
    )


def _chain_puzzle(rule_graph: RuleGraph, seed: int,
                  meta: tuple[str, str, str]) -> tuple[Puzzle, Provenance]:
    """CHAIN base: an INT ``progress`` stepped ``0 → L``. Checkpoint ``t`` is the step leaving
    ``progress == t``; the first ``len(modifiers)`` steps are gadget-gated, the rest are bare.

    Returns the puzzle plus element-level :data:`Provenance`: every ``step_*`` action is credited
    to the CHAIN base concept, and each gadget's aux action(s) to the concept that afforded that
    modifier — so a concept's contribution can later be ablated by name."""
    length = _effective_length(rule_graph)
    mods = rule_graph.modifiers
    variables: list[Variable] = [Variable("progress", Kind.INT, 0, length)]
    initial: dict[str, object] = {"progress": 0}
    actions: list[Action] = []
    prov: dict[str, list[str]] = {}
    base_concept = rule_graph.provenance[MechanicKind.CHAIN]
    aux_total = 0
    for t in range(length):
        at = Eq(Var("progress"), Const(t))
        if t < len(mods):
            g = _gadget(mods[t], t, at)
            variables.extend(g.variables)
            initial.update(g.initial)
            actions.extend(g.aux_actions)
            aux_total += len(g.aux_actions)
            prov.setdefault(rule_graph.provenance[mods[t]], []).extend(
                a.name for a in g.aux_actions)
            pre: Expr = all_of(at, g.pass_condition)
        else:
            pre = at
        step = Action(f"step_{t:02d}", pre, (Assign("progress", Const(t + 1)),))
        actions.append(step)
        prov.setdefault(base_concept, []).append(step.name)
    goal = Eq(Var("progress"), Const(length))
    horizon = length + aux_total + _AUX_HORIZON_SLACK
    puzzle = _finish(rule_graph, seed, meta, ("hub",), (), tuple(variables), initial,
                     actions, goal, horizon)
    return puzzle, _freeze_provenance(prov)


def _connect_puzzle(rule_graph: RuleGraph, seed: int,
                    meta: tuple[str, str, str]) -> tuple[Puzzle, Provenance]:
    """CONNECT base: movement over a line graph ``loc_00 → … → loc_L`` via a single Edge-guarded
    ``move``. Checkpoint ``t`` is the edge ``loc_t → loc_{t+1}``; a gadget there adds a conjunct
    to ``move`` (moving *into* ``loc_{t+1}`` requires the gadget's pass condition) plus its aux.

    Returns the puzzle plus element-level :data:`Provenance`: the ``move`` action is credited to
    the CONNECT base concept and each gadget's aux action(s) to the concept that afforded that
    modifier."""
    length = _effective_length(rule_graph)
    mods = rule_graph.modifiers
    nodes = tuple(f"loc_{i:02d}" for i in range(length + 1))
    edges = tuple((nodes[i], nodes[i + 1]) for i in range(length))
    variables: list[Variable] = [Variable("pos", Kind.LOC)]
    initial: dict[str, object] = {"pos": nodes[0]}
    aux_actions: list[Action] = []
    prov: dict[str, list[str]] = {}
    guard: list[Expr] = [Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))]
    aux_total = 0
    for t in range(len(mods)):
        g = _gadget(mods[t], t, Eq(Var("pos"), Node(nodes[t])))
        variables.extend(g.variables)
        initial.update(g.initial)
        aux_actions.extend(g.aux_actions)
        aux_total += len(g.aux_actions)
        prov.setdefault(rule_graph.provenance[mods[t]], []).extend(a.name for a in g.aux_actions)
        # Only the move that enters loc_{t+1} is gated; every other move is unaffected.
        guard.append(any_of(Not(Eq(PVal("dst"), Node(nodes[t + 1]))), g.pass_condition))
    move = Action("move",
                  precondition=all_of(*guard),
                  effects=(Assign("pos", PVal("dst")),),
                  params=(Param("src", True, nodes), Param("dst", True, nodes)))
    prov.setdefault(rule_graph.provenance[MechanicKind.CONNECT], []).append(move.name)
    goal = Eq(Var("pos"), Node(nodes[length]))
    horizon = length + aux_total + _AUX_HORIZON_SLACK
    puzzle = _finish(rule_graph, seed, meta, nodes, edges, tuple(variables), initial,
                     [move, *aux_actions], goal, horizon)
    return puzzle, _freeze_provenance(prov)


def _notes(rule_graph: RuleGraph) -> str:
    """A deterministic provenance note: every mechanic present → the concept it came from."""
    prov = ", ".join(f"{k.value}<-{rule_graph.provenance[k]}" for k in rule_graph.mechanics)
    mods = ", ".join(m.value for m in rule_graph.modifiers) or "none"
    return (f"Operationalized rule graph: base {rule_graph.base.value}, modifiers [{mods}]. "
            f"Provenance: {prov}.")


def _operationalize(rule_graph: RuleGraph, seed: int) -> tuple[Puzzle, Provenance]:
    """Shared core: validate the rule graph, refuse unsupported modifiers, and dispatch to the
    CHAIN/CONNECT builder. Returns the puzzle *and* its element-level provenance so the two can
    never drift; the public wrappers expose one or both."""
    rule_graph.check()
    unsupported = [m for m in rule_graph.modifiers if m not in SUPPORTED_MODIFIERS]
    if unsupported:
        names = ", ".join(m.value for m in unsupported)
        raise NotImplementedError(
            f"operationalize does not yet compile modifier(s): {names} "
            "(epistemic/temporal mechanics are deferred to a later sub-step)"
        )
    mod_tag = "_".join(m.value for m in rule_graph.modifiers) or "plain"
    meta = (
        f"gen_{seed:04d}_{rule_graph.base.value}_{mod_tag}",
        f"Generated {rule_graph.base.value} puzzle ({mod_tag})",
        _notes(rule_graph),
    )
    if rule_graph.base is MechanicKind.CONNECT:
        return _connect_puzzle(rule_graph, seed, meta)
    return _chain_puzzle(rule_graph, seed, meta)


def operationalize(rule_graph: RuleGraph, seed: int = 0) -> Puzzle:
    """Compile a well-formed :class:`~spie.afford.RuleGraph` into an executable :class:`Puzzle`.

    The result is a pure, canonical function of ``(rule_graph, seed)``: it validates clean and
    certifies solvable + unique with no special casing. Modifiers outside
    :data:`SUPPORTED_MODIFIERS` (``REVEAL`` / ``DELAY``) raise :class:`NotImplementedError` rather
    than being emitted without an epistemic proof."""
    return _operationalize(rule_graph, seed)[0]


def operationalize_traced(rule_graph: RuleGraph, seed: int = 0) -> tuple[Puzzle, Provenance]:
    """Like :func:`operationalize`, but also return the element-level :data:`Provenance` mapping
    each source concept to the action names it produced. Stage 4.6 (concept-relevance) ablates a
    concept by these names to prove it is load-bearing; the map is byte-canonical (sorted,
    de-duplicated) so it is a deterministic function of ``(rule_graph, seed)`` like the puzzle."""
    return _operationalize(rule_graph, seed)


__all__ = ["SUPPORTED_MODIFIERS", "Provenance", "operationalize", "operationalize_traced"]


