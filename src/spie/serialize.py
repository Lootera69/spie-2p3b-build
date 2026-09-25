"""Canonical JSON <-> IR serialization.

JSON is the on-disk interchange format for puzzles and certificates. Serialization is
*canonical*: object keys are sorted and separators are fixed, so re-serializing an
unchanged puzzle yields byte-identical output. That determinism is what lets the
verification step assert that ``suite`` produces stable certificates.

Expressions use a compact tagged encoding — each node is a one-key object whose key is
the operator tag:

    Const(5)        -> {"c": 5}
    Var("x")        -> {"v": "x"}
    Node("A")       -> {"node": "A"}
    Edge(a, b)      -> {"edge": [<a>, <b>]}
    Not(x)          -> {"not": <x>}
    And([a, b])     -> {"and": [<a>, <b>]}
    Add(a, b)       -> {"add": [<a>, <b>]}
    Eq(a, b)        -> {"eq": [<a>, <b>]}
    Ite(c, t, e)    -> {"ite": [<c>, <t>, <e>]}
    PVal("p")       -> {"p": "p"}
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from . import expr as E
from .ir import (
    Action,
    Assign,
    Certificate,
    EpistemicEvidence,
    Kind,
    Objective,
    Observability,
    Param,
    Puzzle,
    Reset,
    SolverEvidence,
    Step,
    Variable,
    WorldReplay,
)
from .results import Plan

if TYPE_CHECKING:  # avoid a circular import at runtime; quality.py imports this module.
    from .quality import QualityVector

# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

_BINARY = {
    "add": E.Add,
    "sub": E.Sub,
    "eq": E.Eq,
    "lt": E.Lt,
    "le": E.Le,
    "edge": E.Edge,
}
_VARIADIC = {"and": E.And, "or": E.Or}


def expr_to_json(node: E.Expr) -> Any:
    match node:
        case E.Const(value):
            return {"c": value}
        case E.Var(key):
            return {"v": key}
        case E.Node(name):
            return {"node": name}
        case E.PVal(name):
            return {"p": name}
        case E.Not(operand):
            return {"not": expr_to_json(operand)}
        case E.And(operands):
            return {"and": [expr_to_json(o) for o in operands]}
        case E.Or(operands):
            return {"or": [expr_to_json(o) for o in operands]}
        case E.Add(left, right):
            return {"add": [expr_to_json(left), expr_to_json(right)]}
        case E.Sub(left, right):
            return {"sub": [expr_to_json(left), expr_to_json(right)]}
        case E.Eq(left, right):
            return {"eq": [expr_to_json(left), expr_to_json(right)]}
        case E.Lt(left, right):
            return {"lt": [expr_to_json(left), expr_to_json(right)]}
        case E.Le(left, right):
            return {"le": [expr_to_json(left), expr_to_json(right)]}
        case E.Edge(src, dst):
            return {"edge": [expr_to_json(src), expr_to_json(dst)]}
        case E.Ite(cond, then, otherwise):
            return {"ite": [expr_to_json(cond), expr_to_json(then), expr_to_json(otherwise)]}
        case _:
            raise TypeError(f"cannot serialize expression node {type(node).__name__}")


def expr_from_json(obj: Any) -> E.Expr:
    if not isinstance(obj, dict) or len(obj) != 1:
        raise ValueError(f"malformed expression json: {obj!r}")
    (tag, payload), = obj.items()
    if tag == "c":
        return E.Const(payload)
    if tag == "v":
        return E.Var(payload)
    if tag == "node":
        return E.Node(payload)
    if tag == "p":
        return E.PVal(payload)
    if tag == "not":
        return E.Not(expr_from_json(payload))
    if tag in _VARIADIC:
        return _VARIADIC[tag](tuple(expr_from_json(o) for o in payload))
    if tag in _BINARY:
        left, right = payload
        return _BINARY[tag](expr_from_json(left), expr_from_json(right))
    if tag == "ite":
        cond, then, otherwise = payload
        return E.Ite(expr_from_json(cond), expr_from_json(then), expr_from_json(otherwise))
    raise ValueError(f"unknown expression tag {tag!r}")


# ---------------------------------------------------------------------------
# Puzzle
# ---------------------------------------------------------------------------


def _assign_to_json(a: Assign) -> dict:
    return {"key": a.key, "value": expr_to_json(a.value)}


def _assign_from_json(d: dict) -> Assign:
    return Assign(d["key"], expr_from_json(d["value"]))


def _effect_to_json(e: Assign | Reset) -> dict:
    """Serialize one action effect. A :class:`~spie.ir.Reset` marker is the single-key object
    ``{"reset": true}``; an :class:`~spie.ir.Assign` keeps its ``key``/``value`` shape, so every
    reset-free action serializes byte-identically to before this primitive existed."""
    if isinstance(e, Reset):
        return {"reset": True}
    return _assign_to_json(e)


def _effect_from_json(d: dict) -> Assign | Reset:
    if "reset" in d:
        return Reset()
    return _assign_from_json(d)


def _param_to_json(p: Param) -> dict:
    return {"name": p.name, "is_node": p.is_node, "values": list(p.values)}


def _param_from_json(d: dict) -> Param:
    return Param(d["name"], d["is_node"], tuple(d["values"]))


def _action_to_json(a: Action) -> dict:
    d: dict[str, Any] = {
        "name": a.name,
        "params": [_param_to_json(p) for p in a.params],
        "precondition": expr_to_json(a.precondition),
        "effects": [_effect_to_json(e) for e in a.effects],
        "cost": a.cost,
    }
    if a.senses:  # omit when default so fully-observable actions serialize unchanged
        d["senses"] = list(a.senses)
    return d


def _action_from_json(d: dict) -> Action:
    return Action(
        name=d["name"],
        precondition=expr_from_json(d["precondition"]),
        effects=tuple(_effect_from_json(e) for e in d["effects"]),
        params=tuple(_param_from_json(p) for p in d.get("params", [])),
        cost=d.get("cost", 1),
        senses=tuple(d.get("senses", [])),
    )


def _variable_to_json(v: Variable) -> dict:
    d: dict[str, Any] = {"key": v.key, "kind": v.kind.value}
    if v.lo is not None:
        d["lo"] = v.lo
    if v.hi is not None:
        d["hi"] = v.hi
    # Phase-3 information fields — omit when default so VISIBLE variables are unchanged.
    if v.obs is not Observability.VISIBLE:
        d["obs"] = v.obs.value
    if v.delay:
        d["delay"] = v.delay
    if v.persistent:
        d["persistent"] = v.persistent
    return d


def _variable_from_json(d: dict) -> Variable:
    return Variable(
        d["key"],
        Kind(d["kind"]),
        d.get("lo"),
        d.get("hi"),
        Observability(d.get("obs", Observability.VISIBLE.value)),
        d.get("delay", 0),
        d.get("persistent", False),
    )


def _objective_to_json(o: Objective) -> dict:
    d: dict[str, Any] = {
        "goal": expr_to_json(o.goal),
        "max_horizon": o.max_horizon,
        "invariants": [expr_to_json(i) for i in o.invariants],
        "requires_unique": o.requires_unique,
        "trap_policy": o.trap_policy,
    }
    if o.loss is not None:
        d["loss"] = expr_to_json(o.loss)
    return d


def _objective_from_json(d: dict) -> Objective:
    return Objective(
        goal=expr_from_json(d["goal"]),
        max_horizon=d["max_horizon"],
        loss=expr_from_json(d["loss"]) if "loss" in d else None,
        invariants=tuple(expr_from_json(i) for i in d.get("invariants", [])),
        requires_unique=d.get("requires_unique", True),
        trap_policy=d.get("trap_policy", "allowed"),
    )


def puzzle_to_json(p: Puzzle) -> dict:
    d: dict[str, Any] = {
        "id": p.id,
        "title": p.title,
        "nodes": list(p.nodes),
        "edges": [list(e) for e in p.edges],
        "variables": [_variable_to_json(v) for v in p.variables],
        "initial": p.initial,
        "actions": [_action_to_json(a) for a in p.actions],
        "objective": _objective_to_json(p.objective),
        "seed": p.seed,
        "notes": p.notes,
    }
    if p.initial_belief:  # omit when empty so fully-observable puzzles serialize unchanged
        d["initial_belief"] = {k: list(v) for k, v in p.initial_belief.items()}
    return d


def puzzle_from_json(d: dict) -> Puzzle:
    return Puzzle(
        id=d["id"],
        title=d["title"],
        nodes=tuple(d["nodes"]),
        edges=tuple((a, b) for a, b in d["edges"]),
        variables=tuple(_variable_from_json(v) for v in d["variables"]),
        initial=dict(d["initial"]),
        actions=tuple(_action_from_json(a) for a in d["actions"]),
        objective=_objective_from_json(d["objective"]),
        seed=d.get("seed", 0),
        notes=d.get("notes", ""),
        initial_belief={k: tuple(v) for k, v in d.get("initial_belief", {}).items()},
    )


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------


def _evidence_to_json(e: SolverEvidence) -> dict:
    return {
        "name": e.name,
        "version": e.version,
        "solvable": e.solvable,
        "horizon": e.horizon,
        "cost": e.cost,
        "unique": e.unique,
    }


def _evidence_from_json(d: dict) -> SolverEvidence:
    return SolverEvidence(
        name=d["name"],
        version=d["version"],
        solvable=d["solvable"],
        horizon=d["horizon"],
        cost=d["cost"],
        unique=d["unique"],
    )


def plan_to_json(p: Plan) -> dict:
    """Serialize a contingent plan (policy tree). A leaf is ``{"action": null}``; an internal
    node adds ``branches`` — a list of ``[observed-valuation, sub-plan]`` pairs. Branches are
    already ordered by valuation in the :class:`~spie.results.Plan`, so canonical (sorted-key)
    JSON is byte-reproducible."""
    d: dict[str, Any] = {"action": p.action}
    if p.branches:
        d["branches"] = [[list(obs_key), plan_to_json(child)] for obs_key, child in p.branches]
    return d


def plan_from_json(d: dict) -> Plan:
    branches = tuple(
        (tuple(obs_key), plan_from_json(child)) for obs_key, child in d.get("branches", [])
    )
    return Plan(action=d["action"], branches=branches)


def _epistemic_evidence_to_json(e: EpistemicEvidence) -> dict:
    return {
        "name": e.name,
        "version": e.version,
        "solvable": e.solvable,
        "depth": e.depth,
        "unique": e.unique,
    }


def _epistemic_evidence_from_json(d: dict) -> EpistemicEvidence:
    return EpistemicEvidence(
        name=d["name"],
        version=d["version"],
        solvable=d["solvable"],
        depth=d["depth"],
        unique=d["unique"],
    )


def _world_replay_to_json(w: WorldReplay) -> dict:
    return {
        "world": list(w.world),
        "trace": list(w.trace),
        "reached_goal": w.reached_goal,
        "ok": w.ok,
    }


def _world_replay_from_json(d: dict) -> WorldReplay:
    return WorldReplay(
        world=tuple(d["world"]),
        trace=tuple(d["trace"]),
        reached_goal=d["reached_goal"],
        ok=d["ok"],
    )


def certificate_to_json(c: Certificate) -> dict:
    d: dict[str, Any] = {
        "puzzle_id": c.puzzle_id,
        "seed": c.seed,
        "solver": c.solver,
        "solver_version": c.solver_version,
        "horizon": c.horizon,
        "solvable": c.solvable,
        "solution": [{"tick": s.tick, "action": s.action} for s in c.solution],
        "unique": c.unique,
        "equivalence": c.equivalence,
        "conformance_ok": c.conformance_ok,
        "warnings": list(c.warnings),
        "solvers": [_evidence_to_json(e) for e in c.solvers],
    }
    # Phase-3 epistemic fields — omit when default so fully-observable certificates are unchanged.
    if c.plan is not None:
        d["plan"] = plan_to_json(c.plan)
    if c.epistemic:
        d["epistemic"] = [_epistemic_evidence_to_json(e) for e in c.epistemic]
    if c.world_replays:
        d["world_replays"] = [_world_replay_to_json(w) for w in c.world_replays]
    return d


def certificate_from_json(d: dict) -> Certificate:
    return Certificate(
        puzzle_id=d["puzzle_id"],
        seed=d["seed"],
        solver=d["solver"],
        solver_version=d["solver_version"],
        horizon=d["horizon"],
        solvable=d["solvable"],
        solution=tuple(Step(s["tick"], s["action"]) for s in d["solution"]),
        unique=d["unique"],
        equivalence=d["equivalence"],
        conformance_ok=d["conformance_ok"],
        warnings=list(d.get("warnings", [])),
        solvers=tuple(_evidence_from_json(e) for e in d.get("solvers", [])),
        plan=plan_from_json(d["plan"]) if "plan" in d else None,
        epistemic=tuple(_epistemic_evidence_from_json(e) for e in d.get("epistemic", [])),
        world_replays=tuple(_world_replay_from_json(w) for w in d.get("world_replays", [])),
    )


def quality_from_json(d: dict) -> QualityVector:
    """Inverse of :func:`spie.quality.quality_to_json` -- rebuild a ``QualityVector`` from its
    plain-data view. The quality/strategy dataclasses are imported *lazily* here: ``quality.py``
    imports this module at load time, so a module-level import would be circular. This is the
    round-trip the archive read-back (:func:`spie.mapelites.archive_from_json`) needs."""
    from .quality import Difficulty, Elegance, Fairness, Novelty, QualityVector
    from .strategy import StrategyResult, Surprise

    df, nv, el, fa = d["difficulty"], d["novelty"], d["elegance"], d["fairness"]
    st, su = d["strategy"], d["surprise"]
    return QualityVector(
        puzzle_id=d["puzzle_id"],
        solvable=d["solvable"],
        difficulty=Difficulty(
            band=df["band"],
            depth=df["depth"],
            reachable_states=df["reachable_states"],
            mean_branching=df["mean_branching"],
            max_branching=df["max_branching"],
            free_choices=df["free_choices"],
            forced_steps=df["forced_steps"],
            trap_density=df["trap_density"],
            raw=df["raw"],
            belief_count=df["belief_count"],
            sensing_actions=df["sensing_actions"],
            plan_branching=df["plan_branching"],
            depth_spread=df["depth_spread"],
            information_gain=df["information_gain"],
        ),
        novelty=Novelty(score=nv["score"], nearest_id=nv["nearest_id"]),
        elegance=Elegance(
            score=el["score"],
            rule_count=el["rule_count"],
            description_length=el["description_length"],
            minimality_ratio=el["minimality_ratio"],
        ),
        fairness=Fairness(
            score=fa["score"], uniform=fa["uniform"], partial=fa["partial"], note=fa["note"]
        ),
        strategy=StrategyResult(
            solvable=st["solvable"],
            inference_depth=st["inference_depth"],
            branching_faced=st["branching_faced"],
            backtracks=st["backtracks"],
            memory_load=st["memory_load"],
            steps_taken=st["steps_taken"],
            complete=st["complete"],
        ),
        surprise=Surprise(
            score=su["score"],
            pivot_index=su["pivot_index"],
            pivot_kind=su["pivot_kind"],
            prediction_error=su["prediction_error"],
            bits_resolved=su["bits_resolved"],
            regret_steps=su["regret_steps"],
        ),
    )


# ---------------------------------------------------------------------------
# Canonical text I/O
# ---------------------------------------------------------------------------


def dumps(obj: Any) -> str:
    """Canonical JSON text: sorted keys, compact-but-readable separators, trailing NL."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def load_puzzle(path: str) -> Puzzle:
    with open(path, encoding="utf-8") as fh:
        return puzzle_from_json(json.load(fh))


def save_puzzle(puzzle: Puzzle, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(puzzle_to_json(puzzle)))
