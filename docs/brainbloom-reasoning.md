# Reasoning lab: stronger puzzle generation without LLMs

## What is implemented

In the local workshop, enter your topics and choose the meaning of each ambiguous
word. Then select **Solve a set of clues**, **Weigh the evidence**, or **Choose the
best next question** under **What should players do?** Exploration time is under
**More options**. The workshop includes every selected topic and filters activities
and levels that cannot fit them. See [the connected flow](brainbloom-workshop-flow.md).

The topic vocabulary supplies **labels in explicitly fictional card problems**.
It does not infer scientific facts, causal relationships or probabilities from
dictionary definitions. Every rule, probability and allowed action needed for
the answer is stated in the puzzle.

The lab supports Multiple Choice, True / False, Type Answer and Riddle across the
five platform categories. Existing dictionary crosswords and Wonders remain
available through their generators. No neural model is loaded, trained or called.

### 1. Multi-clue deduction

- Sample a hidden arrangement of four, five or six topic-labelled cards.
- Construct true clues using ordering, adjacency, exclusion, distance and between
  relations, with more expressive relation types at higher difficulty.
- Search alternative information-reducing clue combinations until one complete
  arrangement remains. Remove every clue that is redundant for full uniqueness.
- Enumerate **every subset** of the final clues to find the smallest set that
  forces the queried answer. Accept only 2–3 supporting clues at easy, 3–4 at
  medium, or 4–5 at hard. This is a minimum-support measure, not a claim about
  how many psychological reasoning steps a person will take.
- Independently encode the problem in Z3. Both exhaustive permutations and Z3
  must establish a consistent, unique full arrangement.

The explanation shows how each clue changes the surviving arrangements and
which positions are forced. It reports one smallest supporting clue set. The
proof records every clue-deletion model count, making irredundancy testable.

### 2. Bayesian evidence

Four candidate identities have specified prior weights. A fictional scanner
produces one, two or three readouts. Its positive-readout probabilities are given
for each identity. The question explicitly states that readouts are independent
**conditional on the hidden identity**, not unconditionally independent.

The engine computes exact rational posterior probabilities and chooses the
unique most-likely identity. Hard questions include negative evidence. Search
favours examples where priors or accumulated evidence change a tempting answer.
Ties and excessively small or large posterior margins are rejected.

A separate checker enumerates the scanner's possible ten-ticket outcomes to
derive exact observation frequencies. Those frequencies must reproduce the
posterior. The explanation distinguishes **most likely** from **certain**.

### 3. Plan the best next question

The player must identify a hidden card using four specified yes/no questions.
Answers are truthful, every question costs one unit, priors are stated, and later
questions can depend on earlier answers.

The engine computes the expected **total** cost of each possible first question,
assuming optimal choices afterwards. It solves the finite belief-state problem
with the Bellman recurrence:

`V(S) = min_q [1 + P(yes | S) V(S_yes) + P(no | S) V(S_no)]`

Singleton states cost zero. Questions that do not split the current state are
excluded. Candidate test sets must distinguish every card, and the best first
question must be unique. Easy uses four equally likely identities; medium/hard
use five/six identities and nonuniform priors.

A separate set-based exhaustive policy evaluator must agree with all four
expected costs. The chosen tree is then rolled out for **every hidden identity**:
each leaf must identify the correct card and the weighted path lengths must
match the predicted cost. This is exact small-domain planning, not just choosing
the most balanced-looking first partition.

## Candidate selection and variety

The search budgets are **12**, **32**, and **80** candidate proposals. Each proposal
is solved to test its skill-specific gates. The highest-scoring qualifying proposal
receives the independent checker before release. A checker disagreement stops the
request. If the proposal budget finds nothing suitable, generation reports that
instead of weakening the gates.

The versioned structural scores are:

- Deduction: `20 × minimum support + 5 × clue kinds − clue count`.
- Bayesian: `20 × evidence steps + 10` if evidence overturns a strictly higher
  prior leader, plus `10` if including priors changes the likelihood-only winner.
- Planning: `20 × difficulty level + min(10, floor(20 × optimality margin))`.

These are **engineering objectives**, not calibrated ratings of enjoyment,
creativity, human difficulty or intelligence. They are compared only within the
same skill. Increasing the budget preserves the proposal prefix, so the selected
structural score cannot be lower than that of the shorter search.

Automatic mode rotates deduction, Bayesian evidence and planning across candidate
seeds. In-batch fingerprints reject repeated reasoning structures even when card
labels differ. This catches structural repetition within the defined encoding;
it is not a universal semantic-novelty test or persistent cross-session archive.

## Reproducibility

Legacy single-topic exports use `brainbloom-reasoning-v4`; current combined-topic
exports use `brainbloom-topics-v5`. They retain the dictionary snapshot and
attribution, request and seed, selected explicit model, search budget and qualified
scores, quality measurements, independent checks and structural fingerprint.
`check` reruns proposal search, selection and verification. No corpus download,
learned model or network connection is needed for replay. v1–v4 replay remains supported.

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --topic reasoning --subject ocean --variation deduction --difficulty hard --search-effort thorough --type riddle --out drafts/deep-ocean-logic.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --topic reasoning --subject animals --variation bayesian --difficulty hard --out drafts/animal-evidence.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --topic reasoning --subject space --variation planning --difficulty hard --out drafts/space-planning.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom check drafts/space-planning.json
```

## Measured regression benchmark

Run:

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom benchmark --subject space --seeds 10 --out artifacts/reasoning-benchmark-new.json
```

This covers each skill and difficulty at seeds 0–9. It records generation failures,
independent verification/replay, latency, candidate acceptance rate, the selected
score versus the first qualifying draft, and within-sample structural fingerprints.
Existing reports are never overwritten. A verification discrepancy aborts the
benchmark rather than being counted as a passing row.

The final local report for this iteration is `artifacts/reasoning-benchmark-v2.json`:

- **90/90** generated cases independently checked and replayed; no rejected requests.
- **56/90** selected drafts improved the structural objective over the first
  qualifying draft.
- Across 30 cases per skill: **29** distinct deduction fingerprints, **30** Bayesian
  fingerprints, **23** planning fingerprints.
- Mean generation time in this run: **0.1000 seconds**, excluding replay. Timing
  depends on hardware and environment and is not a performance guarantee.

This sample provides evidence of correctness and search behaviour. It does not
establish that every future request succeeds, every puzzle is engaging, the
difficulty matches players, or the system matches frontier AI.

## Non-LLM research direction

The useful target is excellent performance in the **puzzle domain**, measured with
held-out tasks and blind human review. General-purpose frontier-model intelligence
does not follow from using a probabilistic model, a knowledge graph, or a solver.

1. **Richer explicit world models:** logic grids with multiple attributes, causal
   interventions, resource planning and program-synthesis grammars. Retain separate
   answer checkers as the hypothesis spaces expand.
2. **Human-oriented explanations:** implement sound propagation rules and measure
   their actual dependency depth, distinguishing deductive solving from case search.
3. **Learned quality ranking:** collect blind pairwise editor preferences, relevance
   labels and rejection reasons. Fit classical gradient-boosted/ranking models to
   structural features; evaluate on held-out topics and puzzle structures.
4. **Player-calibrated difficulty:** use solve times, errors and hint usage to fit
   item-response or Bayesian difficulty models. Synthetic difficulty scores are not
   a substitute for this evidence.
5. **Adaptive proposal search:** the repository already contains LinUCB and other
   operator-selection work in `spie/context_policy.py` and `spie/steering.py`.
   Connect those policies when measured rewards are available. Let them choose what
   to propose; retain exact gates for accepting answers.
6. **Graph/neural search guidance:** a non-language graph neural network can predict
   useful constraints or promising puzzle states. Training data and a held-out
   benchmark must show that it beats the current exact-search baseline before it
   becomes part of generation.

JEPA is relevant to the broader idea of predictive world models, but is not a
drop-in puzzle-language intelligence engine. Meta's V-JEPA 2 predicts visual
representations and supports robotic planning. Its paper also explicitly describes
LLM alignment for video question answering; those results should not be treated
as evidence of standalone non-LLM language reasoning.

Sources:

- [V-JEPA 2 overview, Meta](https://ai.meta.com/research/vjepa/)
- [V-JEPA 2 paper](https://arxiv.org/abs/2506.09985)
- [Generating and Solving Logic Puzzles through Constraint Satisfaction, AAAI](https://cdn.aaai.org/AAAI/2007/AAAI07-361.pdf)

No JEPA weights or other neural model were added in this iteration. The implemented
advance is exact reasoning, adaptive planning and quality-guided candidate search.
