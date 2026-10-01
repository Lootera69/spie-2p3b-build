# SPIE — Symbolic Puzzle Invention Engine

For **BrainBloom question generation without LLMs**, start with the
[six-format workshop](docs/brainbloom-workshop.md). From this directory on
Windows, run `./start-brainbloom.ps1`. It opens a local form for category, topic, format,
difficulty and count, with playable previews and downloadable unpublished drafts.
It supports Multiple Choice, True / False, Type Answer, Crossword, Riddle and Wonder
across the five platform categories. Checks depend on the family: mathematical
proofs, exact word transformations or crossword reconstruction. Saved drafts can be replayed.
The launcher uses the existing sibling question bank and Studio verifier when available.

**The workshop now uses plain-language activities.** Enter up to six topics,
let the engine select suitable meanings, and select **Choose for me**, **Solve a set
of clues**, **Weigh the evidence**, **Choose the best next question**, or a compatible
word/mathematical activity. Meanings remain visible and optionally editable. The
default is hard multi-clue deduction or adaptive planning. All supplied topics must
be represented in every draft.
 Challenge level, answer format and count are checked together before generation. The
 **Create a custom logic grid** activity accepts creator-authored groups and finite rules,
 reports contradictions or ambiguity, and can add explicitly labelled clues to prove a unique
grid. The player preview includes an interactive fillable grid.
Generated grids include deterministic exhaustive-elimination metrics and solving hints.
These structural measures are not a player-validated model of human reasoning or difficulty.
For beginners, **Design a clue puzzle for me** is the recommended activity: the engine selects
topic labels, invents groups and clues, searches several candidates, and verifies that the
answer needs multiple clues. Manual groups and rules remain available under Advanced mode.
Variation numbers and exploration time live under **More options**. See the
[complete connected flow](docs/brainbloom-workshop-flow.md).

Choose **Describe it in my own words…** to type supported instructions, such as
“Make 3 hard multiple-choice puzzles. Players should solve a set of clues.”
The workshop shows its interpretation and asks you to apply changed settings;
unrecognised rules require clarification. This is a local rule-based parser, with
no LLM. Setup and drafts scroll independently, and generation reveals the new
results automatically. Small screens use Setup/Drafts tabs.
See [written instructions and workspace panels](docs/brainbloom-instructions.md).

 The deeper reasoning engine invents multi-clue deduction problems, exact Bayesian
evidence problems, and optimal adaptive-question planning problems. It compares
12/32/80 candidates, ranks a documented structural objective, independently checks
the winner and reports what was measured. See
[the reasoning lab and non-LLM roadmap](docs/brainbloom-reasoning.md).

**User-entered topics are supported together.** Enter words or short phrases. Meanings
are selected automatically; word scrambling, missing letters, alphabetical ordering,
crosswords and letter-counting Wonders remain explicit choices. Twenty distinct authored
topics ship across 28 retained pack versions. The eight coverage-v2 topics contain 106
entries: 96 adapted from OEWN and ten project-authored additions. Optional local WordNet adds roughly 151,000 indexed terms and
117,000 senses; topic coverage depends on usable related words, not just dictionary size.
Install it once with `./.venv/Scripts/python.exe -m spie.questions.brainbloom dictionary-install`.
Generation and saved-draft replay then work offline. See the
[dictionary workflow and limits](docs/brainbloom-dictionary.md).

This development path permits mathematical generation, search and non-LLM machine
learning. No LLM is involved in the workshop, and no training or API key is required.
Difficulty controls structural complexity; it is not a trained prediction of player success.

The earlier [corpus-conditioned LLM writer](docs/brainbloom-generator.md)
(`python -m spie.forge`) remains a separate experimental path and is not invoked by
the workshop. The action-puzzle research engine described below is also separate.

**Creativity from search, correctness from formal solvers.** SPIE represents logic puzzles
as formal, bounded state machines, then uses **three independent solvers** — an SMT backend (Z3),
an explicit-state search, and an answer-set-programming backend (clingo/ASP) — to *prove* them
solvable and unique, cross-checks all three, and re-checks every proof against an independent
interpreter before trusting it. No language model ever sits in the correctness path.

This directory covers the roadmap's representation and proof layers (Phases 1–3), its
**creative front half** (Phase 4) — puzzles are *invented* from concepts and evolved by a
quality-diversity search, never hand-typed — and its **evaluative back half** (Phase 5): a
human-like strategy solver and a surprise metric, an archive that records lineage and rejection
history, a deterministic renderer, and a difficulty evaluator recalibrated against honestly-labeled
synthetic telemetry. It can:

1. **load** a puzzle from canonical JSON,
2. **simulate** it in a deterministic interpreter (the ground-truth runtime),
3. **prove** it solvable — a minimal linear trace when fully observable, or a **contingent
   branching plan** when the initial state is partly hidden and must be sensed,
4. **prove** the minimal solution unique,
5. **cross-check** three independent solvers that share no solving code (gate G2), lifted to
   partial observability by two independent epistemic methods,
6. **conformance-check** the solution by replaying it through the interpreter — over *every*
   possible world when the state is hidden, with no-clairvoyance (uniformity) verified,
7. **verify** a suite of quality gates and emit a deterministic **machine quality vector**
   (difficulty band, novelty, elegance, fairness),
8. **emit** a reproducible, machine-verifiable certificate,
9. **invent** a puzzle from a single word through a concept→mechanic pipeline, and **evolve** a
   byte-reproducible MAP-Elites archive of the best puzzle per behavioral niche — admitting only
   candidates that pass the very same correctness gates, so **no language model ever generates a
   proof**,
10. **read** each puzzle with a deterministic, bounded-rational **strategy solver** that models a
    human-like player, and score its **surprise** — the prediction error at the puzzle's key
    inference — both pure functions of the formal puzzle, needing no player data,
11. **archive** invented puzzles with full **lineage** (parent niche, operator, generation) and a
    **rejection history**, content-addressed and reconstructable back from JSON,
12. **present** a puzzle as human-readable rules, a progressive hint ladder, the worked answer, and
    the machine-readable certificate — a pure view of the formal rep, containing no gameplay logic
    of its own, and
13. **learn**: recalibrate the difficulty evaluator's weights against honestly-labeled **synthetic**
    player telemetry and report whether the fit generalizes to held-out puzzles (Gate G5).

Twenty hand-encoded puzzles anchor the corpus (the standing regression oracle), including
hidden-state deduction and reset/persistence loops; the invention engine builds on top of them.

## Requirements

- Python 3.12+
- [z3-solver](https://pypi.org/project/z3-solver/) 4.13.4 and
  [clingo](https://pypi.org/project/clingo/) 5.8.2 (installed automatically below)

## Install (Windows)

Python is installed via `winget`; the engine and its dependencies go in a local virtualenv.

```bash
winget install -e --id Python.Python.3.12
```

From this `engine/` directory:

```bash
py -3.12 -m venv .venv
```

```bash
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

Smoke-test that Z3 imported:

```bash
./.venv/Scripts/python.exe -c "import z3; print(z3.get_version_string())"
```

## Quick start

All commands below use the venv Python directly. (If you activate the venv, the installed
`spie` console script and `python -m spie.cli` are equivalent.)

Generate the example JSON files from the Python source of truth:

```bash
./.venv/Scripts/python.exe -m spie.cli gen
```

Solve one puzzle end to end — this is the core demo (find a minimal solution, then confirm
it replays cleanly through the interpreter):

```bash
./.venv/Scripts/python.exe -m spie.cli solve examples/01_move.json
```

Report the uniqueness verdict (the fork puzzle is deliberately non-unique):

```bash
./.venv/Scripts/python.exe -m spie.cli unique examples/08_two_solutions.json
```

Solve a puzzle with hidden initial state — the engine senses the hidden fact and prints a
**contingent branching plan** (each `observe (...)` line selects the sub-plan for what was
seen), proven to reach the goal on every possible world:

```bash
./.venv/Scripts/python.exe -m spie.cli solve examples/16_combination_lock.json
```

Cross-check the three independent solvers and run the full verification suite:

```bash
./.venv/Scripts/python.exe -m spie.cli crosscheck examples/15_which_door.json
```

```bash
./.venv/Scripts/python.exe -m spie.cli verify examples/17_assembly_loop.json
```

Emit a full certificate as canonical JSON:

```bash
./.venv/Scripts/python.exe -m spie.cli cert examples/01_move.json
```

Certify the whole corpus and print a summary table (with each puzzle's `|B0|` — the number of
worlds in its initial belief — difficulty band, and static score):

```bash
./.venv/Scripts/python.exe -m spie.cli suite
```

**Invent** a puzzle from a single word — run the whole concept→mechanic pipeline, then certify
and print it (the pipeline is total over the curated vocabulary, so any KB word works):

```bash
./.venv/Scripts/python.exe -m spie.cli invent lock
```

**Evolve** a MAP-Elites archive from a few seed words and write it out (byte-reproducible for a
given seed), then summarize the occupied niches as a table:

```bash
./.venv/Scripts/python.exe -m spie.cli evolve --seeds door,fuel,water --iters 20 --out archive.json
```

```bash
./.venv/Scripts/python.exe -m spie.cli archive show archive.json
```

**Present** a puzzle as text — rules, a progressive hint ladder, the worked answer, and the
machine-readable certificate, all derived purely from the formal rep:

```bash
./.venv/Scripts/python.exe -m spie.cli present examples/16_combination_lock.json
```

**Calibrate** the difficulty evaluator against synthetic-player telemetry — fit the difficulty
weights to the simulated population's effort and report the held-out rank correlation (Gate G5):

```bash
./.venv/Scripts/python.exe -m spie.cli calibrate --players 20 --out calibration.json
```

Other commands: `validate PUZZLE` (static checks + score), `conform PUZZLE` (replay check,
over all worlds when hidden), and `quality PUZZLE` (the machine quality vector as JSON). Every
command exits non-zero if the puzzle is unsolvable, non-conformant, fails a gate, the solvers
disagree, has validation findings, or (for `invent`/`evolve`) nothing certified — so they
compose in scripts.

## How it works

The design turns on a **single source of semantics**. One expression AST
([`expr.py`](src/spie/expr.py)) is walked by two backends that must never disagree:

- [`evaluate.py`](src/spie/evaluate.py) / [`interpreter.py`](src/spie/interpreter.py) —
  the deterministic Python runtime, the ground truth.
- [`z3_compile.py`](src/spie/z3_compile.py) — the same AST compiled to Z3 terms for
  bounded model checking.

Because both traverse one structural definition, the only duplication is a trivial
per-node mapping — and [`test_solver_agreement.py`](tests/test_solver_agreement.py) proves
they never drift, both per-node and across every example.

**Proof loop** ([`solver.py`](src/spie/solver.py), [`conformance.py`](src/spie/conformance.py)):

1. *Reachability.* Unroll the transition relation to horizon `H` with one Int constant per
   `(variable, tick)`; assert init, domains, per-tick invariants/loss, an
   exactly-one-action selector per tick, and the goal at `H`. Search `H` upward from 0 — the
   first satisfiable `H` is the minimal solution length.
2. *Framing.* Each action asserts its effects at `t+1` and holds every unwritten variable
   constant, so the frame problem is handled explicitly and identically in both backends.
3. *Uniqueness.* Take the solution's canonical **state-path**, add a clause forbidding
   exactly that path, and re-solve at the same `H`. `unsat` ⇒ unique; `sat` ⇒ a genuinely
   different minimal solution exists.
4. *Conformance.* Replay the solver's trace through the interpreter and require that it is
   accepted, reaches the goal, and reproduces the solver's exact state-path. Only then is
   the [`certificate`](src/spie/certificate.py) trusted.

Serialization ([`serialize.py`](src/spie/serialize.py)) is canonical (sorted keys, fixed
separators), so certifying the same puzzle twice yields byte-identical JSON.

## Three independent solvers (gate G2)

Trusting one solver is trusting one implementation. SPIE runs three structurally independent
solvers that share **zero** solving code: the Z3 SMT backend
([`solver.py`](src/spie/solver.py)), an explicit-state forward search over the reachable graph
([`search.py`](src/spie/search.py)), and an answer-set-programming backend
([`asp_solver.py`](src/spie/asp_solver.py), clingo) — three paradigms (SMT, explicit search,
ASP), each reading its verdict from its own certificate.
[`crosscheck.py`](src/spie/crosscheck.py) requires all three to agree on solvability, minimal
size, and uniqueness before the certificate stands. A disagreement is a hard failure, never a
warning. [`verify.py`](src/spie/verify.py) runs this and a suite of further gates
(reachability, uniqueness, shortcut-freedom, dead-state fairness, minimality, determinism,
information-necessity), and [`quality.py`](src/spie/quality.py) +
[`fingerprint.py`](src/spie/fingerprint.py) derive a byte-deterministic quality vector
(difficulty band, corpus-relative novelty, elegance, fairness).

## The epistemic layer (partial observability)

A puzzle may declare variables `HIDDEN` with an **initial belief** — the finite set of worlds
consistent with what the player can observe — and actions that `sense` them. The solution is
then a **contingent plan** (a policy tree): sensing outcomes branch it, and it must reach the
goal and avoid loss on *every* world in the belief `B0`, choosing actions that depend only on
what has been observed (the **no-clairvoyance / uniformity** constraint). This is strong
planning, and it is again cross-checked by two independent methods:

- **Method A** ([`epistemic.py`](src/spie/epistemic.py)) — a backward belief-space AND/OR
  fixpoint over sets of live worlds, using only the interpreter's semantics.
- **Method B** ([`z3_epistemic.py`](src/spie/z3_epistemic.py)) — a bounded multi-world SMT
  encoding: one world-trajectory per belief world, action choices tied across still-
  indistinguishable worlds, goal asserted on all copies and loss on none.

**Reduction anchor.** When nothing is hidden, `B0` is a singleton, belief space collapses to
the ordinary world graph, and the contingent plan degenerates to a single linear trace — so
the fully-observable puzzles emit certificates byte-identical to the pre-epistemic engine.
That is both the backward-compatibility guarantee and a standing regression oracle, checked by
hypothesis property tests ([`test_epistemic_properties.py`](tests/test_epistemic_properties.py)).
A [`Reset`](src/spie/expr.py) effect (expanded at grounding into per-variable restores, with
`persistent` variables surviving it) lets puzzles express loops without touching the semantic
core, so all three engines still agree by construction.

## Invention (concept → mechanic → search)

The corpus above is hand-authored. On top of it sits the roadmap's **creative engine**: puzzles
are *invented* from concepts and *evolved* by quality-diversity search, with the formal solvers —
not a language model — deciding what is correct. Every generated candidate flows through the exact
same `validate → verify → certify` gates the twenty hand puzzles do; the generator has no
privileged path and cannot seat an unproven puzzle anywhere.

**The concept→mechanic pipeline** (`Sense → Expand → Afford → Blend → Operationalize → Ablate`)
turns a single word into an executable puzzle:

- [`concepts.py`](src/spie/concepts.py) — a curated, in-repo relation lexicon (IsA / UsedFor /
  CapableOf / HasProperty / Causes / PartOf, plus puzzle *affordances*). `sense` maps a word to a
  typed concept node; `expand` runs a bounded, sorted BFS into a local semantic graph. No live
  ConceptNet, no LLM — the KB is deterministic and inspectable.
- [`afford.py`](src/spie/afford.py) — `afford` reads each concept's affordance tags into mechanic
  templates (connect / consume / propagate / negate / preserve / reveal / delay); `blend` couples
  them into a backend-agnostic **rule graph**.
- [`operationalize.py`](src/spie/operationalize.py) — compiles a rule graph into a real
  [`ir.Puzzle`](src/spie/ir.py) using the same expression constructors and `Observability` / `Reset`
  vocabulary as the hand puzzles, with canonical naming so the same graph is byte-identical every
  time. It also threads **provenance** (which concept produced which action).
- **Ablate** — the pipeline's closing loop, and the content behind the `concept-relevance` gate. A
  concept counts as *used* only if removing its elements changes the puzzle's behavioral
  [`search.signature`](src/spie/search.py); `invent` drops any inert modifier concept and recompiles
  until every surviving concept is load-bearing ([`verify.inert_concepts`](src/spie/verify.py) is
  the shared criterion). This is a *checked* property of every generated puzzle, never asserted.

**Invention operators** ([`operators.py`](src/spie/operators.py)) — sixteen mutation operators in
the roadmap's four families (Structural / Temporal / Information / Goal-constraint), each a pure
`Puzzle -> Puzzle | None` that ends by re-validating its result, so a malformed mutation is
discarded rather than offered to the search.

**MAP-Elites** ([`mapelites.py`](src/spie/mapelites.py)) — a dependency-free, fully-seeded
quality-diversity archive. The niche is a small integer tuple read from the quality vector
(difficulty band, `|B0|` bucket, plan-branching bucket); admission requires `validate` clean **and**
`verify().ok` **and** `certify().solvable`; within a niche the higher novelty+elegance blend wins.
Every random draw comes from one `random.Random(seed)` and the archive serializes through the
canonical `dumps`, so a run is **byte-reproducible** for a given `(seeds, iterations, seed)`.
[`invent.py`](src/spie/invent.py) is the thin orchestration the `invent` / `evolve` CLI commands
call. Property tests
([`test_generator_properties.py`](tests/test_generator_properties.py)) hunt with `hypothesis` for
any invented, mutated, or archived puzzle that escapes the gates — generator soundness, operator
well-formedness, and archive determinism, checked adversarially rather than assumed.

## Evaluation, archive, presentation, learning (the back half)

Proving a puzzle correct is not the same as knowing whether it is *good*. On top of the machine
quality vector sits the roadmap's back half — a human-like reading of each puzzle, an archive that
remembers where every elite came from, a faithful renderer, and a learning loop that recalibrates
the difficulty evaluator. As everywhere else the measurements are deterministic and formal: **no
language model sits in the evaluation, acceptance, or measurement path.**

**A human-like strategy solver + surprise** ([`strategy.py`](src/spie/strategy.py)). The formal
solvers find *optimal* play; a human does not. The strategy solver is a deterministic,
bounded-rational player — greedy best-first search with chronological backtracking under a myopic
`LOOKAHEAD`-bounded heuristic that **never** consults the exact goal distance (that oracle is
reserved for measuring surprise, not for playing). It reports proxies with no analogue in the
static formula — `backtracks`, `memory_load`, `steps_taken` — and collapses to the optimal linear
trace on trivial puzzles. **Surprise** is the player's prediction error at the puzzle's pivot: for
a fully-observable puzzle, the *regret* of the greedy move against the forced one at the moment they
diverge (a "plan-flip"); for a hidden puzzle, the *belief collapse* in bits when a sense resolves
the world (a "belief-collapse"). Both are pure functions of the puzzle — grounded in the
reachability oracle, never in themselves — so they need no player data. They fold into
[`quality.py`](src/spie/quality.py) additively, as *reported* descriptors: the MAP-Elites niche and
fitness are deliberately **unchanged**, so surprise cannot be gamed into the archive by trap-spam.

**An archive with memory** ([`mapelites.py`](src/spie/mapelites.py)). Each elite now carries its
**lineage** — the parent niche and puzzle digest, the operator and family that produced it, and its
generation — and every rejected candidate is retained in a **rejection history** (its digest and
the gate it failed), alongside the integer tally. Both puzzle and certificate are
**content-addressed** by SHA-256, and the archive round-trips: `archive_from_json` reconstructs an
archive whose re-serialization is byte-identical *and* whose every parsed cell recomputes to its
stored quality — so a written archive can be read back for learning without trusting the writer.

**A faithful renderer** ([`presentation.py`](src/spie/presentation.py)). `render` turns a puzzle
and its certificate into ASCII text — the rules (the map, the state variables, each action's
precondition / effects / senses / cost, the objective), a progressive **hint ladder**, the worked
**answer** (the certificate's own solution trace and per-step states), and the machine-readable
certificate. The non-negotiable invariant is that the renderer holds **no gameplay logic absent
from the formal rep**, and this is enforced as a test rather than assumed: a checked bijection
between the symbols named in the rendered rules and the puzzle's actual nodes / variables / actions,
with the hint ladder proven a subset of the proof and the replayed states equal to an independent
re-solve.

**A learning loop on synthetic telemetry** ([`telemetry.py`](src/spie/telemetry.py),
[`calibrate.py`](src/spie/calibrate.py)). Gate G5 asks whether the machine metrics *predict*
difficulty. To answer it honestly without fabricating human data, a **synthetic player** — a
seeded, stochastic, deliberately noisier variant of the strategy solver (random lookahead,
epsilon-greedy slips, hint requests when stuck, restarts) — is simulated over each puzzle, and every
record is stamped `synthetic=True, source="strategy-solver-simulation"` with **no** human-provenance
field. Its per-player seed is a stable SHA-256 digest, so telemetry is byte-reproducible across
processes. Calibration then fits the *static* structural difficulty weights to maximize the
**Spearman rank correlation** between predicted difficulty and the simulated population's observed
effort, by deterministic coordinate ascent (strict improvements only, from the live coefficients as
baseline). The discipline that keeps the fit honest: predictor and target share only the puzzle —
the target is a distinct, noisier process — so the fit means something only if it **generalizes**,
which is why the puzzles are split into train and held-out sets and both correlations are reported.
G5 is the held-out correlation clearing a documented threshold, **reported, never asserted into
being**. Crucially, calibration produces an *artifact* (fitted weights + correlations); it does
**not** rewrite the live difficulty coefficients, so the corpus's bands, niches, and certificates
stay byte-identical.

## The corpus

Twenty puzzles authored in [`examples_src.py`](src/spie/examples_src.py), each chosen to
stress a different part of the representation. `|B0|` is the number of worlds in the initial
belief (1 = fully observable); `H` is the minimal solution size (worst-case plan depth when
hidden).

| # | Puzzle | `\|B0\|` | H | Unique |
|---|--------|:------:|:-:|:------:|
| 01 | The Long Corridor — movement / reachability | 1 | 3 | yes |
| 02 | The Forge — integer state transformation | 1 | 2 | yes |
| 03 | Fuel Budget — resource depletion | 1 | 3 | yes |
| 04 | The Locked Door — conditional gating (key) | 1 | 4 | yes |
| 05 | Seal the Vault — irreversible action + loss trap | 1 | 3 | yes |
| 06 | The Airlock — global invariant / synchronization | 1 | 5 | yes |
| 07 | Hidden Lever — hidden→visible state | 1 | 2 | yes |
| 08 | The Fork — **deliberately non-unique** (negative test) | 1 | 2 | **no** |
| 09 | Fetch Quest — move + carry + multi-var effect | 1 | 4 | yes |
| 10 | Pressure Valve — accumulate to threshold + commit | 1 | 4 | yes |
| 11 | Point of No Return — signaled loss trap | 1 | 3 | yes |
| 12 | The Toll Bridge — action cost / payment | 1 | 2 | yes |
| 13 | The Drawbridge — two-agent synchronization | 1 | 3 | yes |
| 14 | The Loading Dock — pushable block | 1 | 3 | yes |
| 15 | Which Door — **sense the hidden prize, then commit** | 2 | 3 | yes |
| 16 | The Combination Lock — **two hidden bits, ordered probes** | 4 | 3 | yes |
| 17 | The Assembly Loop — **reset loop + persistence** | 1 | 6 | yes |
| 18 | Scout and Reset — **hidden target + reset, persistent memory** | 2 | 3 | yes |
| 19 | The Lagging Gauge — **DELAYED readout, deduce the lagged signal** | 2 | 3 | yes |
| 20 | The Vanishing Password — **REMEMBERED transient, latched recall** | 2 | 3 | yes |

## Testing

```bash
./.venv/Scripts/python.exe -m pytest -q
```

```bash
./.venv/Scripts/python.exe -m ruff check src tests
```

The suite covers the interpreter, Z3/search/interpreter agreement (per-node and across the
corpus), uniqueness (positive and negative), the validator, the verification gates and quality
vector, the epistemic layer (Method A ≡ Method B, per-world conformance, the reduction anchor),
reset semantics, the full corpus (certification, expected sizes/verdicts, serialization
round-trip, determinism), and the invention layer (the concept→mechanic pipeline, the sixteen
operators, MAP-Elites admission + determinism, and end-to-end `invent` / `evolve` / `archive show`).
The back half is covered too — the strategy solver + surprise (a deceptive fixture proving the new
signals are not optimal-cost re-encodings), the archive's lineage / rejection / round-trip, the
renderer's fidelity bijection, and the synthetic-telemetry calibration (distinct-process +
generalization + byte-reproducibility). Property-based tests
([`test_property.py`](tests/test_property.py),
[`test_epistemic_properties.py`](tests/test_epistemic_properties.py),
[`test_generator_properties.py`](tests/test_generator_properties.py)) hunt with `hypothesis` for
any random puzzle on which the independent backends disagree, or any invented / mutated / archived
puzzle that escapes the correctness gates — and, for the back half, for any drift in
strategy/surprise determinism, archive read-back, presentation fidelity, or calibration
reproducibility.

## Project layout

```
engine/
  pyproject.toml          # package + deps (z3-solver, clingo) + [dev] extras (pytest, ruff, hypothesis)
  src/spie/
    expr.py               # expression + effect AST (incl. Reset) — the one definition of semantics
    ir.py                 # Puzzle / Action / Objective / Certificate / Observability dataclasses
    evaluate.py           # eval_expr + apply_effects (interpreter half)
    interpreter.py        # deterministic run(puzzle, trace) -> Outcome
    ground.py             # expand parameterised actions + Reset markers into ground actions
    z3_compile.py         # compile_expr + build_unrolling (Z3 half)
    solver.py             # Z3 solve() + check_uniqueness()   [Method / backend 1]
    search.py             # explicit-state search solve() + check_uniqueness()   [backend 2]
    asp_solver.py         # answer-set-programming (clingo) solve() + check_uniqueness()   [backend 3]
    crosscheck.py         # run all three backends, require agreement (gate G2)
    epistemic.py          # belief-space AND/OR contingent solver   [epistemic Method A]
    z3_epistemic.py       # bounded multi-world SMT contingent solver   [epistemic Method B]
    results.py            # Plan (contingent policy tree) + Solution types
    conformance.py        # replay trace / plan through the interpreter (all worlds when hidden)
    validate.py           # static structural checks -> findings
    verify.py             # the verification gate suite
    quality.py            # deterministic machine quality vector
    fingerprint.py        # corpus-relative novelty features
    report.py             # score = 100 - 8*findings + histogram
    certificate.py        # run the whole loop, assemble a Certificate
    serialize.py          # canonical JSON <-> IR
    augment.py            # desugar: compile DELAYED (shift register) + REMEMBERED (latch) to VISIBLE + HIDDEN
    examples_src.py       # the 20 hand-encoded puzzles (source of truth)
    concepts.py           # curated relation lexicon + Sense/Expand (INPUT -> semantic graph)
    afford.py             # Afford + Blend: semantic graph -> mechanic rule graph
    operationalize.py     # compile a rule graph -> ir.Puzzle (+ concept provenance)
    operators.py          # the 16 invention operators (Structural/Temporal/Information/Goal)
    mapelites.py          # hand-rolled deterministic MAP-Elites quality-diversity archive
    invent.py             # orchestration: invent(word) + evolve(seeds) over the pipeline
    strategy.py           # bounded-rational human-like strategy solver + surprise metric
    presentation.py       # deterministic renderer: rules / hints / answer / certificate (ASCII)
    telemetry.py          # seeded synthetic player -> honestly-labeled telemetry
    calibrate.py          # recalibrate difficulty weights vs synthetic effort (Spearman, Gate G5)
    cli.py                # gen | validate | solve | unique | conform | crosscheck | verify | quality | cert | present | suite | invent | evolve | archive show | calibrate
  examples/               # generated puzzle JSON
  tests/
```

## Out of scope (deferred to later phases)

**Real human playtest telemetry** and **human-calibrated difficulty / surprise** remain deferred:
the surprise metric is now a machine proxy grounded in the reachability oracle, and difficulty
calibration is validated end-to-end on honestly-labeled *synthetic* telemetry — the harness proves
the *mechanism* (weights move, rank correlation improves and generalizes to held-out puzzles) with
no claim that the numbers reflect real humans. **Live ConceptNet ingestion** or a larger concept
graph (the KB is curated in-repo and LLM-free by design), any **web player, theming, or dashboard**
(the renderer emits text + a machine-readable certificate; a GUI is out of scope), and **learned
search policies** (calibration recalibrates *evaluators*, not the MAP-Elites operator distribution)
also remain deferred. The concept→mechanic pipeline, the invention operators, and the MAP-Elites
search that used to live here are now implemented — see
[Invention](#invention-concept--mechanic--search) above; the strategy solver, surprise metric,
archive lineage, renderer, and calibration loop are described in [Evaluation, archive, presentation,
learning](#evaluation-archive-presentation-learning-the-back-half).

Both history-dependent observation modes are solved by semantics-preserving compilation
([`augment.py`](src/spie/augment.py)): a `DELAYED` variable compiles to a hidden shift register
whose final stage is a VISIBLE lagged readout, and a `REMEMBERED` variable compiles to a VISIBLE
persistent latch that snapshots the transient value on a sense (with an out-of-range sentinel
initial that makes the sense load-bearing). Every solver, the interpreter, and conformance run
unchanged, and Method A ≡ Method B holds by construction. With that, all four `Observability`
modes are implemented, and the clingo/ASP third solving method (gate G2) is now implemented in
[`asp_solver.py`](src/spie/asp_solver.py) — three independent methods (SMT, explicit search, ASP)
stand behind every fully-observable proof.
