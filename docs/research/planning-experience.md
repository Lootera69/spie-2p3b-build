# Revision 11: complete planning episodes

This document preserves the revision-11 contract. Current development is described in
[Revision 12: varied plans with bounded quality tradeoffs](planning-experience-v12.md).

14 October 2026. The existing **Plan with energy and switches** activity now selects
designs using complete-episode evidence and supports playing the entire plan. It
remains Experimental, fully observable and non-LLM. No new activity is added.

## Candidate comparison

`planning_experience.propose` selects one of the existing four profiles uniformly
before search. Within a budget of 48 candidate evaluations it assesses same-profile
foundations and bounded physical revisions. It retains the best evaluated candidate,
including when a later valid revision is worse. The revision-10 generator is unchanged.

The mandatory target is at least two meaningful decisions on **every shortest
episode**, plus a witnessed earlier branch that reaches the same later room in a
different physical state with a different set of optimal next actions. A meaningful
decision has at least two committed, goal-reaching alternatives with unequal complete
costs. Commitment excludes returning to a state dominated by the original decision.

Ranking caps these dimensions at two decisions and one link, then penalizes traps on
shortest routes, forced steps, rule rows and solution length, in that order. Simple
player policies remain diagnostics; defeating them earns no ranking reward. The
certificate independently reconstructs the model and four mechanic interventions
through core IR. Saved answers and search scores are not certification evidence.

The link is a reachable continuation difference, not a claim of human insight or an
isolated causal effect of one state variable. Some pairs compare different recharge
stages. Different optimal-action sets can overlap. An alternative completion is
shortest under the earlier commitment restriction; the reported optimal next actions
at its later state are unrestricted. These are distinct witness scopes.

Eight simple policies are simulated with uniform handling of ties for 36 actions.
Residual mass is a step-limit outcome, not failure. Probabilities and mean successful
lengths use exact rational strings so browser JSON serialization preserves strict
proof replay. No floating-point tolerance was added to saved-bundle verification.

## Scenario and play contract

`planning_episode.create` binds one authored station-farewell premise to the public
physical model, with three character/voice variants. Topic words remain fictional
room labels. A robot wants to deliver a recording to the caretaker who helped it;
action-specific dialogue and the ending refer to events that actually happened.
Expressive dialogue is explicitly separate from mechanical evidence. There is no
hidden deadline, inventory requirement or fictional punishment for a slower arrival.

`replay` reconstructs state from an action transcript and compares it with the core
interpreter. It rejects unknown/illegal actions, actions after completion, altered
scenarios, invalid hint levels and histories over 128 actions. The history bound is a
transport limit, not an in-world loss condition. All legal arrivals succeed, including
slower completions and tied optimal paths.

The public view contains current state, local action availability and consequences,
history, goal status, and facts supporting feedback. It omits the best remaining cost
and solution. The first two hint levels connect public rules to the current position;
explicit third-level help names a next action. Hints reset after movement, switching,
recharge or undo. Each hint and event carries fact dependencies.

`POST /api/play-episode` accepts exactly `bundle`, `index`, `actions`, `hint_level`.
It verifies the entire immutable bundle before using its model. A per-server cache
holds up to 16 successful full-content hashes for five minutes; changed content must
verify again. Each action transcript is replayed on every request. Same-origin,
request-size and public rate limits remain enforced.

The existing card presents the scenario, full map/rules, actions, undo/restart and
progressive help. The exported first-move quiz stays in a separately labelled
disclosure containing spoilers. Browser progress stores only the transcript and hint
level alongside existing quiz progress. Stale responses cannot replace a new position,
and navigation flushes actions accepted while another set was being verified.

## Validation and remaining questions

The [independent audit artifacts](../../artifacts/engine-capability/2026-10-14/)
freeze the previous source, historical bundles, matched baseline and comparison
protocol. They compare 20 matched cases at the same budget, exercise additional
unseen profile/voice combinations, inspect complete traces and hints, and check all
four quiz formats plus 20-item batches. Saved revisions 1–10 keep their old paths.

Structural checks do not establish enjoyment. This first slice has one story premise,
three authored voices, and a finite mechanic family. The comparison reports reduced
trap/forced-step counts alongside slight diversity losses and additional reading.
Actual player feedback on clarity, insight, agency, humor, emotional interest,
frustration and desire to play again remains pending. The paired review sheet is a
collection instrument, not completed human evidence.
