"""Phase 5.3 — PRESENTATION: a deterministic, pure, ASCII-only renderer.

Turns a proven :class:`~spie.ir.Puzzle` and its :class:`~spie.ir.Certificate` into human-readable
text (``list[str]``), honoring the roadmap's **non-negotiable invariant: the renderer contains no
gameplay logic absent from the formal representation**. Everything shown is a strict function of
the formal rep or the proof:

* **Rules** are mechanically derived from the IR — locations, connections, variables, each
  action's precondition/effects/senses/cost, and the objective. The only free text is the
  author-supplied :attr:`~spie.ir.Puzzle.title`/:attr:`~spie.ir.Puzzle.notes`.
* **Hints** are a progressive reveal derived from the proof (the goal, the proven distance/depth,
  then the exact next action of the certified solution) — every hinted action is one the proof
  already prescribes.
* **The answer / replay** is **re-derived** from the puzzle via
  :func:`spie.search.canonical_solution` (fully observable) or
  :func:`spie.conformance.check_plan_conformance` (hidden) — never by expanding the certificate,
  so the 20 corpus certificates stay byte-identical.
* **The machine-readable certificate** is the existing :func:`spie.serialize.certificate_to_json`.

The renderer is a pure new *consumer*: it imports no writer of the corpus and mutates nothing, so
it cannot perturb any certificate. Output is strictly ASCII (Windows cp1252-safe).
"""

from __future__ import annotations

from . import augment, search
from .conformance import check_plan_conformance
from .expr import (
    Add,
    And,
    Const,
    Edge,
    Eq,
    Expr,
    Ite,
    Le,
    Lt,
    Node,
    Not,
    Or,
    PVal,
    Reset,
    Sub,
    Var,
)
from .ir import Certificate, Kind, Observability, Puzzle
from .results import Plan
from .serialize import certificate_to_json, dumps

# --- Expression / effect / state rendering (pure functions of the formal rep) ---------------


def _render_expr(node: Expr) -> str:
    """Render one expression node as readable ASCII infix/prefix text. Every node type the DSL
    defines is handled (incl. the ``PVal`` parameter placeholder that appears in lifted action
    templates); an unknown node is a hard error, never silently dropped."""
    match node:
        case Const(value):
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)
        case Var(key):
            return key
        case Node(name):
            return f"@{name}"
        case PVal(name):
            return f"?{name}"
        case Not(operand):
            return f"not {_render_expr(operand)}"
        case And(operands):
            return "(" + " and ".join(_render_expr(o) for o in operands) + ")"
        case Or(operands):
            return "(" + " or ".join(_render_expr(o) for o in operands) + ")"
        case Add(left, right):
            return f"({_render_expr(left)} + {_render_expr(right)})"
        case Sub(left, right):
            return f"({_render_expr(left)} - {_render_expr(right)})"
        case Eq(left, right):
            return f"({_render_expr(left)} == {_render_expr(right)})"
        case Lt(left, right):
            return f"({_render_expr(left)} < {_render_expr(right)})"
        case Le(left, right):
            return f"({_render_expr(left)} <= {_render_expr(right)})"
        case Edge(src, dst):
            return f"edge({_render_expr(src)} -> {_render_expr(dst)})"
        case Ite(cond, then, otherwise):
            return (
                f"(if {_render_expr(cond)} then {_render_expr(then)} "
                f"else {_render_expr(otherwise)})"
            )
        case _:  # pragma: no cover - defensive; the DSL defines no other node
            raise TypeError(f"cannot render expression node {type(node).__name__}")


def _render_effect(effect: object) -> str:
    """An action effect: a ``Reset`` marker, or an ``Assign`` shown as ``key := value``."""
    if isinstance(effect, Reset):
        return "reset non-persistent state"
    return f"{effect.key} := {_render_expr(effect.value)}"  # type: ignore[attr-defined]


def _initial_display(puzzle: Puzzle, key: str, kind: Kind) -> str:
    """The declared start value of a variable, decoded to a readable form (a LOC as its node
    name, a BOOL as true/false), read straight from :attr:`~spie.ir.Puzzle.initial`."""
    if key not in puzzle.initial:
        return "?"
    raw = puzzle.initial[key]
    if kind is Kind.BOOL:
        return "true" if raw else "false"
    if kind is Kind.LOC:
        if isinstance(raw, str):
            return f"@{raw}"
        return f"@{puzzle.nodes[int(raw)]}"
    return str(raw)


def _format_state(puzzle: Puzzle, values: tuple[int, ...]) -> str:
    """Render a concrete state tuple (ints in declared variable order) back to named values."""
    parts = []
    for v, val in zip(puzzle.variables, values, strict=True):
        if v.kind is Kind.LOC and isinstance(val, int) and 0 <= val < len(puzzle.nodes):
            parts.append(f"{v.key}=@{puzzle.nodes[val]}")
        elif v.kind is Kind.BOOL:
            parts.append(f"{v.key}={'true' if val else 'false'}")
        else:
            parts.append(f"{v.key}={val}")
    return "{" + ", ".join(parts) + "}"


def _var_flags(v: object) -> list[str]:
    """The non-default information-model tags on a variable (observability, delay, persistence),
    shown so the player sees exactly the declared dynamics and nothing more."""
    flags: list[str] = []
    if v.obs is not Observability.VISIBLE:  # type: ignore[attr-defined]
        flags.append(v.obs.value)  # type: ignore[attr-defined]
    if v.delay:  # type: ignore[attr-defined]
        flags.append(f"delay {v.delay}")  # type: ignore[attr-defined]
    if v.persistent:  # type: ignore[attr-defined]
        flags.append("persistent")
    return flags


# --- Rules: the playable rules, mechanically derived from the IR ----------------------------


def rules_lines(puzzle: Puzzle) -> list[str]:
    """The playable rules, a strict function of the formal rep: the map (locations + one-way
    connections), the state variables with their declared starts and info-model flags, any initial
    uncertainty, each action's precondition/effects/senses/cost, and the objective. The only
    author-supplied free text is the title and notes; every mechanic shown is read from the IR."""
    out: list[str] = [f"Puzzle: {puzzle.id} - {puzzle.title}"]
    if puzzle.notes:
        out.append("Notes:")
        out.extend(f"  {line}" for line in puzzle.notes.splitlines())
    out.append("Locations:")
    if puzzle.nodes:
        out.extend(f"  {name}" for name in puzzle.nodes)
    else:
        out.append("  (none)")
    if puzzle.edges:
        out.append("Connections:")
        out.extend(f"  {a} -> {b}" for a, b in puzzle.edges)
    out.append("State variables:")
    for v in puzzle.variables:
        line = f"  {v.key}: {v.kind.value}, start {_initial_display(puzzle, v.key, v.kind)}"
        flags = _var_flags(v)
        if flags:
            line += ", " + ", ".join(flags)
        out.append(line)
    if puzzle.initial_belief:
        out.append("Initial belief (unknown at start):")
        for key in sorted(puzzle.initial_belief):
            vals = ", ".join(str(x) for x in puzzle.initial_belief[key])
            out.append(f"  {key} in {{{vals}}}")
    out.append("Actions:")
    for a in puzzle.actions:
        out.append(f"  {a.name}:")
        for p in a.params:
            kind = "node" if p.is_node else "int"
            out.append(f"    param {p.name} ({kind}): {', '.join(str(x) for x in p.values)}")
        out.append(f"    when {_render_expr(a.precondition)}")
        if a.effects:
            out.extend(f"    effect {_render_effect(e)}" for e in a.effects)
        else:
            out.append("    effect (none)")
        if a.senses:
            out.append(f"    senses {', '.join(a.senses)}")
        out.append(f"    cost {a.cost}")
    out.append("Objective:")
    out.append(f"  goal {_render_expr(puzzle.objective.goal)}")
    if puzzle.objective.loss is not None:
        out.append(f"  loss {_render_expr(puzzle.objective.loss)}")
    out.extend(f"  invariant {_render_expr(inv)}" for inv in puzzle.objective.invariants)
    out.append(f"  max horizon {puzzle.objective.max_horizon}")
    out.append(f"  requires unique {str(puzzle.objective.requires_unique).lower()}")
    out.append(f"  trap policy {puzzle.objective.trap_policy}")
    return out


# --- Hints: a progressive reveal, every rung a strict function of the proof -----------------


def _collect_plan_actions(plan: Plan, acc: set[str]) -> None:
    """Accumulate every action an internal node of a contingent plan prescribes (a leaf, whose
    ``action`` is ``None``, prescribes nothing)."""
    if plan.action is not None:
        acc.add(plan.action)
    for _obs, child in plan.branches:
        _collect_plan_actions(child, acc)


def _proof_action_set(puzzle: Puzzle, cert: Certificate) -> set[str]:
    """Every action the proof itself prescribes: the internal-node actions of the certified
    contingent plan (hidden), or the canonical linear solution's ground actions (fully
    observable). The hint ladder may reveal only actions drawn from this set."""
    if cert.plan is not None:
        acc: set[str] = set()
        _collect_plan_actions(cert.plan, acc)
        return acc
    return set(search.canonical_solution(puzzle).trace)


def hint_actions(puzzle: Puzzle, cert: Certificate) -> list[str]:
    """The concrete next action(s) the ladder discloses, taken verbatim from the proof: the
    contingent plan's root action (hidden), or the first two steps of the canonical solution
    (fully observable). Always a subset of :func:`_proof_action_set`."""
    if cert.plan is not None:
        return [] if cert.plan.is_leaf else [cert.plan.action]
    return list(search.canonical_solution(puzzle).trace[:2])


def hint_ladder(puzzle: Puzzle, cert: Certificate) -> list[str]:
    """A progressive reveal derived entirely from the proof: the goal to make true, then the
    proven size of the solution (worst-case plan depth for hidden puzzles, minimal step count for
    fully observable ones), then the exact next action(s) the certified solution takes."""
    out: list[str] = ["Hints:"]
    out.append(f"  1. Aim to make true: {_render_expr(puzzle.objective.goal)}")
    if cert.plan is not None:
        out.append(f"  2. A correct plan needs at most {cert.horizon} step(s) in the worst case.")
    else:
        out.append(f"  2. The shortest solution takes exactly {cert.horizon} step(s).")
    for i, name in enumerate(hint_actions(puzzle, cert), start=3):
        out.append(f"  {i}. Next: {name}")
    return out


# --- Answer / replay: states RE-DERIVED from the puzzle, never read off the certificate ------


def _plan_lines(plan: Plan, prefix: str = "  ") -> list[str]:
    """A branching, indented rendering of a contingent plan: a leaf is ``goal reached``; an
    internal node shows its action, then one indented block per observed sensing outcome."""
    if plan.is_leaf:
        return [f"{prefix}goal reached"]
    out = [f"{prefix}{plan.action}"]
    for obs_key, child in plan.branches:
        out.append(f"{prefix}  observe ({', '.join(str(x) for x in obs_key)}):")
        out.extend(_plan_lines(child, prefix + "    "))
    return out


def answer_lines(puzzle: Puzzle, cert: Certificate) -> list[str]:
    """The worked answer, with every state RE-DERIVED from the puzzle (never read out of the
    certificate, so the corpus certificates stay byte-identical). Fully observable: the canonical
    minimal solution and the state after each step, from :func:`spie.search.canonical_solution`.
    Hidden: the certified contingent plan plus a per-world replay of it through the interpreter,
    from :func:`spie.conformance.check_plan_conformance` (worlds are in desugared variable
    order, so they are decoded against :func:`spie.augment.desugar`)."""
    if cert.plan is not None:
        out = [f"Answer (contingent plan, worst-case depth {cert.horizon}):"]
        out.extend(_plan_lines(cert.plan))
        conf = check_plan_conformance(puzzle, cert.plan)
        desugared = augment.desugar(puzzle)
        out.append(f"Per-world replay ({len(conf.world_replays)} world(s)):")
        for wr in conf.world_replays:
            trace = " -> ".join(wr.trace) if wr.trace else "(no actions)"
            status = "goal" if wr.reached_goal else "NO GOAL"
            out.append(f"  from {_format_state(desugared, wr.world)}: {trace}  [{status}]")
        return out
    solution = search.canonical_solution(puzzle)
    out = [f"Answer (canonical minimal solution, {cert.horizon} step(s)):"]
    path = solution.state_path
    if path:
        out.append(f"  start: {_format_state(puzzle, path[0])}")
        for i, name in enumerate(solution.trace):
            nxt = _format_state(puzzle, path[i + 1]) if i + 1 < len(path) else "?"
            out.append(f"  {i}: {name}  ->  {nxt}")
    return out


# --- The machine-readable proof + the full assembled presentation ---------------------------


def certificate_lines(cert: Certificate) -> list[str]:
    """The machine-readable proof, verbatim from :func:`spie.serialize.certificate_to_json` (the
    same canonical JSON the ``cert`` command emits), indented as a block."""
    out = ["Machine-readable certificate:"]
    out.extend(f"  {line}" for line in dumps(certificate_to_json(cert)).splitlines())
    return out


def render(puzzle: Puzzle, cert: Certificate) -> list[str]:
    """The full presentation: the rules, the proof-derived hint ladder, the worked answer with
    re-derived states, and the machine-readable certificate, each under an ASCII banner. A pure
    function of the puzzle and its certificate that contains no gameplay logic absent from the
    formal representation."""
    sections = (
        ("RULES", rules_lines(puzzle)),
        ("HINTS", hint_ladder(puzzle, cert)),
        ("ANSWER", answer_lines(puzzle, cert)),
        ("CERTIFICATE", certificate_lines(cert)),
    )
    out: list[str] = []
    for title, body in sections:
        if out:
            out.append("")
        out.append("=" * 60)
        out.append(title)
        out.append("=" * 60)
        out.extend(body)
    return out


__all__ = [
    "render",
    "rules_lines",
    "hint_ladder",
    "hint_actions",
    "answer_lines",
    "certificate_lines",
]
