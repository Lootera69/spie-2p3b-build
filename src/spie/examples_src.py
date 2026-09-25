"""Hand-encoded example puzzles, authored in Python for readability.

These are the corpus the roadmap demands ("encode ~10 puzzles before building any
generation layer"). Each builder returns a :class:`~spie.ir.Puzzle`. ``write_examples``
serializes them to ``examples/*.json``, which is the form the CLI, solver and tests use.

Authoring in Python (with the ergonomic constructors in ``expr``) keeps the puzzles
legible and lets us stress the DSL's expressiveness directly. The JSON files are the
generated artifact — the source of truth is here.
"""

from __future__ import annotations

from .expr import Add, And, Const, Edge, Eq, Le, Node, Not, PVal, Reset, Sub, Var, all_of, any_of
from .ir import Action, Assign, Kind, Objective, Observability, Param, Puzzle, Variable

# Every builder is registered here; order fixes the NN_ file-number prefix.
BUILDERS: list = []


def _example(fn):
    BUILDERS.append(fn)
    return fn


@_example
def move() -> Puzzle:
    """#1 Movement. Walk an agent A -> B -> C -> D along a directed path. The simplest
    possible reachability puzzle: no objects, no resources — just get somewhere."""
    nodes = ("A", "B", "C", "D")
    edges = (("A", "B"), ("B", "C"), ("C", "D"))
    variables = (Variable("pos", Kind.LOC),)
    move_action = Action(
        name="move",
        params=(Param("src", True, ("A", "B", "C", "D")), Param("dst", True, ("A", "B", "C", "D"))),
        precondition=And(
            (
                Eq(Var("pos"), PVal("src")),
                Edge(PVal("src"), PVal("dst")),
            )
        ),
        effects=(Assign("pos", PVal("dst")),),
    )
    return Puzzle(
        id="01_move",
        title="The Long Corridor",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "A"},
        actions=(move_action,),
        objective=Objective(goal=Eq(Var("pos"), Node("D")), max_horizon=6),
        seed=1,
        notes="Reachability along a directed path; unique shortest solution has length 3.",
    )


@_example
def transform() -> Puzzle:
    """#2 Transformation. Refine raw ore into a blade through two state changes. No
    movement — the puzzle is the transformation chain itself."""
    variables = (Variable("form", Kind.INT, 0, 2),)  # 0=ore, 1=ingot, 2=blade
    smelt = Action(
        name="smelt",
        precondition=Eq(Var("form"), Const(0)),
        effects=(Assign("form", Const(1)),),
    )
    forge = Action(
        name="forge",
        precondition=Eq(Var("form"), Const(1)),
        effects=(Assign("form", Const(2)),),
    )
    return Puzzle(
        id="02_transform",
        title="The Forge",
        nodes=("Forge",),
        edges=(),
        variables=variables,
        initial={"form": 0},
        actions=(smelt, forge),
        objective=Objective(goal=Eq(Var("form"), Const(2)), max_horizon=5),
        seed=2,
        notes="Two-step refinement ore->ingot->blade; unique solution of length 2.",
    )


@_example
def resource() -> Puzzle:
    """#3 Resource budget. Cross a 3-hop corridor where every move burns one unit of
    fuel. The tank holds exactly enough: the budget, not the path, is the constraint."""
    nodes = ("A", "B", "C", "D")
    edges = (("A", "B"), ("B", "C"), ("C", "D"))
    variables = (
        Variable("pos", Kind.LOC),
        Variable("fuel", Kind.INT, 0, 3),
    )
    move_action = Action(
        name="move",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(
            Eq(Var("pos"), PVal("src")),
            Edge(PVal("src"), PVal("dst")),
            Le(Const(1), Var("fuel")),
        ),
        effects=(
            Assign("pos", PVal("dst")),
            Assign("fuel", Sub(Var("fuel"), Const(1))),
        ),
    )
    return Puzzle(
        id="03_resource",
        title="Fuel Budget",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "A", "fuel": 3},
        actions=(move_action,),
        objective=Objective(goal=Eq(Var("pos"), Node("D")), max_horizon=6),
        seed=3,
        notes="Reach D on a fuel budget of exactly 3; unique, and infeasible with less.",
    )


@_example
def lockkey() -> Puzzle:
    """#4 Lock and key. The gate to the Treasure opens only while carrying the key, which
    lies in a side room. Gating is expressed as a conditional inside the move guard."""
    nodes = ("Start", "KeyRoom", "Gate", "Treasure")
    edges = (("Start", "KeyRoom"), ("KeyRoom", "Gate"), ("Gate", "Treasure"))
    variables = (
        Variable("pos", Kind.LOC),
        Variable("has_key", Kind.BOOL),
    )
    move_action = Action(
        name="move",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(
            Eq(Var("pos"), PVal("src")),
            Edge(PVal("src"), PVal("dst")),
            # The Gate->Treasure edge is passable only with the key; all others are free.
            any_of(Not(Eq(PVal("dst"), Node("Treasure"))), Eq(Var("has_key"), Const(1))),
        ),
        effects=(Assign("pos", PVal("dst")),),
    )
    pickup = Action(
        name="pickup",
        precondition=all_of(Eq(Var("pos"), Node("KeyRoom")), Eq(Var("has_key"), Const(0))),
        effects=(Assign("has_key", Const(1)),),
    )
    return Puzzle(
        id="04_lockkey",
        title="The Locked Door",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "Start", "has_key": 0},
        actions=(move_action, pickup),
        objective=Objective(goal=Eq(Var("pos"), Node("Treasure")), max_horizon=8),
        seed=4,
        notes="Fetch the key, then pass the gate; unique solution of length 4.",
    )


@_example
def irreversible() -> Puzzle:
    """#5 Irreversible action with a loss trap. Grab the gem, leave, then seal the vault.
    Sealing can never be undone, and sealing empty-handed is an unrecoverable failure (the
    loss predicate), so the order is forced."""
    nodes = ("Vault", "Exit")
    edges = (("Vault", "Exit"),)
    variables = (
        Variable("pos", Kind.LOC),
        Variable("has_gem", Kind.BOOL),
        Variable("sealed", Kind.BOOL),
    )
    move_action = Action(
        name="move",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("pos", PVal("dst")),),
    )
    grab = Action(
        name="grab",
        precondition=all_of(Eq(Var("pos"), Node("Vault")), Eq(Var("has_gem"), Const(0))),
        effects=(Assign("has_gem", Const(1)),),
    )
    seal = Action(
        name="seal",
        precondition=all_of(Eq(Var("pos"), Node("Exit")), Eq(Var("sealed"), Const(0))),
        effects=(Assign("sealed", Const(1)),),
    )
    return Puzzle(
        id="05_irreversible",
        title="Seal the Vault",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "Vault", "has_gem": 0, "sealed": 0},
        actions=(move_action, grab, seal),
        objective=Objective(
            goal=all_of(Eq(Var("has_gem"), Const(1)), Eq(Var("sealed"), Const(1))),
            max_horizon=6,
            loss=all_of(Eq(Var("sealed"), Const(1)), Eq(Var("has_gem"), Const(0))),
        ),
        seed=5,
        notes="Grab, exit, seal; sealing is irreversible and sealing empty-handed loses.",
    )


@_example
def synchronize() -> Puzzle:
    """#6 Synchronization under a global invariant. Pass through an airlock whose two doors
    may never be open at once. Progress means coordinating the door states, not just
    walking — the invariant forbids the shortcut of opening both."""
    nodes = ("Outside", "Airlock", "Inside")
    edges = (("Outside", "Airlock"), ("Airlock", "Inside"))
    variables = (
        Variable("pos", Kind.LOC),
        Variable("doorA", Kind.BOOL),  # Outside <-> Airlock
        Variable("doorB", Kind.BOOL),  # Airlock <-> Inside
    )
    openA = Action(
        "openA", precondition=Eq(Var("doorA"), Const(0)), effects=(Assign("doorA", Const(1)),)
    )
    closeA = Action(
        "closeA", precondition=Eq(Var("doorA"), Const(1)), effects=(Assign("doorA", Const(0)),)
    )
    openB = Action(
        "openB", precondition=Eq(Var("doorB"), Const(0)), effects=(Assign("doorB", Const(1)),)
    )
    step_in = Action(
        name="step",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(
            Eq(Var("pos"), PVal("src")),
            Edge(PVal("src"), PVal("dst")),
            # the door guarding the edge being entered must be open
            any_of(
                all_of(Eq(PVal("dst"), Node("Airlock")), Eq(Var("doorA"), Const(1))),
                all_of(Eq(PVal("dst"), Node("Inside")), Eq(Var("doorB"), Const(1))),
            ),
        ),
        effects=(Assign("pos", PVal("dst")),),
    )
    return Puzzle(
        id="06_synchronize",
        title="The Airlock",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "Outside", "doorA": 0, "doorB": 0},
        actions=(openA, closeA, openB, step_in),
        objective=Objective(
            goal=Eq(Var("pos"), Node("Inside")),
            max_horizon=10,
            invariants=(Not(all_of(Eq(Var("doorA"), Const(1)), Eq(Var("doorB"), Const(1)))),),
        ),
        seed=6,
        notes="Airlock: doors never both open (invariant); unique length-5 solution.",
    )


@_example
def hidden() -> Puzzle:
    """#7 Hidden then visible state. A lever is concealed until searched; only once
    revealed can it be pulled. Models information that an action must first expose."""
    variables = (
        Variable("revealed", Kind.BOOL),
        Variable("pulled", Kind.BOOL),
    )
    search = Action(
        name="search",
        precondition=Eq(Var("revealed"), Const(0)),
        effects=(Assign("revealed", Const(1)),),
    )
    pull = Action(
        name="pull",
        precondition=all_of(Eq(Var("revealed"), Const(1)), Eq(Var("pulled"), Const(0))),
        effects=(Assign("pulled", Const(1)),),
    )
    return Puzzle(
        id="07_hidden",
        title="Hidden Lever",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"revealed": 0, "pulled": 0},
        actions=(search, pull),
        objective=Objective(goal=Eq(Var("pulled"), Const(1)), max_horizon=5),
        seed=7,
        notes="Reveal the lever before pulling it; unique solution of length 2.",
    )


@_example
def two_solutions() -> Puzzle:
    """#8 Deliberately non-unique — the uniqueness negative test. A diamond graph offers
    two distinct shortest routes to the goal, so the uniqueness check must report false."""
    nodes = ("S", "L", "R", "G")
    edges = (("S", "L"), ("S", "R"), ("L", "G"), ("R", "G"))
    variables = (Variable("pos", Kind.LOC),)
    move_action = Action(
        name="move",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("pos", PVal("dst")),),
    )
    return Puzzle(
        id="08_two_solutions",
        title="The Fork",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "S"},
        actions=(move_action,),
        objective=Objective(
            goal=Eq(Var("pos"), Node("G")), max_horizon=4, requires_unique=False
        ),
        seed=8,
        notes="Diamond graph with two length-2 routes S->L->G and S->R->G; NOT unique.",
    )


@_example
def combined() -> Puzzle:
    """#9 Multi-step combination. Fetch water from the well and fill the pot at home: a
    round trip that combines movement, carrying, and a multi-variable effect."""
    nodes = ("Home", "Well")
    edges = (("Home", "Well"), ("Well", "Home"))
    variables = (
        Variable("pos", Kind.LOC),
        Variable("has_water", Kind.BOOL),
        Variable("pot_filled", Kind.BOOL),
    )
    move_action = Action(
        name="move",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("pos", PVal("dst")),),
    )
    fill = Action(
        name="fill",
        precondition=all_of(Eq(Var("pos"), Node("Well")), Eq(Var("has_water"), Const(0))),
        effects=(Assign("has_water", Const(1)),),
    )
    pour = Action(
        name="pour",
        precondition=all_of(
            Eq(Var("pos"), Node("Home")),
            Eq(Var("has_water"), Const(1)),
            Eq(Var("pot_filled"), Const(0)),
        ),
        effects=(Assign("pot_filled", Const(1)), Assign("has_water", Const(0))),
    )
    return Puzzle(
        id="09_combined",
        title="Fetch Quest",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "Home", "has_water": 0, "pot_filled": 0},
        actions=(move_action, fill, pour),
        objective=Objective(goal=Eq(Var("pot_filled"), Const(1)), max_horizon=8),
        seed=9,
        notes="Go to the well, fill, return, pour; unique solution of length 4.",
    )


@_example
def pressure() -> Puzzle:
    """#10 Accumulate to a threshold, then commit. Pump the vessel to full pressure, then
    seal it. Sealing needs the threshold exactly and is irreversible — exercises integer
    arithmetic (Add), a bound (Le), and a final one-way commit."""
    variables = (
        Variable("pressure", Kind.INT, 0, 3),
        Variable("sealed", Kind.BOOL),
    )
    pump = Action(
        name="pump",
        precondition=all_of(Eq(Var("sealed"), Const(0)), Le(Var("pressure"), Const(2))),
        effects=(Assign("pressure", Add(Var("pressure"), Const(1))),),
    )
    seal = Action(
        name="seal",
        precondition=all_of(Eq(Var("pressure"), Const(3)), Eq(Var("sealed"), Const(0))),
        effects=(Assign("sealed", Const(1)),),
    )
    return Puzzle(
        id="10_pressure",
        title="Pressure Valve",
        nodes=("Vessel",),
        edges=(),
        variables=variables,
        initial={"pressure": 0, "sealed": 0},
        actions=(pump, seal),
        objective=Objective(goal=Eq(Var("sealed"), Const(1)), max_horizon=6),
        seed=10,
        notes="Pump to pressure 3 then seal; unique solution of length 4.",
    )


@_example
def signaled_trap() -> Puzzle:
    """#11 Signaled failure. Grab the gem, step to the Exit, then seal — but stepping out
    empty-handed is an *immediate, announced* loss, not a silent dead-end. Because every
    would-be dead-end is promoted to a ``loss`` this way, the reachable live space holds no
    silent trap, so ``trap_policy="signaled"`` is honoured (contrast #05, whose empty-handed
    Exit state is a *silent* trap and would fail the dead-state gate under this policy)."""
    nodes = ("Vault", "Exit")
    edges = (("Vault", "Exit"),)
    variables = (
        Variable("pos", Kind.LOC),
        Variable("has_gem", Kind.BOOL),
        Variable("sealed", Kind.BOOL),
    )
    move_action = Action(
        name="move",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("pos", PVal("dst")),),
    )
    grab = Action(
        name="grab",
        precondition=all_of(Eq(Var("pos"), Node("Vault")), Eq(Var("has_gem"), Const(0))),
        effects=(Assign("has_gem", Const(1)),),
    )
    seal = Action(
        name="seal",
        precondition=all_of(Eq(Var("pos"), Node("Exit")), Eq(Var("sealed"), Const(0))),
        effects=(Assign("sealed", Const(1)),),
    )
    return Puzzle(
        id="11_signaled_trap",
        title="Point of No Return",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "Vault", "has_gem": 0, "sealed": 0},
        actions=(move_action, grab, seal),
        objective=Objective(
            goal=all_of(Eq(Var("has_gem"), Const(1)), Eq(Var("sealed"), Const(1))),
            max_horizon=6,
            loss=all_of(Eq(Var("pos"), Node("Exit")), Eq(Var("has_gem"), Const(0))),
            trap_policy="signaled",
        ),
        seed=11,
        notes="Leaving empty-handed loses at once, so no silent trap remains; length 3, unique.",
    )


@_example
def toll_bridge() -> Puzzle:
    """#12 Weighted routes. From the Gate, the quick Bridge to the far side is also the
    cheapest way across; a scenic Trek costs more per step. Exercises non-unit
    :attr:`~spie.ir.Action.cost`, the search backend's Dijkstra min-cost path, and the
    shortcut gate certifying the minimal-*length* route is *also* cost-optimal — no cheaper
    detour undercuts it (contrast a toll that is fast but dear, which the gate would fail)."""
    nodes = ("Gate", "S", "A", "G")
    edges = (("S", "A"), ("A", "G"))
    variables = (Variable("pos", Kind.LOC),)
    enter = Action(
        name="enter",
        precondition=Eq(Var("pos"), Node("Gate")),
        effects=(Assign("pos", Node("S")),),
        cost=1,
    )
    bridge = Action(
        name="bridge",
        precondition=Eq(Var("pos"), Node("S")),
        effects=(Assign("pos", Node("G")),),
        cost=1,
    )
    trek = Action(
        name="trek",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("pos"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("pos", PVal("dst")),),
        cost=3,
    )
    return Puzzle(
        id="12_toll_bridge",
        title="The Toll Bridge",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"pos": "Gate"},
        actions=(enter, bridge, trek),
        objective=Objective(goal=Eq(Var("pos"), Node("G")), max_horizon=8),
        seed=12,
        notes="Bridge route is shortest and cheapest; the trek detour is longer and pricier.",
    )


@_example
def two_agents() -> Puzzle:
    """#13 Coordinated agents. A guard and a runner share one map. The runner may cross to
    the Keep only while the guard stands on the Plate, holding the drawbridge down — a guard
    that couples two *location* variables, so the solution is a joint plan, not a single
    walk. The corpus's first puzzle with more than one moving piece."""
    nodes = ("Field", "Mid", "Plate", "Bank", "Keep")
    edges = (("Field", "Mid"), ("Mid", "Plate"), ("Bank", "Keep"))
    variables = (
        Variable("guard", Kind.LOC),
        Variable("runner", Kind.LOC),
    )
    move_guard = Action(
        name="move_guard",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(Eq(Var("guard"), PVal("src")), Edge(PVal("src"), PVal("dst"))),
        effects=(Assign("guard", PVal("dst")),),
    )
    move_runner = Action(
        name="move_runner",
        params=(Param("src", True, nodes), Param("dst", True, nodes)),
        precondition=all_of(
            Eq(Var("runner"), PVal("src")),
            Edge(PVal("src"), PVal("dst")),
            # Crossing to the Keep needs the guard on the Plate (drawbridge lowered).
            any_of(Not(Eq(PVal("dst"), Node("Keep"))), Eq(Var("guard"), Node("Plate"))),
        ),
        effects=(Assign("runner", PVal("dst")),),
    )
    return Puzzle(
        id="13_two_agents",
        title="The Drawbridge",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"guard": "Field", "runner": "Bank"},
        actions=(move_guard, move_runner),
        objective=Objective(goal=Eq(Var("runner"), Node("Keep")), max_horizon=8),
        seed=13,
        notes="Guard reaches the Plate to lower the bridge, then the runner crosses; length 3.",
    )


@_example
def push_block() -> Puzzle:
    """#14 Pushing. A worker shoves a crate along a one-way track: stepping into the crate's
    cell drives it one ahead. Worker and crate are two coupled *location* variables that
    advance together (a three-place ``push`` reads two edges at once), so the crate reaches
    the dock only by being pushed the whole way — never pulled, never skipped."""
    nodes = ("P0", "P1", "P2", "P3", "P4")
    edges = (("P0", "P1"), ("P1", "P2"), ("P2", "P3"), ("P3", "P4"))
    variables = (
        Variable("worker", Kind.LOC),
        Variable("crate", Kind.LOC),
    )
    push = Action(
        name="push",
        params=(
            Param("src", True, nodes),
            Param("mid", True, nodes),
            Param("dst", True, nodes),
        ),
        precondition=all_of(
            Eq(Var("worker"), PVal("src")),
            Eq(Var("crate"), PVal("mid")),
            Edge(PVal("src"), PVal("mid")),
            Edge(PVal("mid"), PVal("dst")),
        ),
        effects=(Assign("worker", PVal("mid")), Assign("crate", PVal("dst"))),
    )
    return Puzzle(
        id="14_push_block",
        title="The Loading Dock",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"worker": "P0", "crate": "P1"},
        actions=(push,),
        objective=Objective(goal=Eq(Var("crate"), Node("P4")), max_horizon=8),
        seed=14,
        notes="Push the crate P1->P4; the worker follows one cell behind. Length 3, unique.",
    )


@_example
def which_door() -> Puzzle:
    """#15 Hidden-goal deduction. The prize sits behind one of two doors, but *which* door is
    a fact the player cannot see (``prize`` is HIDDEN over {Left, Right}). Walking into the
    wrong room strands you — so a linear plan cannot guarantee the prize. The player must
    ``peek`` (sensing the hidden location), branch on what they learn, then commit to the
    matching room. The corpus's first hidden-*goal* puzzle: sensing decides *where* to go."""
    nodes = ("Hall", "RoomL", "RoomR")
    edges = (("Hall", "RoomL"), ("Hall", "RoomR"))
    variables = (
        Variable("prize", Kind.BOOL, obs=Observability.HIDDEN),  # 0=RoomL, 1=RoomR
        Variable("pos", Kind.LOC),
        Variable("found", Kind.BOOL),
    )
    peek = Action(
        name="peek",
        precondition=Eq(Var("found"), Const(0)),
        effects=(),  # pure sensing: reveals which room holds the prize
        senses=("prize",),
    )
    go_left = Action(
        name="go_left",
        precondition=Eq(Var("pos"), Node("Hall")),
        effects=(Assign("pos", Node("RoomL")),),
    )
    go_right = Action(
        name="go_right",
        precondition=Eq(Var("pos"), Node("Hall")),
        effects=(Assign("pos", Node("RoomR")),),
    )
    grab_left = Action(
        name="grab_left",
        precondition=all_of(Eq(Var("pos"), Node("RoomL")), Eq(Var("prize"), Const(0)),
                            Eq(Var("found"), Const(0))),
        effects=(Assign("found", Const(1)),),
    )
    grab_right = Action(
        name="grab_right",
        precondition=all_of(Eq(Var("pos"), Node("RoomR")), Eq(Var("prize"), Const(1)),
                            Eq(Var("found"), Const(0))),
        effects=(Assign("found", Const(1)),),
    )
    return Puzzle(
        id="15_which_door",
        title="Which Door",
        nodes=nodes,
        edges=edges,
        variables=variables,
        initial={"prize": 0, "pos": "Hall", "found": 0},
        actions=(peek, go_left, go_right, grab_left, grab_right),
        objective=Objective(goal=Eq(Var("found"), Const(1)), max_horizon=6),
        seed=15,
        initial_belief={"prize": (0, 1)},
        notes="Peek to learn the prize room, then commit; a branching plan of worst-case depth 3.",
    )


@_example
def combination_lock() -> Puzzle:
    """#16 Mastermind-lite: multi-step deduction over four worlds. Two hidden bits form a
    combination (``bitA``, ``bitB`` each HIDDEN over {0, 1} => |B0| = 4). A gated ``stage``
    counter forces the two probes in order — ``probeA`` then ``probeB`` — each revealing one
    bit, so the belief splits twice before the player dials the one matching combination. The
    corpus's deepest deduction (worst-case depth 3) and its largest belief space."""
    variables = (
        Variable("bitA", Kind.BOOL, obs=Observability.HIDDEN),
        Variable("bitB", Kind.BOOL, obs=Observability.HIDDEN),
        Variable("stage", Kind.INT, 0, 2),  # visible probe-ordering gate
        Variable("open", Kind.BOOL),
    )
    probeA = Action(
        name="probeA",
        precondition=Eq(Var("stage"), Const(0)),
        effects=(Assign("stage", Const(1)),),
        senses=("bitA",),
    )
    probeB = Action(
        name="probeB",
        precondition=Eq(Var("stage"), Const(1)),
        effects=(Assign("stage", Const(2)),),
        senses=("bitB",),
    )
    dials = tuple(
        Action(
            name=f"dial{a}{b}",
            precondition=all_of(Eq(Var("stage"), Const(2)), Eq(Var("open"), Const(0)),
                                Eq(Var("bitA"), Const(a)), Eq(Var("bitB"), Const(b))),
            effects=(Assign("open", Const(1)),),
        )
        for a in (0, 1) for b in (0, 1)
    )
    return Puzzle(
        id="16_combination_lock",
        title="The Combination Lock",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"bitA": 0, "bitB": 0, "stage": 0, "open": 0},
        actions=(probeA, probeB, *dials),
        objective=Objective(goal=Eq(Var("open"), Const(1)), max_horizon=6),
        seed=16,
        initial_belief={"bitA": (0, 1), "bitB": (0, 1)},
        notes="Probe both hidden bits in order, then dial the matching combo; depth 3, 4 worlds.",
    )


@_example
def assembly_loop() -> Puzzle:
    """#17 Reset in a loop: persistent progress, transient scratch. Each cycle you ``work`` a
    transient bench slot up to ``ready``, ``bank`` it to advance the persistent ``level`` —
    which leaves the slot ``spent`` — then ``reboot`` (a first-class :class:`~spie.expr.Reset`)
    snaps the transient slot back to empty while the learned ``level`` survives. Because a
    spent slot admits neither ``work`` (needs empty) nor another ``bank`` (needs ready), the
    reboot is the *only* way to start the next cycle, so reaching ``level == 2`` forces two
    full work/bank/reboot loops. Fully observable: the reset marker grounds to a plain
    assignment, so both solvers agree by construction."""
    variables = (
        Variable("slot", Kind.INT, 0, 2),  # transient: 0=empty, 1=ready, 2=spent — reset clears it
        Variable("level", Kind.INT, 0, 2, persistent=True),  # banked work — survives reboot
    )
    work = Action(
        name="work",
        precondition=Eq(Var("slot"), Const(0)),
        effects=(Assign("slot", Const(1)),),
    )
    bank = Action(
        name="bank",
        precondition=all_of(Eq(Var("slot"), Const(1)), Le(Var("level"), Const(1))),
        effects=(Assign("level", Add(Var("level"), Const(1))), Assign("slot", Const(2))),
    )
    reboot = Action(name="reboot", precondition=Const(True), effects=(Reset(),))
    return Puzzle(
        id="17_assembly_loop",
        title="The Assembly Loop",
        nodes=("Bench",),
        edges=(),
        variables=variables,
        initial={"slot": 0, "level": 0},
        actions=(work, bank, reboot),
        objective=Objective(
            goal=all_of(Eq(Var("level"), Const(2)), Eq(Var("slot"), Const(0))),
            max_horizon=8,
        ),
        seed=17,
        notes="Two work/bank/reboot cycles bank level to 2; a spent slot forces reboot. Length 6.",
    )


@_example
def scout_reset() -> Puzzle:
    """#18 Blended deduction + reset. A HIDDEN, ``persistent`` ``target`` is a fixed fact of
    the world the player must deduce; ``scan`` senses it (dirtying a transient ``scratch``),
    the player branches to ``log`` the matching result into the persistent ``logged`` flag,
    then ``reset`` snaps the transient scratch back — leaving the hidden truth and the logged
    result untouched. Combines a branching sensing plan with reset semantics, and showcases a
    variable that is *both* hidden and persistent (so the reset never disturbs it)."""
    variables = (
        Variable("target", Kind.BOOL, obs=Observability.HIDDEN, persistent=True),
        Variable("scratch", Kind.INT, 0, 1),  # transient scan residue — cleared by reset
        Variable("logged", Kind.BOOL, persistent=True),  # the deduced result — survives reset
    )
    scan = Action(
        name="scan",
        precondition=Eq(Var("logged"), Const(0)),
        effects=(Assign("scratch", Const(1)),),
        senses=("target",),
    )
    log0 = Action(
        name="log0",
        precondition=all_of(Eq(Var("target"), Const(0)), Eq(Var("scratch"), Const(1)),
                            Eq(Var("logged"), Const(0))),
        effects=(Assign("logged", Const(1)),),
    )
    log1 = Action(
        name="log1",
        precondition=all_of(Eq(Var("target"), Const(1)), Eq(Var("scratch"), Const(1)),
                            Eq(Var("logged"), Const(0))),
        effects=(Assign("logged", Const(1)),),
    )
    reset = Action(name="reset", precondition=Eq(Var("logged"), Const(1)), effects=(Reset(),))
    return Puzzle(
        id="18_scout_reset",
        title="Scout and Reset",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"target": 0, "scratch": 0, "logged": 0},
        actions=(scan, log0, log1, reset),
        objective=Objective(
            goal=all_of(Eq(Var("logged"), Const(1)), Eq(Var("scratch"), Const(0))),
            max_horizon=6,
        ),
        seed=18,
        initial_belief={"target": (0, 1)},
        notes="Scan the hidden target, log the matching result, then reset scratch; depth 3.",
    )


@_example
def delayed_signal() -> Puzzle:
    """#19 Deduction through a lagged readout. A static hidden ``signal`` (0 or 1, fixed at the
    start but unknown) drives which commit is safe, yet the player never sees it directly: they
    read a gauge that lags the signal by two ticks (``signal`` is DELAYED, delay=2). For the
    first two ticks the gauge still shows its start value, so the two worlds are
    indistinguishable and — by uniformity — must take the same action; committing then is a
    gamble that fails in one world. Only after ``wait, wait`` does the gauge catch up and reveal
    the true signal, letting the player branch to the matching commit. The corpus's first
    *standing lagged observation*: information that is always visible but arrives late, compiled
    to a hidden shift register whose final stage is the visible readout."""
    variables = (
        Variable("signal", Kind.INT, 0, 1, obs=Observability.DELAYED, delay=2),  # static, lagged
        Variable("done", Kind.BOOL),
    )
    wait = Action(name="wait", precondition=Eq(Var("done"), Const(0)), effects=())
    commit0 = Action(
        name="commit0",
        precondition=all_of(Eq(Var("signal"), Const(0)), Eq(Var("done"), Const(0))),
        effects=(Assign("done", Const(1)),),
    )
    commit1 = Action(
        name="commit1",
        precondition=all_of(Eq(Var("signal"), Const(1)), Eq(Var("done"), Const(0))),
        effects=(Assign("done", Const(1)),),
    )
    return Puzzle(
        id="19_delayed_signal",
        title="The Lagging Gauge",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"signal": 0, "done": 0},
        actions=(wait, commit0, commit1),
        objective=Objective(goal=Eq(Var("done"), Const(1)), max_horizon=5),
        seed=19,
        initial_belief={"signal": (0, 1)},
        notes="Wait for the 2-tick-lagged gauge to reveal the signal, then commit; depth 3.",
    )


@_example
def remembered_recall() -> Puzzle:
    """#20 A vanishing password. A hidden ``code`` (0 or 1) is REMEMBERED: the player observes it
    only by ``read``-ing it, which latches what they saw. The lock then ``wipe``s the true code to
    0 — both worlds collapse to the same live state — before the player must ``enter`` the code
    they originally saw. Because the true code is gone, the only thing that still distinguishes the
    two worlds is the *memory*: a plain hidden sensing would let the belief reconverge at the wipe
    and strand the player, but the persistent latch carries the observed value across it, so the
    plan branches on what was remembered. The ``phase`` gate forces read→wipe→enter, and the latch
    starts at an out-of-range 'unread' sentinel, so committing without reading is impossible —
    the sense is load-bearing. The corpus's first *latched recall*: act on a transient observation
    after it is gone."""
    variables = (
        Variable("code", Kind.INT, 0, 1, obs=Observability.REMEMBERED),  # transient, must recall
        Variable("phase", Kind.INT, 0, 2),
        Variable("entered", Kind.BOOL),
    )
    read = Action(
        name="read",
        precondition=Eq(Var("phase"), Const(0)),
        effects=(Assign("phase", Const(1)),),
        senses=("code",),
    )
    wipe = Action(
        name="wipe",
        precondition=Eq(Var("phase"), Const(1)),
        effects=(Assign("phase", Const(2)), Assign("code", Const(0))),
    )
    enter0 = Action(
        name="enter0",
        precondition=all_of(
            Eq(Var("phase"), Const(2)), Eq(Var("entered"), Const(0)), Eq(Var("code"), Const(0))
        ),
        effects=(Assign("entered", Const(1)),),
    )
    enter1 = Action(
        name="enter1",
        precondition=all_of(
            Eq(Var("phase"), Const(2)), Eq(Var("entered"), Const(0)), Eq(Var("code"), Const(1))
        ),
        effects=(Assign("entered", Const(1)),),
    )
    return Puzzle(
        id="20_remembered_recall",
        title="The Vanishing Password",
        nodes=("Room",),
        edges=(),
        variables=variables,
        initial={"code": 0, "phase": 0, "entered": 0},
        actions=(read, wipe, enter0, enter1),
        objective=Objective(goal=Eq(Var("entered"), Const(1)), max_horizon=5),
        seed=20,
        initial_belief={"code": (0, 1)},
        notes="Read the transient code (latched), let it be wiped, then enter what you remembered.",
    )


def write_examples(out_dir: str) -> list[str]:
    """Build every registered example and write it to ``out_dir`` as NN_id.json.
    Returns the list of written paths."""
    import os

    from .serialize import save_puzzle

    os.makedirs(out_dir, exist_ok=True)
    written: list[str] = []
    for builder in BUILDERS:
        puzzle = builder()
        path = os.path.join(out_dir, f"{puzzle.id}.json")
        save_puzzle(puzzle, path)
        written.append(path)
    return written


__all__ = [
    "BUILDERS",
    "write_examples",
    "move",
    "transform",
    "resource",
    "lockkey",
    "irreversible",
    "synchronize",
    "hidden",
    "two_solutions",
    "combined",
    "pressure",
    "signaled_trap",
    "toll_bridge",
    "two_agents",
    "push_block",
    "which_door",
    "combination_lock",
    "assembly_loop",
    "scout_reset",
    "delayed_signal",
    "remembered_recall",
]
