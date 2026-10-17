# Interacting energy, gate and switch puzzles

The workshop activity **Plan with energy and switches** generates a small, fully
observable planning world. An action changes what the player can do next: movement
uses energy, switches persistently flip gates, and the battery can be recharged once.
Revision 11 introduced complete authored scenarios alongside the first-move quiz.
Revision 12 added concise stories and a dependency check on every shortest route;
revision 13 develops broader candidate proposals within the same quality bounds.
See the [current experience contract and validation status](planning-experience-v13.md)
and the [original episode contract](planning-experience.md).

This is a finite family of generated state machines. It extends the creator with
branching choices; it does not replace the older concept compiler with an arbitrary
mechanic-composition language. Topic words label fictional locations and do not supply
unstated facts or causal rules.

## Rules

The complete state is `(location, energy, gate A, gate B, recharge used)`. Easy, medium
and hard use four, five and six rooms. Only listed directed routes are legal; each route
specifies its energy cost and optional required open gate. A switch flips its listed
gates and can have an energy cost. The charger restores the battery to capacity, only
below capacity and only once. Revisits are allowed; reaching the final room ends play.

Every move, switch use and recharge costs **one action**. Energy limits feasibility;
it is not the quantity being minimized. The answer minimizes the total action count,
assuming optimal choices after the first action. Three start routes and the start
switch provide the four answer options. An option can initially be unavailable.

## Revision-10 strategy synthesis (preserved)

New requests select one of four profiles uniformly before synthesis. Each uses the
same physical rules and all the necessity, branching and solver checks below.

| Profile | Independently checked claim |
| --- | --- |
| Switch first | The start switch is the unique best opening and beats a move with a committed successful continuation |
| Recharge first | The best opening moves to the charger; every shortest plan recharges before leaving it, possibly after using its switch |
| Remote switch first | The best opening visits a noncharger switch; every shortest plan uses that switch before recharging |
| Conserve energy | The best opening move uses less energy than a committed viable rival move that becomes optimal when energy is ignored |

The remote-switch profile is an ordering prerequisite, not a claim that the route is
longer than an alternative route. The conserve profile compares movement alternatives;
it does not claim the winning move costs less than a free start switch. Profiles can
overlap: conserve and recharge can both begin with a move to the charger. Validation
therefore reports physical opening roles and simple-policy outcomes separately.

Generation starts from a finite bank of feasible physical layouts. A bounded walk
changes route topology, costs, gate requirements, initial state and switch effects,
accepting an edit only when it retains the chosen profile and every existing quality
gate. The default budget is 48 candidate evaluations, including the foundation.
Room and gate relabeling happens separately and is excluded from diversity counts.
This extends a finite family; it does not generate arbitrary new mechanics.

The versioned strategy certificate re-explores the compiled complete graph with
forward BFS and checks action ordering in a product graph. It does not trust saved
answers, canonical witnesses or proposal diagnostics. A counterexample search rejects
an ordering claim if any violating plan is as short as the optimum. The ordinary
checker independently retains direct/core graph agreement, Z3 optimality and all four
mechanic interventions. Saved engine revisions 1–9 retain their previous replay paths;
state plans use the original generator at revision 7 and the investment generator at
revisions 8–9.

The creator keeps this activity in Experimental. Selected strategy details appear in
the proof and revealed explanation, without a profile selector or answer hint in the
unrevealed title or rules. [The work tracker](../creator-quality-work-tracker.md)
records current validation and sample evidence.

## Revision-10 validation

The final independent audit passes 150 unseen models (50 seeds per level), 36 creator
format items and 60 items in three count-20 batches. All 96 rendered answer surfaces
agree with the raw-domain oracle. Exact saved replay passes 1,719 prechange bundles
containing 1,839 items across engine revisions 1–9.

The unseen corpus contains 150 physical structures and 113 unlabeled route topologies:
15 easy, 48 medium and 50 hard. Actual openings are 78 charger moves, 45 other moves
and 27 start-switch actions. Identical raw seeds select identical profile draws across
levels; these are 150 models but 50 independent profile draws.

Two arbitrary visible cues found during review were countered with physical variation
and verified opposing examples. Predictive priors remain: the shortest raw route toward
the charger uniquely selects the answer in 100/150 unseen cases. Three of nine sampled
true/false claims name an initially unavailable action and can be rejected immediately.
Neither universal shortcut resistance nor equal reasoning demands across formats is
claimed.

[Full validation](../../artifacts/state-planning-variety/2026-10-13/validation.md),
[independent results and source hashes](../../artifacts/state-planning-variety/2026-10-13/independent-validation.md)
and [15 reviewable samples](../../artifacts/state-planning-variety/2026-10-13/sample-gallery.html)
record the exact denominators, runtimes, finite synthesis limits and separate 300-model
visible-cue review. The historical results below describe the revision-7 sampler.

## Original revision-7 proposal search

The original proposals vary the directed map, route costs and gate requirements, starting energy
and gate settings, charger position, and switch effects/costs. The sampler deliberately
focuses on reachable charging and initially unaffordable direct exits where present;
it does not sample every legal state machine uniformly or fix one solution template.
Search stops at the first model passing all gates, within 2,000 proposals. Accepted
plans need at least 4/5/6 actions by level and at most 12. Graph exploration fails closed
at its 512-state cap. The declared state dimensions themselves permit at most 432
states for the largest legal model.

The workshop includes this activity in engine revision 7. It accepts topic labels and
the four quiz answer formats, renders per-option feedback and a replayable witness,
and uses the existing bundle verification/save/share path. An exhausted proposal
search can be retried within the workshop's `count * 30` batch candidate limit.
`search_candidates_exhausted` records these attempts; a batch that cannot be filled
returns an error rather than a partial export. Other verification errors stop the
request. Saved engine revisions 1–6 retain their previous replay paths, including
the clue synthesis introduced in revision 6.

## What makes a choice count

An accepted model has exactly one optimal first action and at least two first actions
with successful **committed** continuations. At least one later state on the canonical
optimal witness also has two successful committed continuations. Every room must be
reachable in some legal state.

The committed comparison forbids returning to the decision room with the same gate
settings, no more energy, and no improvement in remaining recharge availability.
Consequently, walking out and back or wasting a recharge does not manufacture a second
strategy. A return with changed gates or a net energy gain can count, because it changes
the future possibilities. The alternate first action must take strictly more actions
than the unique optimum. Later successful branches may be tied or slower.

These gates establish meaningful alternatives within the explicit state model. They
do not require every instance to defeat a particular greedy heuristic, such as choosing
the cheapest initial energy cost, and do not establish that every branch is difficult
for a person. Only the **optimal first action** is unique; the full action sequence is
allowed to have multiple optima.

## Necessity and verification

Each accepted model is solved again under four separate interventions:

| Mechanic | Intervention |
| --- | --- |
| Energy | Ignore affordability and energy spending; retain the other rules |
| Gates | Ignore gate requirements on routes |
| Switches | Remove switch actions and preserve the initial gate settings |
| Recharge | Remove the recharge action |

For every intervention, the pair `(minimum action count, optimal first-action set)`
must change. Removal can make the goal unreachable. This measures necessity of each
mechanic category for the accepted optimum/answer, not necessity of every individual
route, switch or parameter, nor uniqueness of the ablation methodology.

The production certificate uses three computations:

1. A direct domain interpreter enumerates every reachable state and transition.
2. The model is separately compiled into the existing guarded-action core IR. Its
   independent interpreter must produce the same complete transition graph and goal
   set, both for the baseline and all four mechanic interventions. The chosen witness
   is replayed through that interpreter with exact intermediate-state comparison.
3. Z3 bounded model checking proves no shorter solution exists, a solution at the
   optimum exists, and no solution at that optimum begins with another action. Goal-only
   padding makes the shorter-horizon query cover every shorter length. Padding is not
   a playable action. Unknown solver results and exhausted work limits fail closed.

`tools/benchmark_state_planning.py` supplies another raw-domain implementation and a
forward BFS oracle. It does not call the production transition function, compiler or
solver to determine the expected result. It checks full graphs and goals against the
compiled core, audits both committed-choice requirements and all four interventions,
counts all shortest action sequences including paths merging into one state, and
repeats seeded generation plus certification. Oracle regression fixtures cover merged
paths, recharge persistence and undo-only alternatives. Any unexpected generation,
solver or audit failure aborts the benchmark; only `ProposalExhausted` is an expected
request rejection.

## Reproduce the original revision-7 fixed-seed audit

Run from the `engine` directory with the repository environment:

```powershell
./.venv/Scripts/python.exe -B tools/benchmark_state_planning.py --seeds 0,1,2,3,4,5,6,7,8,9 --levels 1,2,3 --out artifacts/state-planning/fixed-seeds-new.json
```

The tool refuses to overwrite evidence and rejects Python's assertion-disabling `-O`
mode. Reports contain raw models, independent solutions and ablations, exact structure
and route-topology fingerprints, proposal counts, SMT results, runtime versions and
source-file hashes. Generation, certification, independent audit and seeded replay have
separate measured durations. Changes to recorded source files during a run abort the report.

Full structural fingerprints ignore location labels, interior-room numbering and gate
names, while retaining costs and mechanics. Topology fingerprints additionally discard
all route costs, gate requirements, charging and switch information. The latter checks
whether diversity includes different maps rather than only renamed or repriced copies.

## Original revision-7 fixed-seed results

The [tracked 30-request results](state-planning-results.json) cover seeds 0–9 at each
level and include the full report's SHA-256. The complete local report remains at
`artifacts/state-planning/fixed-seeds-0-9-v1.json` from the `engine` directory; it contains
the raw models, certificates and witnesses. All 30 generated models passed every independent check
and exact seeded replay; no request exhausted its proposal budget. Source hashes stayed
unchanged throughout the run. Each of the four mechanic interventions changed the
optimal signature in **30/30** cases. Every case had committed initial and later choices.

| Level | Verified / requested | Proposals | Distinct structures | Distinct route topologies | Best action count | Median generation / certification |
| --- | --- | --- | --- | --- | --- | --- |
| Easy | 10 / 10 | 3,345 | 10 | 3 | 4–5 | 0.832 s / 0.767 s |
| Medium | 10 / 10 | 1,506 | 10 | 9 | 5–7 | 0.299 s / 0.896 s |
| Hard | 10 / 10 | 5,549 | 10 | 10 | 6–7 | 0.814 s / 1.008 s |
| Total | 30 / 30 | 10,400 | 30 | 22 | 4–7 | 0.521 s / 0.881 s |

The per-proposal acceptance rate was **0.2885%**: 10,370 proposals were rejected
(8,003 unsolved/outside length bounds, 944 choice/reachability failures, and 1,423
mechanic/shape failures). The largest successful search used 1,388 of its 2,000
proposals. Accepted models had 21–143 reachable states, and the best committed alternate
first action needed one or two additional actions. There were **18/30** models with
multiple complete optimal action sequences, all sharing their one optimal first action.

Across all 30 rows, generation plus certification had median **1.547 s** and nearest-rank
95th percentile **4.750 s**. The independent audit had median **0.094 s**, and generation
plus certification replay had median **1.485 s**. These measurements use Python 3.12
and Z3 4.13.4 on the local Windows environment. They exclude browser and batch retry
overhead. The ten easy cases shared only three route topologies, which is a concrete
remaining variety limit even though all their full mechanic structures differed.
Other validation work was running locally during measurement, so these timings also
include contention with those checks.

Removing energy changed the optimal first-action set in 27 cases; ignoring gates did
so in four. Both changed the optimum length in all 30. Removing switches made 29 goals
unreachable and changed the optimal signature in the remaining case. Removing recharge
made every goal unreachable. Thus all four categories affect the optimum; it would be
incorrect to claim that every category changes the identity of the best first move in
every puzzle.

For a concrete example, easy seed 0 starts at Depot with energy 2/6. Reaching Orchard
first gives a five-action solution: move to Orchard, recharge, flip its switch, return
to Depot with changed gates and more energy, then move to the goal Meadow. Starting
with Harbour or the Depot switch still permits a committed solution, but needs six
actions. Moving directly to Meadow is initially unaffordable. At Orchard, switching
before recharging also gives a five-action solution; this is why the first action is
unique while the full path is not. The raw model and both the exact costs and shortest
path count are saved in the full local report.

## Observed Studio integration limit

The local CLI automatically detects the optional sibling Studio verifier when it is
available. The new family passes the standalone engine and native field contract,
but its rules and full witness are longer than Studio's existing short-quiz editorial
limits. In the observed hard `space, ocean` sample at seed 7, the question contained
about 116 words against a 60-word limit, the complete trace exceeded the 1–2 sentence
explanation limit, and a topic label triggered a lexical giveaway check.

Studio's external rejection remains enforced; it was not weakened to accept this
family. Consequently these verified state-planning items are not yet Studio-ready
exports. Native local preview is available without that optional integration:

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom serve --no-integrations --no-history
```

This previews the engine's own creator/player and checks. It does not establish
acceptance by Studio or perform a live import or publication.

## Measurement limits

Fixed seeds measure acceptance, local throughput and diversity of this sampler on a
small corpus. They do not prove completeness, global puzzle quality, novelty beyond
the chosen fingerprints, or future request success. Exhausted proposal searches report
their full attempted budget; the current exception does not retain a per-reason rejection
breakdown for those searches, so the report explicitly records the unclassified count.
Proposal reasons on successful searches are complete: `unsolved` includes unmet length
bounds, `choice` includes branch/reachability failures, and `mechanics` includes sampler
shape rejections or failed necessity gates. These are sequential rejection categories.

Timing includes normal local runtime variation and has no hardware-independent or
human-difficulty meaning. Hidden information, delayed effects, arbitrary new mechanics,
and a player study remain outside this family.

## Original revision-7 completion checks

The focused runs passed 58 state-planning tests, 46 creator-integration tests and
64 answer-feedback tests (168 total). These cover independent transitions and goals,
shortest paths, mechanic interventions, bounded rejection/retry, solver disagreement,
all four answer formats, topic coverage, tampering and saved replay. Twenty assertions
from older tests that expected revision 6 as the current default were updated and their
focused reruns passed. Ruff passed for the source, tests and benchmark tool.

All six JavaScript suites passed (workspace, theme, library, sharing, flow and player).
Actual browser checks confirmed state-planning generation/coaching and the desktop
brief's automatic 60%/28% widths, manual dragging/keyboard control, stored preferences,
and mobile/Play-mode transitions.

The full repository run was stopped after confirming an unrelated existing failure:
`test_attribution_travels_with_the_data` requires a citation missing from the unchanged
`NOTICE` at Git HEAD. The unchanged presentation fixture also globs the ignored
`examples/workshop-handoff-bundles.json`, a BrainBloom bundle list rather than a core
puzzle object. Neither unrelated file was altered. A clean full-repository test run
is therefore not claimed.
