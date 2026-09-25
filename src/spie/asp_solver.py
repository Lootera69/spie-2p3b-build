"""The answer-set-programming backend — gate G2's independent *third* solving method.

The roadmap's gate **G2** asks for independent solving methods, each with its own solution
certificate, that must agree. Phases 1-2 shipped two — the symbolic Z3 bounded model checker
(:mod:`spie.solver`) and the concrete explicit-state search (:mod:`spie.search`). This module
adds a third paradigm, **answer-set programming** (clingo), that shares *zero* encoding code
with either: it emits a bounded-horizon planning program as ASP text and reads the answer set
back. Three methods from three paradigms (SMT, explicit search, ASP) now stand behind every
fully-observable proof.

Independence is the whole point, so nothing here reuses :func:`spie.evaluate.eval_expr` or
:func:`spie.z3_compile.compile_expr`. :class:`_Encoder` is a *fresh* structural walk over
:mod:`spie.expr` that compiles every expression node to ``ev(id, T, Value)`` rules mirroring the
evaluator's semantics rule-for-rule (booleans as 0/1, integer arithmetic, adjacency,
if-then-else). Only :func:`spie.ground.ground_all` is shared — purely structural action
grounding with no solving content, already common to the search and Z3 backends.

The encoding is the standard bounded planning one, matched tick-for-tick to
:func:`spie.z3_compile.build_unrolling` so the two *must* reach the same verdict on any puzzle:

* one ``holds(VarIdx, T, Value)`` atom per variable and tick; the initial state pinned at tick 0;
* an *exactly-one* action choice ``{ do(A,T) : act(A) } = 1`` per step (no no-ops, so the
  minimal horizon is genuinely minimal);
* a fired action's precondition must hold, its effects set the next tick's ``holds`` and every
  unwritten variable is framed (held constant);
* variable domains, per-tick invariants and the loss predicate are integrity constraints — a
  transition that would push a variable out of its declared domain is simply infeasible, exactly
  as the Z3 domain bounds make it ``unsat``;
* the goal is asserted at the final tick, and the horizon is searched upward from 0 for the
  minimal feasible length (as :func:`spie.solver.solve` does).

Uniqueness mirrors :func:`spie.solver.check_uniqueness`: block the found solution's canonical
state-path and re-solve at the same horizon — no other answer set ⇒ unique under
:data:`spie.results.EQUIVALENCE`. A ``#minimize`` selects the lexicographically-least action
trace so the reported solution (and its cost) is a canonical function of the puzzle, keeping the
certificate byte-reproducible.
"""

from __future__ import annotations

import clingo

from . import expr as E
from .ground import GroundAction, ground_all, path_cost
from .interpreter import domain_of, initial_state
from .ir import Puzzle
from .results import EQUIVALENCE, Solution, Uniqueness

SOLVER_NAME = "clingo-asp"


def solver_version() -> str:
    return getattr(clingo, "__version__", "unknown")


class _Encoder:
    """A fresh structural walk over :mod:`spie.expr` that compiles the puzzle to ASP text.

    Shares no code with :func:`spie.evaluate.eval_expr` or :func:`spie.z3_compile.compile_expr`:
    every expression node is assigned a stable integer id and compiled to ``ev(id, T, Value)``
    rules that reproduce the evaluator's semantics rule-for-rule. A fresh encoder is built per
    program (the horizon and any blocking constraint differ), so its accumulated rule list and
    node-id table never bleed between solves.
    """

    def __init__(self, puzzle: Puzzle) -> None:
        self.puzzle = puzzle
        self.ground = ground_all(puzzle)
        self.vindex = {v.key: j for j, v in enumerate(puzzle.variables)}
        self.nidx = {name: i for i, name in enumerate(puzzle.nodes)}
        self.edges = [(self.nidx[a], self.nidx[b]) for a, b in puzzle.edges]
        self._eval_rules: list[str] = []
        self._node_id: dict[E.Expr, int] = {}
        self._next = 0

    def reg(self, node: E.Expr) -> int:
        """Register an expression node, emitting its ``ev/3`` rules once, and return its id."""
        cached = self._node_id.get(node)
        if cached is not None:
            return cached
        nid = self._next
        self._next += 1
        self._node_id[node] = nid
        self._emit(nid, node)
        return nid

    def _emit(self, nid: int, node: E.Expr) -> None:
        R = self._eval_rules
        match node:
            case E.Const(value):
                R.append(f"ev({nid},T,{int(value)}) :- tick(T).")
            case E.Var(key):
                R.append(f"ev({nid},T,V) :- holds({self.vindex[key]},T,V).")
            case E.Node(name):
                R.append(f"ev({nid},T,{self.nidx[name]}) :- tick(T).")
            case E.Edge(src, dst):
                s, d = self.reg(src), self.reg(dst)
                R.append(f"ev({nid},T,1) :- ev({s},T,S), ev({d},T,D), edge(S,D).")
                R.append(f"ev({nid},T,0) :- ev({s},T,S), ev({d},T,D), not edge(S,D).")
            case E.Not(operand):
                x = self.reg(operand)
                R.append(f"ev({nid},T,1) :- ev({x},T,0).")
                R.append(f"ev({nid},T,0) :- ev({x},T,V), V!=0.")
            case E.And(operands):
                self._emit_junction(nid, operands, conjunction=True)
            case E.Or(operands):
                self._emit_junction(nid, operands, conjunction=False)
            case E.Add(left, right):
                a, b = self.reg(left), self.reg(right)
                R.append(f"ev({nid},T,S) :- ev({a},T,A), ev({b},T,B), S=A+B.")
            case E.Sub(left, right):
                a, b = self.reg(left), self.reg(right)
                R.append(f"ev({nid},T,S) :- ev({a},T,A), ev({b},T,B), S=A-B.")
            case E.Eq(left, right):
                a, b = self.reg(left), self.reg(right)
                R.append(f"ev({nid},T,1) :- ev({a},T,A), ev({b},T,B), A=B.")
                R.append(f"ev({nid},T,0) :- ev({a},T,A), ev({b},T,B), A!=B.")
            case E.Lt(left, right):
                a, b = self.reg(left), self.reg(right)
                R.append(f"ev({nid},T,1) :- ev({a},T,A), ev({b},T,B), A<B.")
                R.append(f"ev({nid},T,0) :- ev({a},T,A), ev({b},T,B), A>=B.")
            case E.Le(left, right):
                a, b = self.reg(left), self.reg(right)
                R.append(f"ev({nid},T,1) :- ev({a},T,A), ev({b},T,B), A<=B.")
                R.append(f"ev({nid},T,0) :- ev({a},T,A), ev({b},T,B), A>B.")
            case E.Ite(cond, then, otherwise):
                c, t, e = self.reg(cond), self.reg(then), self.reg(otherwise)
                R.append(f"ev({nid},T,V) :- ev({c},T,C), C!=0, ev({t},T,V).")
                R.append(f"ev({nid},T,V) :- ev({c},T,0), ev({e},T,V).")
            case _:
                raise TypeError(f"asp_solver cannot encode expression node: {type(node).__name__}")

    def _emit_junction(self, nid: int, operands, *, conjunction: bool) -> None:
        """And/Or over truthiness (``!=0``), matching :func:`evaluate.eval_expr`.

        Empty conjunction ⇒ true, empty disjunction ⇒ false (the identity elements)."""
        R = self._eval_rules
        ids = [self.reg(o) for o in operands]
        if not ids:
            R.append(f"ev({nid},T,{1 if conjunction else 0}) :- tick(T).")
            return
        if conjunction:
            for cid in ids:
                R.append(f"ev({nid},T,0) :- ev({cid},T,0).")
            lits = ", ".join(f"ev({c},T,V{k}), V{k}!=0" for k, c in enumerate(ids))
            R.append(f"ev({nid},T,1) :- {lits}.")
        else:
            for cid in ids:
                R.append(f"ev({nid},T,1) :- ev({cid},T,V), V!=0.")
            lits = ", ".join(f"ev({c},T,0)" for c in ids)
            R.append(f"ev({nid},T,0) :- {lits}.")

    def base_program(self, horizon: int) -> str:
        """The full bounded-planning ASP program at ``horizon`` (no minimize / block tail)."""
        p = self.puzzle
        nvars = len(p.variables)
        lines: list[str] = [f"tick(0..{horizon})."]
        if horizon >= 1:
            lines.append(f"step(0..{horizon - 1}).")
        if self.ground:
            lines.append(f"act(0..{len(self.ground) - 1}).")
        for a, b in self.edges:
            lines.append(f"edge({a},{b}).")
        # Declared domains and the pinned initial state.
        for v in p.variables:
            lo, hi = domain_of(p, v.key)
            lines.append(f"dom({self.vindex[v.key]},{lo},{hi}).")
        init = initial_state(p)
        for v in p.variables:
            lines.append(f"holds({self.vindex[v.key]},0,{init[v.key]}).")
        # Exactly one action fires per step (no no-ops). Omitted at horizon 0 (no steps).
        if horizon >= 1:
            lines.append("{ do(A,T) : act(A) } = 1 :- step(T).")
        # Preconditions, effects and framing, per ground action.
        for i, ga in enumerate(self.ground):
            lines.append(f"pre({i},{self.reg(ga.precondition)}).")
            written: dict[int, E.Expr] = {}
            for eff in ga.effects:
                written[self.vindex[eff.key]] = eff.value  # last-write-wins, as the interpreter
            for j, rhs in written.items():
                eid = self.reg(rhs)
                lines.append(f"holds({j},TN,V) :- do({i},T), ev({eid},T,V), TN=T+1.")
            for j in range(nvars):
                if j not in written:
                    lines.append(f"holds({j},TN,V) :- do({i},T), holds({j},T,V), TN=T+1.")
        lines.append(":- do(A,T), pre(A,P), ev(P,T,0).")
        # Domains hold at every tick; an out-of-domain successor is infeasible.
        lines.append(":- holds(J,T,V), dom(J,Lo,Hi), V<Lo.")
        lines.append(":- holds(J,T,V), dom(J,Lo,Hi), V>Hi.")
        # Invariants true and loss false at every tick.
        for inv in p.objective.invariants:
            lines.append(f":- tick(T), ev({self.reg(inv)},T,0).")
        if p.objective.loss is not None:
            lines.append(f":- tick(T), ev({self.reg(p.objective.loss)},T,V), V!=0.")
        # Goal at the final tick.
        lines.append(f":- ev({self.reg(p.objective.goal)},{horizon},0).")
        lines.extend(self._eval_rules)
        lines.append("#show do/2.")
        lines.append("#show holds/3.")
        return "\n".join(lines)


def _build_program(
    puzzle: Puzzle, horizon: int, *, minimize: bool, extra: str | None = None
) -> str:
    """A fresh program: the base encoding plus an optional lex-least minimize / block tail."""
    prog = _Encoder(puzzle).base_program(horizon)
    tail: list[str] = []
    if minimize and horizon >= 1:
        # Lexicographic by tick (tick 0 at the highest priority) ⇒ a canonical, lex-least trace.
        tail.append(f"#minimize {{ A@P,T : do(A,T), P={horizon}-T }}.")
    if extra:
        tail.append(extra)
    return prog + "\n" + "\n".join(tail) if tail else prog


def _run(program: str, *, optimize: bool) -> list[clingo.Symbol] | None:
    """Solve one program; return the (optimal, when optimizing) model's shown symbols, or None."""
    ctl = clingo.Control(
        ["--models=0"] if optimize else ["--models=1"],
        logger=lambda code, message: None,  # silence grounder info/warnings (kept deterministic)
        message_limit=0,
    )
    ctl.add("base", [], program)
    ctl.ground([("base", [])])
    captured: dict[str, list[clingo.Symbol]] = {}

    def on_model(model: clingo.Model) -> None:
        captured["syms"] = model.symbols(shown=True)  # last call = optimum under #minimize

    result = ctl.solve(on_model=on_model)
    return captured.get("syms") if result.satisfiable else None


def _extract(
    syms: list[clingo.Symbol], ground: list[GroundAction], nvars: int, horizon: int
) -> tuple[list[str], tuple[tuple[int, ...], ...]]:
    """Read the trace (ground-action names) and canonical state-path from an answer set."""
    do_at: dict[int, int] = {}
    holds_at: dict[tuple[int, int], int] = {}
    for s in syms:
        if s.name == "do":
            do_at[s.arguments[1].number] = s.arguments[0].number
        elif s.name == "holds":
            holds_at[(s.arguments[0].number, s.arguments[1].number)] = s.arguments[2].number
    trace = [ground[do_at[t]].name for t in range(horizon)]
    state_path = tuple(
        tuple(holds_at[(j, t)] for j in range(nvars)) for t in range(horizon + 1)
    )
    return trace, state_path


def solve(puzzle: Puzzle) -> Solution:
    """Minimal-horizon bounded planning via ASP: search the horizon upward from 0.

    Independent of :func:`spie.solver.solve` and :func:`spie.search.solve` — reads its verdict
    from a clingo answer set — but reports the same :class:`~spie.results.Solution` shape so
    :func:`spie.crosscheck.cross_solve` can require all three methods to agree."""
    ground = ground_all(puzzle)
    nvars = len(puzzle.variables)
    for horizon in range(puzzle.objective.max_horizon + 1):
        syms = _run(_build_program(puzzle, horizon, minimize=True), optimize=True)
        if syms is not None:
            trace, state_path = _extract(syms, ground, nvars, horizon)
            return Solution(True, horizon, trace, state_path, path_cost(puzzle, trace))
    return Solution(solvable=False, horizon=puzzle.objective.max_horizon)


def check_uniqueness(puzzle: Puzzle, solution: Solution) -> Uniqueness:
    """Block the found canonical state-path and re-solve at the same horizon.

    No further answer set ⇒ the minimal solution is unique under
    :data:`spie.results.EQUIVALENCE`; another ⇒ a genuinely different minimal trace exists.
    Mirrors :func:`spie.solver.check_uniqueness` with zero shared code."""
    if not solution.solvable:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)
    ground = ground_all(puzzle)
    nvars = len(puzzle.variables)
    block = _block_constraint(solution.state_path, nvars)
    program = _build_program(puzzle, solution.horizon, minimize=False, extra=block)
    syms = _run(program, optimize=False)
    if syms is None:
        return Uniqueness(unique=True, equivalence=EQUIVALENCE)
    witness, _ = _extract(syms, ground, nvars, solution.horizon)
    return Uniqueness(unique=False, equivalence=EQUIVALENCE, witness=witness)


def _block_constraint(state_path: tuple[tuple[int, ...], ...], nvars: int) -> str:
    """An integrity constraint forbidding exactly this per-tick state-path."""
    lits = ", ".join(
        f"holds({j},{t},{state_path[t][j]})"
        for t in range(len(state_path))
        for j in range(nvars)
    )
    return f":- {lits}."
