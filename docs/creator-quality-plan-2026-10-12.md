# BrainBloom creator quality audit and improvement plan

Date: 12 October 2026 (India). Audited engine revision: `3901bc7d7995c4a2d61fd2b98865a2faaed8c67c`.

Status: audit and plan only. No production behavior, deployment, or remote repository was changed. Recommendations below are proposed work, not completed fixes.

Implementation subsequently started at the user's request. Current progress and validation are recorded in the [work tracker](creator-quality-work-tracker.md); the audit findings below remain the pre-change baseline.

## Decision

Reduce the main creator menu and invest in a few puzzle types that require meaningful inference. The current engine is much better at proving its chosen answer than ensuring the player needs to reason to find it. Making the numbers larger, adding more rows, changing topic words, or selecting a more expensive solver will not fix that gap.

The user's concern about **Plan the best next move** is supported. It is a small shortest-route calculation dressed in topic words. In the nine sampled multiple-choice questions, going directly to the destination wins seven times, including all three hard samples. Medium/hard reject the cheapest-first-leg answer, but that alone does not establish a worthwhile planning problem.

Recommended initial main menu, after the Phase 1 answer-option repairs:

1. **Solve a set of clues** — consolidate built-in ordering and rule deduction here, after checking the actual answer options.
2. **Design a clue puzzle for me** — retain generated multi-group puzzles, with stronger checks on what the player actually sees.
3. **Create a custom logic grid** — retain explicit authoring and verification; improve author guidance.
4. **Connect words in a crossword** — retain as a separate word-puzzle format, with better clue and grid standards.

Keep resource and state planning in an explicitly experimental area until their decision structure improves. Merge duplicated activities. Move drills and unscored explorations into clearly named optional areas. Hide weak activities from automatic selection and the main menu first; preserve saved-bundle replay and old activity IDs during migration.

## What was tested

The audit exercised the same local creator path as the application: `Brief → prepare → Generator.build`, using WordNet 3.0 plus the shipped coverage packs, with OEWN, persistent history and Studio disabled. This matches the deployment's intended dictionary configuration; the live service was not load-tested.

| Sample | Coverage | Result |
| --- | --- | --- |
| Resumed corpus, 11 October | 31 activities × 3 nominal levels × seeds 7, 23, 91 in the first supported format, plus every alternate format at hard/7 | 346/346 accepted; 346 generated items |
| Format expansion, 12 October | Every supported activity/format pair at easy and medium, seed 7 | 196/196 accepted; 196 generated items |
| Combined single-item coverage | Union of the above, counting repeated configurations once | 480 distinct activity/level/seed/format cells; all 98 supported activity/format pairs exercised at every nominal level |
| Batch/topic check | All 31 activities, hard/7, first format, count 3; topic activities use animals/plants | 30 complete batches, 90 items; custom grid correctly refuses count 3 because the shipped example supports at most 2 |

The first two datasets overlap in 62 cases; do not report 542 unique configurations. The batch/topic run changes both topic and batch size, so it is a robustness check, not a controlled comparison of topic effects.

The custom-grid example determines its own hard difficulty, regardless of the selector. Word Wonder resolves to medium and has no difficulty control. Nominal level coverage therefore does not imply three actual difficulty levels for those activities. All successful generation results remain unpublished drafts.

Validation completed: **901 existing tests passed** (358.43 seconds). Independent replay passed **572/572 accepted bundles, containing 632/632 items**, across the three corpora; the grid count-limit refusal is separate. The original 346-bundle corpus and both fresh datasets are included in that total.

An additional **11/11 creator-flow checks passed**: five default category routes, four supported written instructions (including the apply-settings step), and two unsupported instructions correctly stopped for clarification. The nine successful flows produced 11 items and replayed successfully; these are separate from the corpus totals. Under the sampled defaults, logic/riddles/science selected deduction, and puzzles/wonders selected question planning.

Supporting records are linked at the end of this plan. Acceptance and replay establish the implementation's formal contracts; they are not evidence of enjoyment, educational effectiveness, or human-rated difficulty.

## Concrete quality failures

All fractions below describe the nine sampled multiple-choice cases per named activity, unless otherwise stated. These are reproducible examples, not estimated population rates.

| Finding | Evidence | Implication |
| --- | --- | --- |
| Impossible clue can be found by copying comparison | 9/9: the answer is the only choice not copied verbatim from the base clues | Deduction can be skipped entirely; rebuild the distractors before prominently offering this activity |
| Shortest-route planning favors the destination itself | Direct-to-goal wins 7/9; hard 3/3 | A cheapest-first rejection gate misses other simple policies and repeated graph structure |
| Number-rule discovery needs just one observation | 9/9 have some single row that uniquely identifies the rule; first row suffices in 7/9 | Four to six examples and harder arithmetic do not create evidence combination |
| Hidden-number choices bypass most clues | 9/9 solved by one displayed clue when restricted to the offered choices | Full-domain uniqueness is insufficient; evaluate clue support after rendering choices |
| Position choices can be impossible on their face | 3/9 have only one choice within the legal range | In hard/7, six people have options 12, 5, 8, 11; only 5 is a position |
| Core grids also pad the choices | All 18 sampled Autopilot/custom-grid MCQs include “None of these” while the other three choices exhaust the legal values or positions | Permit three choices or grid entry; a fourth impossible choice adds no challenge |
| Word length reveals the answer | Anagram 3/9 and missing-letters 3/9: just one matching-length word in the entire bank; reversal 5/9: just one matching-length option | Letter and meaning clues are avoidable in these cases |
| Delivery optimization is offered as feasibility elimination | 9/9 show only one feasible option; each distractor violates a constraint | The player need not compare speeds of two feasible plans, despite “fastest” wording |
| Energy planning has a narrow recurring opening | All 9 have two viable first choices; 7/9 answer “go to the charger”; all use the same energy-investment strategy | Preserve the solver but diversify the strategic situations and check action-level biases |
| Choosing a question often reduces to balancing a split | Closest-to-half prior-mass split uniquely wins 7/9 and includes the winner in 9/9 | The optimal decision-tree proof may describe more reasoning than the first decision requires |
| Probability activities duplicate the same mechanic | `bayesian` and `most-likely` share the hidden-card/noisy-evidence implementation | Combine them; two menu labels do not represent two substantial capabilities |
| Bigger questions can leave the reasoning unchanged | Hard sequences announce both operations; motion constructs equal speeds on the two legs; four rulebooks use the same linear implication chain | Extra text, units and reskinning inflate the menu and difficulty labels |

Examples to inspect first, under `artifacts/quality-audit/2026-10-11/cases/`:

- `contradiction__hard__7__multiple-choice.json`: compare the choices with the base-clue text.
- `best-move__hard__7__multiple-choice.json`: the direct destination is the optimal first stop.
- `pattern__hard__7__multiple-choice.json`: proof records one supporting example despite six displayed rows.
- `ordering__hard__7__multiple-choice.json`: illegal numeric distractors.
- `number-riddles__medium__23__multiple-choice.json`: the range 9–79 alone excludes 83, 80 and 81, leaving 79.
- `anagram__hard__7__multiple-choice.json` and `missing-letters__hard__7__multiple-choice.json`: TELESCOPE is the sole nine-letter bank word.
- `resource-plan__hard__7__multiple-choice.json`: distinguish global optimality from the feasibility-only comparison offered to the player.

There are useful foundations. Deduction combines multiple constraints, Autopilot and current custom grids already certify target and true/false support as well as a complete arrangement, planning engines independently replay state transitions, and crosswords genuinely connect words. Preserve these mechanisms. Even here, assess the presented task: in two hard deduction samples, choices reduced required supporting clues from five to four. The hard/7 true/false claim needs only three clues even though its underlying question needs five. Deduction's wrapper lacks the displayed-claim recertification already present in the grid families.

## Disposition of every activity

“Hide” means remove from the main creator menu and automatic recommendations until its stated condition is met. It does not mean delete the verifier or make old drafts unreadable. These are product recommendations, not changes applied by this audit.

| Activity ID and current label | Decision | Required change or rationale |
| --- | --- | --- |
| `autopilot` — Design a clue puzzle for me | Keep in core; strengthen | Preserve existing target/claim support certificates; remove impossible fourth-choice padding; vary relations and group structure; improve coherent scenarios |
| `deduction` — Solve a set of clues | Keep in core; strengthen | Check support after choices; absorb basic ordering and conditional deduction without proliferating menu entries |
| `logic-grid` — Create a custom logic grid | Keep in core | Keep contradiction/ambiguity and target-support checks; permit three choices or grid entry; explain fixture-dependent difficulty and batch capacity |
| `crossword` — Connect words in a crossword | Keep in word-puzzle track | Better clue quality, crossings and answer ambiguity checks; distinguish vocabulary challenge from deduction |
| `contradiction` — Find the impossible clue | Hide pending repair; later clue-puzzle mode | Generate equally plausible new statements, each requiring inference; prevent “not copied” detection |
| `best-move` — Plan the best next move | Remove from core; optional route practice | Do not spend effort making this weighted graph longer; route practice can retain accurate labeling |
| `resource-plan` — Plan a delivery with limited resources | Experimental; improve | Either explicitly ask which plan is feasible, or provide at least two feasible plans and a genuine optimality comparison |
| `state-planning` — Plan with energy and switches | Experimental; priority investment | Vary meaningful opening actions, dependencies and gate effects; prevent charger/switch/cost heuristics from dominating |
| `planning` — Choose the best next question | Experimental; improve | Construct cases where future questions, unequal question costs or constraints change the best first question; retain independent strategy proof |
| `bayesian` — Weigh the evidence | Merge; rebuild one evidence activity | Same core as most-likely; retain explicit finite hypotheses, honest priors and noise assumptions |
| `most-likely` — Choose the most likely explanation | Merge into evidence activity | Prefer evidence that changes competing hypotheses across steps; arbitrary card names do not provide narrative meaning |
| `pattern` — Discover a number rule | Hide pending rebuild | Require several observations to discriminate the stated hypothesis set; reduce arithmetic burden; do not claim unrestricted unique rules |
| `anagram` — Unscramble a word | Move to word practice; fix choices | Match candidate lengths and letter plausibility; a bank should not disclose the answer mechanically |
| `missing-letters` — Find the missing letters | Merge into word practice; fix choices | Match visible-letter masks and length; tune clue directness separately |
| `word-order` — Put words in order | Remove from core; optional practice | Alphabetical sorting is an explicit skill drill; longer lists do not create a new reasoning mechanism |
| `word-wonder` — Explore patterns in words | Keep only in unscored Explore | Label as an exploration; no puzzle-quality or difficulty claim |
| `arithmetic` — Solve an everyday number problem | Move to number practice | Useful calculation exercise; retain when deliberately requested, outside invention claims |
| `sequences` — Find the next number | Remove from core; optional practice | Stated operation plus next term is rule application; a discovery version needs a bounded, discriminating rule set |
| `number-riddles` — Guess the hidden number | Hide MCQ pending repair; later clue mode | All sampled MCQs are single-clue-solvable; support must be measured against offered alternatives |
| `ordering` — Work out positions | Merge into deduction after repair | Distractors must be legal positions; eliminate direct chains or targets answerable by one copied relation |
| `word-riddles` — Reverse a word | Remove from core; optional practice | Small fixed reversal bank and length clues are not substantial riddle invention |
| `motion` — Calculate speed and journeys | Move to science practice | Use unequal leg speeds when testing combined journeys; prevent redundant stages |
| `circuits` — Solve a simple circuit | Move to science practice | Stated formulas and substituted values are calculation; a later puzzle could reason about a missing circuit state |
| `density` — Calculate mass and volume | Move to science practice | Same treatment as motion/circuits; unit conversion alone should not imply hard reasoning |
| `growth` — Explore how doubling works | Keep only in unscored Explore | Explanatory thought experiment; do not count as a scored puzzle family |
| `probability` — Explore shared birthdays | Keep only in unscored Explore | Demonstration with explicit model assumptions; distinguish from evidence inference |
| `pigeonhole` — Explore when a match is certain | Keep only in unscored Explore | Useful counting explanation; not a scored activity as currently shipped |
| `warehouse` — Follow rules about parcels | Merge into one rule-deduction mode | Same template as the other three rulebooks; add branching and alternative explanations |
| `library` — Follow rules about books | Merge into rule deduction | Theme can be a scenario choice, not a separate reasoning capability |
| `laboratory` — Follow rules about samples | Merge into rule deduction | Require interacting relevant rules; remove disconnected padding |
| `delivery` — Follow delivery rules | Merge into rule deduction | Preserve necessary-rule checks; make clear this is distinct from route/resource planning |

The two additional selector actions are routing controls: **Choose for me** selects an existing activity, and **Describe it in my own words** uses a bounded phrase grammar. Neither invents a new semantic domain. Automatic selection must honor the same quality policy; custom instructions must not reactivate hidden activities silently or pretend unsupported rules were understood.

## A better definition of quality

Use separate dimensions with explicit failure reasons, not one invented “intelligence” score:

1. **Correctness:** the displayed facts entail exactly the intended answer in the declared model; independent replay agrees. Preserve current proof checks.
2. **Necessary reasoning:** the rendered question and answer format require the claimed combination of clues or decisions. Analyze the player's actual candidate set, not only the hidden complete solution.
3. **Resistance to shortcuts:** test copying, valid range, word length, visible letters, direct facts, answer position, cheapest first leg, direct destination, charger first, earliest deadline, highest prior, one readout, and most balanced split where applicable.
4. **Decision substance:** plausible alternatives survive initial inspection and fail for different meaningful reasons. For optimization, compare multiple feasible candidates. For deduction, avoid merely reading the only legal option.
5. **Meaning and clarity:** the setting makes the goal and rules understandable. Topic words should participate in relevant relationships if semantic relevance is promised. An abstract card puzzle is fine when presented honestly as abstract.
6. **Variety:** track changes in constraint structure, causal dependencies and solution strategy after normalizing names, clue order and choice order. Compare numeric parameters by their effects on rankings, feasible paths and strategy; do not erase consequential number changes. Surface fingerprints alone are insufficient.
7. **Human experience:** test whether target players understand the problem, can explain their solution, find the distractors plausible, and want another. Formal solver effort is not a proxy for enjoyment or human difficulty.

Do not ban accessible puzzles. Easy should teach one meaningful relation; medium should combine information; hard should introduce a qualitatively harder dependency or decision. Increasing the reading burden, number of names or size of coefficients should not be the sole difficulty progression.

## Implementation sequence

### Phase 1 — Contain misleading choices and repair visible shortcuts

Deliver a short main menu, an explicit practice area, and an experimental area. Add a central activity-status/quality policy used by menu availability, `auto`, natural-language aliases and generation validation. Preserve saved requests and proof replay separately from eligibility for new generation.

Repair copied contradiction choices, illegal position options, single-clue number distractors, and unique-length word answers before promoting those modes. Remove “None of these” padding when the other three choices exhaust the domain; permit three choices or a grid interaction instead of forcing four. Every distractor should survive cheap domain checks and correspond to a documented plausible mistake. Reject or regenerate failures with a bounded attempt budget; return an honest unavailable/partial result when the quality gate cannot be met.

Likely files: `brief.py`, `catalog.py`, `instructions.py`, `static/app.js`, `static/index.html`, `contradiction.py`, `families.py`, `logic_grid.py`, `word_puzzles.py`, `workshop.py` and their existing tests.

Acceptance:

- Main menu and automatic selection follow the same policy in all categories and answer formats.
- Existing example shortcuts become saved regressions; no accepted release sample is solved solely by those unintended cues.
- Alternatives stay in the legal answer domain; copied-clue and sole-length/range detection fails to identify a unique answer.
- Old bundle verification still passes. Removing a menu entry must not rewrite or invalidate previously exported puzzles.
- No production rollout until the revised samples can be reviewed locally. This plan does not authorize a push.

### Phase 2 — Measure the task after rendering

Keep formal validity separate from a new, versioned quality record. Proposed fields: activity/mechanism version, requested and effective difficulty, support against offered candidates, useful alternatives, failed heuristic policies, constraint ablations, structural family and rejection reasons.

For MCQ, compute minimum sufficient support over the answer options. For true/false, recompute for the displayed proposition. For typed answers, use the stated answer domain. A riddle wrapper must not inherit an MCQ difficulty claim blindly. For full grids, distinguish uniqueness of the arrangement from the difficulty of the asked target.

For patterns, reject medium/hard cases where one observation identifies the winner. Provisional targets: at least two jointly necessary observations for medium and three for hard, provided they fit the declared hypothesis family. Build overlapping candidate rules deliberately; random larger polynomials are not enough. Validate these thresholds with player trials rather than treating them as universal difficulty laws.

For planning, compare simple policies with the optimal result and record why they fail. Across a fixed, stratified seed sample, report opening-action and strategy distributions. Do not claim diversity from shuffled labels or answer letters. Ensure any acceptance thresholds are feasible for the small model and do not merely create long calculations.

Acceptance: proof and quality records agree with the exported prompt/options; sample failures name the violated criterion; no silent fallback to a lower-quality family; replay validates the relevant version without trusting an unverified score.

### Phase 3 — Make a few richer puzzle mechanisms

Prioritize state planning and clue puzzles. Give each an explicit goal, a compact set of interacting rules, and a solution that changes when a consequential rule is removed.

- **State planning:** generate varied small state graphs where an action can unlock a gate, consume a nonrenewable resource, enable a later tool or invalidate a later path. Include different strategies: acquire a prerequisite, change a switch, conserve a resource, take a detour, or act immediately. Require multiple legal and goal-reachable first actions where the task claims a strategic choice. Revision eight structurally excludes the initial switch from winning: its cost is 0/1, movement costs at least 1, and the selected strategy requires the winner to cost more than the cheapest legal first action. Revise that strategy gate deliberately; shuffling seeds cannot fix it. Do not always make charging the opening answer.
- **Resource planning:** retain fuel, deadline and prerequisite replay. If asking for fastest, show at least two feasible alternatives, one uniquely optimal and another attractive but slower. Include infeasible alternatives that fail distinct constraints. With four options, one winner plus one feasible competitor leaves room for two traps; rotate constraint types instead of demanding three separate traps in every question. If the intended skill is feasibility, ask that honestly and avoid a redundant optimization objective.
- **Information gathering:** create cases where future distinguishability, question costs or question availability alter the best first query. A balanced split can remain a useful easy lesson; harder cases should require more than applying it.
- **Clue puzzles:** generate branching, interacting constraints rather than longer linear chains. Choose a target only after measuring its support in the rendered format. Test all contradiction options under the same evidence.
- **Evidence:** merge the duplicate modes. Use coherent finite hypotheses and evidence that meaningfully changes the ranking. Check prior-only, last-readout-only and single-evidence policies. Explain modeled assumptions; arbitrary likelihood tables do not establish real-world causal knowledge.

Build one strong representative of each priority mechanism before expanding templates or adding options. Preserve bounded deterministic generation and independent checking; a language model is not required to fix these failures.

### Phase 4 — Add coherent scenarios and prove variety

Create a small authored scenario library with roles and constraints: for example, a field team must activate power before collecting a temperature-sensitive sample and reach storage before a deadline. Tie words to roles and legal actions. The important improvement is the dependency structure, not the story length.

Generate and inspect batches of 20 per retained activity. Compare normalized rule graphs, dependency patterns and successful strategies; record repeated structures even when wording is different. Exercise alternative topic sets, custom grids, count limits and answer formats. Keep arithmetic scale small enough to expose the intended decision.

Avoid claiming semantic understanding from dictionary membership. If creators supply arbitrary topics the engine cannot relate meaningfully, offer an honest abstract-label mode or explain the available scenario constraints.

### Phase 5 — Calibrate and release only the activities that earn it

Run the original audit cases as regressions, then at least 50 unseen seeds per real difficulty of each retained or rebuilt family. Extend to all supported formats and multiple topic pools; record unavailable cases and generation attempts as well as accepted ones. Use an explicit time/attempt budget on deployment-equivalent hardware before claiming performance improvements.

Conduct a small initial player study across the intended audience, with separate easy/medium/hard samples. Collect completion, hints, solve explanation, discovered shortcuts, perceived fairness and desire to play another. Treat initial findings as formative; choose sample size and any numerical success targets before a broader evaluation. No such study has been performed by this audit.

Release only when:

- Formal generation and replay checks pass, including old bundles.
- Known unintentional shortcut regressions are eliminated in the declared test set.
- The claimed reasoning or planning criteria hold on rendered questions.
- New seeds provide different structural situations, with disclosed limits.
- Difficulty and readability are supported by player observations rather than solver runtime alone.
- The creator receives truthful labels and clear explanations when no suitable puzzle is available.

## Evidence and reproduction

Saved locally:

- [Original corpus manifest](../artifacts/quality-audit/2026-10-11/manifest.json) and its `cases/` directory: original 346 requests, prompts, choices, answers and proofs.
- [Reasoning/planning review](../artifacts/quality-audit/2026-10-12/reasoning-review.md): source-level mechanisms and measured shortcuts.
- [Other-activity review](../artifacts/quality-audit/2026-10-12/other-review.md): all other 20 activities, examples and recommended gates.
- [Validation report](../artifacts/quality-audit/2026-10-12/validation.md): existing test results and independent replay counts.
- [Format expansion](../artifacts/quality-audit/2026-10-12/format-expansion/manifest.json) and [batch/topic sample](../artifacts/quality-audit/2026-10-12/batch-topic/manifest.json): fresh manifests and full cases.
- [Creator flow checks](../artifacts/quality-audit/2026-10-12/creator-flows.json): automatic routing and supported/unsupported written instructions.
- [Audit runner](../tools/audit_creator_quality.py): resumable local sampling; does not publish or write engine configuration.

Run from the `engine` directory using its installed virtual environment. Use a **new output directory** after changing source, runner, dictionary, subject or count. The saved run directories contain the exact runner snapshot matching their recorded hash; later formatting-only edits to the main runner may change its hash.

```powershell
.\.venv\Scripts\python.exe -B tools\audit_creator_quality.py --out artifacts\quality-audit\rerun-base
.\.venv\Scripts\python.exe -B tools\audit_creator_quality.py --out artifacts\quality-audit\rerun-base --levels hard --seeds 7 --all-formats
.\.venv\Scripts\python.exe -B tools\audit_creator_quality.py --out artifacts\quality-audit\rerun-formats --levels easy,medium --seeds 7 --all-formats
.\.venv\Scripts\python.exe -B tools\audit_creator_quality.py --out artifacts\quality-audit\rerun-batches --levels hard --seeds 7 --count 3 --subject 'animals, plants'
```

Inspect per-case status rather than assuming a successful command exit means all requested cases were accepted. The runner retains errors/unavailable/partial results and resumes by skipping existing case files. Use a fresh directory to retry an old case. The original manifest predates source hashes and invocation logs; independent replay was used to validate that corpus.

Limitations: selected seeds are a small coverage sample; alternate formats beyond seed 7 remain unsampled; authored custom-grid coverage uses the shipped example; topic/batch checks are narrow; session history, live browser behavior, production latency and long-term novelty were not evaluated. This is an agent-led content and source audit, not an independent human review.

## Work boundary

This request produces the audit, supporting local samples and the implementation plan. It does not implement the proposed menu changes or quality gates. The only code changed for this work is the local audit tooling. The pre-existing deletion of `requirements-build.txt` was left untouched. Nothing was committed, pushed or deployed.
