"""Static puzzle validation — cheap structural checks that run without a solver.

The output shape deliberately echoes the BrainBloom Forge verifier we drew patterns from:
a flat list of ``Finding(rule, message)`` records. These catch authoring mistakes (a
variable with no initial value, an effect targeting an undeclared key, an edge to a missing
node) *before* the expensive Z3 solve, and feed the score in :mod:`spie.report`.

Validation never executes the puzzle; it only inspects the declared structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from . import expr as E
from .ground import ground_all
from .interpreter import domain_of
from .ir import Kind, Observability, Puzzle


@dataclass(frozen=True)
class Finding:
    """One validation issue: a stable ``rule`` slug and a human-readable ``message``."""

    rule: str
    message: str


def _collect(node: E.Expr, vars_out: set[str], nodes_out: set[str]) -> None:
    """Walk an expression, recording every ``Var`` key and ``Node`` name it references."""
    match node:
        case E.Var(key):
            vars_out.add(key)
        case E.Node(name):
            nodes_out.add(name)
        case E.Not(operand):
            _collect(operand, vars_out, nodes_out)
        case E.And(operands) | E.Or(operands):
            for o in operands:
                _collect(o, vars_out, nodes_out)
        case E.Add(a, b) | E.Sub(a, b) | E.Eq(a, b) | E.Lt(a, b) | E.Le(a, b) | E.Edge(a, b):
            _collect(a, vars_out, nodes_out)
            _collect(b, vars_out, nodes_out)
        case E.Ite(c, t, e):
            _collect(c, vars_out, nodes_out)
            _collect(t, vars_out, nodes_out)
            _collect(e, vars_out, nodes_out)
        case _:
            pass  # Const / PVal reference nothing to validate here


def validate(puzzle: Puzzle) -> list[Finding]:
    """Return every structural issue found in ``puzzle``, in a deterministic order."""
    findings: list[Finding] = []
    node_set = set(puzzle.nodes)
    var_keys = {v.key for v in puzzle.variables}

    # Nodes and edges.
    if len(node_set) != len(puzzle.nodes):
        findings.append(Finding("duplicate-node", "node list contains duplicate names"))
    for a, b in puzzle.edges:
        for endpoint in (a, b):
            if endpoint not in node_set:
                findings.append(
                    Finding("unknown-edge-endpoint", f"edge references unknown node {endpoint!r}")
                )

    # Horizon.
    if puzzle.objective.max_horizon < 1:
        findings.append(
            Finding("nonpositive-horizon", "objective.max_horizon must be at least 1")
        )

    # Variables: initial values present, INT bounds declared, initial within domain.
    for var in puzzle.variables:
        if var.key not in puzzle.initial:
            findings.append(
                Finding("missing-initial", f"variable {var.key!r} has no initial value")
            )
            continue
        if var.kind is Kind.INT and (var.lo is None or var.hi is None):
            findings.append(
                Finding("missing-int-bounds", f"INT variable {var.key!r} must declare lo and hi")
            )
            continue
        raw = puzzle.initial[var.key]
        if var.kind is Kind.LOC and isinstance(raw, str):
            idx = puzzle.node_index()
            if raw not in idx:
                findings.append(
                    Finding("initial-out-of-range", f"initial {var.key}={raw!r} is not a node")
                )
                continue
            value = idx[raw]
        else:
            value = int(raw)
        lo, hi = domain_of(puzzle, var.key)
        if not (lo <= value <= hi):
            findings.append(
                Finding("initial-out-of-range", f"initial {var.key}={raw!r} outside [{lo},{hi}]")
            )

    # Expression references: gather from goal, invariants, loss, and every ground action.
    used_vars: set[str] = set()
    used_nodes: set[str] = set()
    _collect(puzzle.objective.goal, used_vars, used_nodes)
    for inv in puzzle.objective.invariants:
        _collect(inv, used_vars, used_nodes)
    if puzzle.objective.loss is not None:
        _collect(puzzle.objective.loss, used_vars, used_nodes)
    for ga in ground_all(puzzle):
        _collect(ga.precondition, used_vars, used_nodes)
        for eff in ga.effects:
            _collect(eff.value, used_vars, used_nodes)
            if eff.key not in var_keys:
                findings.append(
                    Finding(
                        "unknown-effect-target",
                        f"effect writes undeclared variable {eff.key!r}",
                    )
                )
    for key in sorted(used_vars - var_keys):
        findings.append(
            Finding("unbound-var", f"expression references undeclared variable {key!r}")
        )
    for name in sorted(used_nodes - node_set):
        findings.append(
            Finding("unknown-node-ref", f"expression references unknown node {name!r}")
        )

    # Node-typed action parameters must name real nodes.
    for action in puzzle.actions:
        for param in action.params:
            if param.is_node:
                for pv in param.values:
                    if pv not in node_set:
                        findings.append(
                            Finding(
                                "unknown-param-node",
                                f"param {param.name!r} lists unknown node {pv!r}",
                            )
                        )

    # Phase-3 information model: observability, hidden-variable belief support, sensing.
    _validate_information(puzzle, var_keys, findings)
    return findings


def _validate_information(puzzle: Puzzle, var_keys: set[str], findings: list[Finding]) -> None:
    """Checks for the Phase-3 fields — only ever fire when a puzzle actually uses them,
    so fully-observable slice-1/2 puzzles stay clean."""
    belief = puzzle.initial_belief
    by_key = puzzle.variables_by_key()
    idx = puzzle.node_index()

    for var in puzzle.variables:  # variable order is deterministic
        if var.obs is Observability.HIDDEN and not belief.get(var.key):
            findings.append(
                Finding(
                    "hidden-without-belief",
                    f"HIDDEN variable {var.key!r} declares no initial_belief support",
                )
            )
        if var.delay < 0:
            findings.append(
                Finding("negative-delay", f"variable {var.key!r} has negative delay {var.delay}")
            )
        if var.obs is Observability.DELAYED and var.delay < 1:
            findings.append(
                Finding(
                    "delayed-without-delay",
                    f"DELAYED variable {var.key!r} needs delay >= 1 (has {var.delay})",
                )
            )

    for key in sorted(belief):
        support = belief[key]
        if key not in var_keys:
            findings.append(
                Finding("belief-unknown-var", f"initial_belief names undeclared variable {key!r}")
            )
            continue
        var = by_key[key]
        if var.obs is Observability.VISIBLE:
            findings.append(
                Finding("belief-not-hidden", f"initial_belief given for visible variable {key!r}")
            )
        if not support:
            findings.append(Finding("empty-belief-support", f"initial_belief for {key!r} is empty"))
            continue
        lo, hi = domain_of(puzzle, key)
        for val in support:
            if not (lo <= val <= hi):
                findings.append(
                    Finding("belief-out-of-range", f"belief value {key}={val} outside [{lo},{hi}]")
                )
        if key in puzzle.initial:  # the concrete world must be one the player can't rule out
            raw = puzzle.initial[key]
            actual = idx[raw] if (var.kind is Kind.LOC and isinstance(raw, str)) else int(raw)
            if actual not in support:
                findings.append(
                    Finding(
                        "belief-initial-not-in-support",
                        f"initial {key}={raw!r} is not in its belief support",
                    )
                )

    for action in puzzle.actions:
        for key in action.senses:
            if key not in var_keys:
                findings.append(
                    Finding(
                        "senses-unknown-var",
                        f"action {action.name!r} senses undeclared variable {key!r}",
                    )
                )

    _validate_distribution(puzzle, belief, findings)


def _validate_distribution(
    puzzle: Puzzle, belief: dict[str, tuple[int, ...]], findings: list[Finding]
) -> None:
    """Item-4 chance layer: check ``initial_dist`` only when it is non-empty, so every
    deterministic and every existing epistemic puzzle stays byte-identical and clean.

    A distribution is a per-hidden-variable set of exact-``Fraction`` weights over *exactly*
    that variable's ``initial_belief`` support: every support value carries one weight, weights
    are non-negative, and they sum to exactly ``Fraction(1)``."""
    if not puzzle.initial_dist:
        return
    for key in sorted(puzzle.initial_dist):
        pairs = puzzle.initial_dist[key]
        support = belief.get(key)
        if not support:
            findings.append(
                Finding(
                    "dist-without-belief",
                    f"initial_dist for {key!r} has no matching initial_belief support",
                )
            )
            continue
        dist_values = [value for value, _ in pairs]
        if len(dist_values) != len(set(dist_values)) or set(dist_values) != set(support):
            findings.append(
                Finding(
                    "dist-support-mismatch",
                    f"initial_dist for {key!r} does not weight its belief support exactly",
                )
            )
        for value, weight in pairs:
            if weight < 0:
                findings.append(
                    Finding(
                        "dist-negative-weight",
                        f"initial_dist {key}={value} has negative weight {weight}",
                    )
                )
        total = sum((weight for _, weight in pairs), Fraction(0))
        if total != Fraction(1):
            findings.append(
                Finding(
                    "dist-not-normalized",
                    f"initial_dist for {key!r} weights sum to {total}, not 1",
                )
            )


__all__ = ["Finding", "validate"]
