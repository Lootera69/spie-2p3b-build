# Engine capability and puzzle experience roadmap

Started 14 October 2026; updated 17 October 2026 (India). This is the active
development direction, following the user's reprioritization. The first milestone's
revision-11 implementation and local
engineering validation are complete; actual player evaluation remains pending.
[Validation and limits](../artifacts/engine-capability/2026-10-14/validation.md),
[20 paired examples](../artifacts/engine-capability/2026-10-14/sample-gallery.html) and
the [work tracker](creator-quality-work-tracker.md) preserve the evidence, including
completed revision-9 and revision-10 work.

Revision 12's local correctness and compatibility checks are also complete. Its
three authored scenarios reduce median introduction/objective length by 48.65%, and
controlled median generation time falls by 6.95%. The registered decision-sequence
diversity target was not met: 14 distinct canonical sequences before and after.
Physical structures remain at the sample ceiling of 20/20. This is a partial
improvement, not completion of the engine-quality vision. [Revision-12 validation](../artifacts/engine-capability-v12/2026-10-14/validation.md)
and [paired playable examples](../artifacts/engine-capability-v12/2026-10-14/sample-gallery.html)
preserve the result. Human feedback remains pending.

Revision 13's proposal engineering milestone now meets its registered structural
targets on a fresh 20-case comparison: complete canonical role sequences increase
from 11 to 16, label-invariant sequences from 12 to 16, and route topologies from
17 to 20. Physical structures remain 20/20. Eighteen final frontiers contain
multiple invariant roles, and mean traps and forced actions fall to zero. All 16
heldout cases pass. The frozen release also passes [2,408 creator tests](../artifacts/engine-capability-v13/2026-10-15/release/creator-final.json)
and [six browser checks](../artifacts/engine-capability-v13/2026-10-15/release/browser-final.json).
See the [revision-13 research note](research/planning-experience-v13.md) and
[final independent validation](../artifacts/engine-capability-v13/2026-10-15/independent-validation.md).

This completes the current proposal milestone, not the wider experience goal.
Meaningful-decision-only variety remains 14/20, and shortcut resistance does not
improve: predefined shallow policies solve more candidate puzzles. Human participant
count is zero. The user-requested [assistant play review](../artifacts/engine-capability-v13/2026-10-15/release/assistant-play-review.md)
is complete as separate editorial evidence with prior source knowledge. All three
revision-13 UI episodes finished, including charger hints, undo, dead-end recovery
and zero-energy success. Final hint-amendment checks pass: 155 focused tests,
56-model replay and the final DOM retry, separate from the original full suite.
All 18 registered engineering gates pass. Controlled generation is substantially
slower: median 0.167s → 0.274s (+64.2%). The [performance review](../artifacts/engine-capability-v13/2026-10-15/release/performance-review.md)
attributes added cost to more distinct candidate and graph/quality evaluations.
Speed improvement was not mandatory; the frozen implementation retains this
tradeoff. The revision-13 handoff is complete. Human enjoyment, broader meaningful
variety, shortcut resistance and further performance work remain future roadmap
goals, without blocking the assistant self-review requested by the user.

Revision 15 repairs new-batch playback and Studio editorial compatibility while
reducing warmed generation time by 20.99%. All 44 fresh cases, 86 format/batch
items, 2,720 historical replay outcomes and 386 raw model records pass. The source
is still Experimental: meaningful-only roles remain 15 against target 17, while
dependency signatures and physical structures are retained. The source was not
retuned against those outcomes. Human evaluation remains pending. See the
[revision 15 repair record](../artifacts/engine-capability-v15/2026-10-17/release/completion.md).

Revision 14's interrupted implementation and evaluation are now complete, with
release acceptance failed on five of 27 gates. It improves bounded-policy planning
depth and keeps correctness and old replay, but meaningful-only variety falls16
to 14, dependency signatures18 to 15 and structures20 to 19. Warmed generation is
12.44% slower, and medium/hard 20-item bundles exceed the saved-request size cap.
All 2,488 creator tests and the six DOM/API checks pass; assistant play completes
all three difficulties. See the [revision 14 completion record](../artifacts/engine-capability-v14/2026-10-15/release/completion.md).
The candidate remains local and Experimental. Prioritize compact replay transport,
less concentrated decision selection and profiling in the next iteration, using
new registered cases. Do not reinterpret this attempt as a full quality gain.

## Product goal and audience

Build an engine that designs puzzles worth thinking through and experiences players
want to finish. Priorities are stronger reasoning, higher puzzle quality, meaningful
interaction, humor and emotional context. Activity count and interface breadth are
not success measures.

The user selected both a broad teen/adult audience and more demanding adult puzzles.
The default tone should be approachable, warm and intelligent, with sharper or dry
humor where the situation supports it. Challenge should come from connected reasoning
and consequential decisions. Emotional stakes can involve trust, pride, belonging,
keeping a promise or helping someone; sadness is not required. Different puzzles may
emphasize these qualities differently rather than forcing a joke into every scene.

Work remains local. Preserve the current non-LLM runtime and replay of saved engine
revisions 1–14. New local review requests use candidate revision 15, and future generator behavior
must also use an explicit version. No commit, push or deployment is authorized.

## What the engine needs to improve

| Capability | Development requirement | Evidence of improvement |
| --- | --- | --- |
| Reasoning and invention | Design interacting rules, viable alternatives and consequences that require planning or combining evidence; compare and revise candidates | Replayed causal/dependency traces, independent counterfactual checks and better results against predefined shortcut policies |
| Puzzle judgment | Evaluate the task as actually presented, including choices, hints, text and intermediate decisions | Fewer easy shortcuts and redundant steps on held-out cases, with clarity and compactness retained |
| Interactive reasoning | Make the formal state respond to player actions; support testing a hypothesis, observing consequences and reconsidering a plan | Every action and feedback message agrees with the interpreter; later decisions remain meaningful |
| Humor and emotional context | Represent characters, goals, relationships, comic premises and resolutions together with puzzle events | Consistent scenario bindings, no invented causal rules in prose, and human review of tone, coherence and payoff |
| Meaningful variety | Vary dependencies, strategies, consequences and scenario structure | Diversity after removing names and stylistic wording; held-out mechanism/scenario combinations as well as unseen seeds |

“Thinking capacity” here means stronger bounded representation, synthesis, planning,
self-critique and revision. A larger search budget, more clues, a longer optimal path
or a harder solver problem alone does not establish a better player experience.

## Baseline findings before revision 11

- BrainBloom has a strong correctness foundation: independent answer checks,
  displayed-task clue support, committed planning alternatives, mechanic interventions
  and reproducible saved bundles.
- Candidate selection still uses narrow structural objectives. For example,
  [reasoning](../src/spie/questions/brainbloom/reasoning.py) and
  [Autopilot](../src/spie/questions/brainbloom/autopilot.py) rank combinations of
  support, clue kinds and other family-specific proxies. These do not measure enjoyment.
- [State planning](../src/spie/questions/brainbloom/state_planning.py) already bridges
  physical transitions into core IR and checks full plans. Its current presentation asks
  for the first action; its three hints are general rather than tailored to a played state.
- [Revision-10 synthesis](../src/spie/questions/brainbloom/state_planning_variety.py)
  improves opening variety using finite physical foundations and bounded edits. It does
  not invent arbitrary mechanics. Its valid-edit walk returns the last accepted layout;
  it does not rank whether each edit improves the reasoning experience. The release
  audit still finds useful shortcut priors.
- The existing player supports answer checking, grid work, hints and save/reload.
  [Feedback](../src/spie/questions/brainbloom/feedback.py) generally grades an answer;
  it is not a general action-by-action scenario runtime.
- Core [IR](../src/spie/ir.py), [strategy evaluation](../src/spie/strategy.py),
  [quality descriptors](../src/spie/quality.py) and [MAP-Elites](../src/spie/mapelites.py)
  provide reusable research infrastructure. Their capabilities are not all connected
  to live workshop generation. Model-based surprise is not proof of human delight.
  Core [augmentation](../src/spie/augment.py) already compiles delayed and remembered
  observations; using these in coherent workshop play still needs integration and
  bounded state-space evaluation. The first slice stays fully observable.

## Completed first engineering milestone: a playable planning scenario

The revision-11 engineering stage below is implemented and locally verified. Its 20-case
comparison meets the predefined structural decision targets, while reporting greater
reading burden and slightly lower structural diversity. Human-experience acceptance
is still pending; the scenario remains Experimental. See the
[implementation contract](research/planning-experience.md) for the actual scope.

Deepen the existing energy-and-switch planning activity into a playable episode.
Keep its current mechanical rules and independent solvers while improving how designs
are selected, how their consequences can be explored and why the player cares.
Do not create another activity-menu entry for this work.

1. **Establish the quality baseline.** Freeze current puzzles and record complete
   decision traces, competing continuations, shortcut-policy results, hint behavior,
   narrative limits and generation time. Define the candidate comparisons and held-out
   sets before tuning the generator.
2. **Build a shared quality evaluation loop.** Propose a situation, solve it, simulate
   several bounded player policies, identify shallow decisions or repetitive structure,
   revise the situation and compare candidates. Retain explicit evidence and rejection
   reasons. Keep correctness gates mandatory, and keep quality dimensions separate
   until a combined ranking is justified by evidence. Do not reward confusion or traps
   just because they defeat a simple policy.
3. **Bind a scenario to the same formal model.** Give entities stable roles and authored
   attributes; bind the goal, routes, resources, actions and consequences to scene facts.
   Define what each character wants, why the outcome matters and what constitutes the
   resolution. Distinguish mechanical facts from expressive dialogue. Use deterministic,
   authored language rules initially; text must not silently introduce deadlines,
   costs, knowledge, motives-as-evidence or other unstated mechanics.
4. **Expose the reasoning process through play.** The engine supplies the legal actions,
   current public state, action consequences and goal status. A replayed action history
   determines progress. Let players explore a plan and recognize why an alternative
   fails or costs more. Any view code serves those engine capabilities. Existing quiz
   exports and their certificates remain distinct from the richer played experience.
   Accept all legal successful continuations, including later optimal ties. A slower
   successful route must not produce a fictional disaster merely because it is slower.
5. **Ground help in the player's state.** Generate a ladder from a useful observation,
   to a relevant connection, to an explained next step. Bind each hint and feedback
   claim to supporting facts and the selected action. Early help should preserve the
   opportunity to reason, and should not simply print the best remaining plan length.
6. **Compare quality, then iterate.** Produce 20 candidate episodes alongside matched
   baseline examples. Review complete play, not just screenshots of the question. Test
   unseen seeds and held-out structural/scenario combinations. Preserve the best
   supported mechanisms; revise weak ones before expanding into other puzzle families.

### Illustrative creative direction

An anxious station robot is carrying a farewell recording for the retiring caretaker
who repaired it for years. Its announcements have the pompous confidence of a railway
official, even when asking where its own charging socket is. The player must plan its
route through the existing power and gate constraints to reach the farewell hall.

The relationship supplies a reason to finish; character voice supplies situational
humor; the route decisions remain explicit and fair. The ending acknowledges events
that actually occurred in the replay. Revision 11 implements this authored premise
with three voice variants and verifies its mechanical bindings. Humor and emotional
payoff remain design intentions awaiting player feedback. There is no hidden time
limit or new inventory mechanic.

## Completion criteria

| Area | Required check |
| --- | --- |
| Correctness and compatibility | Preserve independent solver/interpreter agreement and all existing planning gates; current revision 13 must replay saved revisions 1–12 |
| Complete interaction | Execute legal, illegal, suboptimal and successful traces; reject altered histories; displayed state and consequences must match replay |
| Decision quality | At least two causally connected decision points with viable alternatives; compare whole episodes against predefined short-horizon and simple-policy baselines; report ties, failures and residual cues |
| Story consistency | Mechanically relevant statements bind to model facts; characters and references stay consistent; resolution is justified by the played outcome; check that titles, humor and wording do not leak the answer |
| Helpful hints | Each hint has a valid dependency trace from available facts; early hints do not name the winning action or expose unrevealed information |
| Variety and efficiency | Inspect 20 complete episodes; count distinct structures and consequential decision sequences; report fixed-budget acceptance, failures and latency |
| Human experience | Obtain paired play feedback on clarity, insight, agency, humor, emotional interest, frustration and desire to play another; report audience and raw results |

Define numerical improvement targets after recording the baseline and before tuning.
Record text length and reading burden as well as solver metrics. A passing
solver check cannot certify that a puzzle is funny, emotionally engaging or enjoyable.
Until real play feedback is collected, label those qualities as design intentions and
editor judgments. Keep human validation visibly pending rather than substituting
synthetic telemetry or self-assigned “fun” scores.

## Following engine work

Revision 13 addresses the revision-12 proposal bottleneck through a finite bank of
257 physical foundations, role-balanced edits and a static prior that reduces
overrepresented role sequences across level/profile groups. It retains the
48-candidate request budget, independent causal guarantees and existing quality
bounds. Offline mining is separate from that request budget. The exposed
revision-12 failed-improvement record and the fresh revision-13 comparison remain
frozen evidence.

Next, improve variety in consequential decisions and investigate the remaining
shortcut policies. More complete route sequences alone do not satisfy those goals.
The hard remote-switch profile still has one retained foundation role family;
known development alternatives add traps or forced steps, so broader support needs
better physical dependencies rather than looser quality limits. Preserve the current
gates, register fresh comparisons before a future revision, and gather real paired
play feedback alongside this work. Assistant self-review can find interface and
wording defects, but cannot establish participant enjoyment or emotional impact.

Once the first scenario demonstrates improvement, apply the quality evaluation and
scenario contracts to deduction and evidence puzzles. Expand the bounded composition
grammar only where it creates useful new reasoning. Integrate hidden-information
episodes only with explicit observation semantics and knowledge-scoped proofs.

Learned ranking or proposal guidance can follow actual preference data and held-out
evaluation; it is not a prerequisite for this milestone. Preserve independent answer
checks regardless of how candidates are proposed or ranked.

The earlier delivery, question-planning and number-rule issues remain regression cases
for this engine work. Their repair is subordinate to the capability roadmap rather
than a queue of separate new functions. Number-rule true/false remains unavailable for
new requests until its quality problem is solved. Cosmetic expansion, more menus and
larger nominal difficulty settings are deferred.
