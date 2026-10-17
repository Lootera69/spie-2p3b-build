# Revision 12: varied plans with bounded quality tradeoffs

14 October 2026. This iteration develops the same energy-and-switch engine. It adds
an explicit selection policy, a stronger linked-decision guarantee and three concise
authored scenarios. Local correctness and compatibility validation is complete.
The registered decision-sequence diversity improvement target was not met; this
iteration is not an all-targets success. Human play feedback is still pending;
the activity remains Experimental. See the [validation report](../../artifacts/engine-capability-v12/2026-10-14/validation.md).

## Selection and efficiency

`planning_experience_v2` preserves the revision-11 bounded candidate walk and its
48-evaluation limit. It reuses the base graph during assessment, omits irrelevant
committed-path calculations in mechanic interventions, and caches topology keys only
within a proposal. No cross-request novelty state influences saved replay.

Among candidates satisfying every hard gate, the lexicographically strongest candidate
sets the quality reference. A selected alternative may have no more traps or forced
steps, at most one additional rule row, and at most one additional action. These are
comparisons within that proposal's eligible pool, not promises of per-seed superiority
over a different generator or of human-calibrated difficulty.

Equivalent physical structures receive one entry. Within each topology and optimal
role-sequence group, dominated candidates are removed. A seeded draw then chooses a
role sequence, a topology within it and a remaining structure. The role sequence is
the lexical minimum over all shortest sequences of action roles; it is independent
of room and gate names. Dominance is deliberately local to each group, so useful
structural alternatives can survive within the declared quality limits.

Search evidence retains primitive candidate rules, dimensions, exclusions, the
eligible reference, selection seed and exact tradeoffs. `audit_selection` compiles
the recorded candidate pool independently and reconstructs selection. It audits that
recorded pool, not proof of proposal-RNG provenance or completeness. Saved-bundle
verification separately regenerates the entire request and compares its content.

## Every shortest route must contain linked decisions

Revision 11 required at least two meaningful decisions on every shortest route and
one witnessed dependency somewhere in the optimal state graph. Revision 12 retains
those gates and additionally requires a dependency on **every shortest route**.

The earlier action actually taken must have a competing, committed completion that
reaches the same later room in a different state and changes the unrestricted optimal
action set there. Both decision points must be meaningful. All shortest committed
competing completions are considered, avoiding dependence on room-name tie-breaking.
These are reachable continuation consequences; they may involve different recharge
stages and do not isolate a single physical variable as the cause.

`planning_causal_paths` computes action-conditioned witness relations and propagates
uncovered routes through the shortest-path DAG. Subset-dominance pruning preserves
potential counterexamples. Its explicit processed-context limit raises an unknown
result when exhausted; unknown coverage cannot pass selection or certification.
Final certification uses freshly compiled core graphs and retains all four mechanic
interventions, a unique optimal opening, viable alternatives and original bounds.

## Concise authored context

`planning_scenarios` binds three situations to the same public model: a farewell
recording, community radio repair notes and a theatre invitation. Each has stable
characters, a relationship, an explicit destination and an arrival-based resolution.
No deadlines, inventory rules or extra action costs are introduced. All legal
arrivals succeed, including slower routes.

Action dialogue refers to observed visits, energy, charging or gate changes. Early
hints connect current public constraints; only explicit third-level help names an
optimal next action. The response and transcript contracts remain compatible with
the existing player. Story-specific headings and destination names prevent a radio
or theatre episode from accidentally displaying the farewell ending.

## Versioning and evidence

New requests use engine revision 12, `planning-experience-v2` and `planning-episode-v2`.
Saved revisions 1–11 keep their existing generation paths. Revision-11 episode text
and runtime results have frozen replay checks. The previous
[revision-11 contract](planning-experience.md) remains historical documentation.

The [predefined protocol](../../artifacts/engine-capability-v12/2026-10-14/protocol.md)
and [linked-decision addendum](../../artifacts/engine-capability-v12/2026-10-14/link-protocol-addendum.md)
separate development seeds, untouched comparison cases, additional heldout cases,
controlled timing and historical replay. Rejected development experiments are retained.
Passing structural checks does not establish clarity, humor, emotional impact or enjoyment.
