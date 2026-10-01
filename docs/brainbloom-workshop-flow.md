# Connected workshop flow

The workshop uses connected, plain-language choices and retains its green/cream
visual identity. Setup and drafts now have separate scroll areas and fixed action
bars. On small screens, Setup/Drafts tabs preserve both panels' state. Generation
opens the new results automatically.

## What the user chooses

| Control | Meaning | Connections |
| --- | --- | --- |
| Platform category | Where the puzzle appears in the platform | Limits the available activities; it does not prove a topic is scientific |
| How will players answer? | Multiple Choice, True / False, Type Answer, Crossword, Riddle or Wonder | Only compatible activities are offered |
| Topics or keywords | Up to six English topics, separated by commas | Every supplied topic must be represented; blank uses an explicit built-in/default scenario |
| Meaning for each topic | Automatically selected from authored packs or ranked lexical senses | Visible choice with an optional override; selected meanings are saved for replay |
| What should players do? | A plain-language activity, or Choose for me | Suggestions account for category, format, topic count, vocabulary and challenge level |
| Describe it in my own words… | A text alternative to the presets | Supported phrases compile to settings; changes require Apply and unknown details block generation |
| Challenge level | The structural complexity of this activity | Levels that cannot fit all topics are disabled with an explanation |
| How many puzzles? | Number of different drafts requested | Known finite limits are shown; search exhaustion is still reported explicitly |
| More options → Time spent exploring ideas | Quick, Standard or More exploration | Shown for reasoning activities; controls proposal budget, not difficulty |
| More options → Variation number | Reproduce the same settings and puzzle | The main Make another version button changes it automatically |

Examples of user-facing activities:

- **Design a clue puzzle for me** → Autopilot chooses labels and groups from your topics,
  invents and prunes clues, selects a question that needs at least two clues together, and
  independently checks the complete answer. This remains an explicit activity choice.

- **Solve a set of clues** → checked multi-clue deduction.
- **Weigh the evidence** → exact Bayesian inference with stated priors and likelihoods.
- **Choose the best next question** → optimal adaptive question planning.
- **Create a custom logic grid** → enter 1–3 groups of 3–4 values and rules such as
  “Tiger is before Lion” or “Tiger is paired with Red”. The engine reports ambiguity,
  identifies contradictory rules, and can add labelled clues until the full grid has one
  solution.
- **Discover a number rule** → infer an arithmetic operation from examples and predict the next value.
- **Find the impossible clue** → use a finite ordering chain to identify the one incompatible statement.
- **Choose the most likely explanation** → calculate exact posterior probabilities from stated evidence.
- **Plan the best next move** → compare complete costs of routes on a weighted map.
- **Unscramble a word**, **Find the missing letters**, **Put words in order**.
- **Connect words in a crossword**, **Explore patterns in words**.
- Without custom topics, compatible built-in number and science calculations.

Format or category changes preserve the chosen activity when it still fits.
Switching to a fundamentally different format falls back to Choose for me.
Entering custom topics while on a built-in preset selects a topic-aware suggestion;
the server also rejects any request that would silently discard those topics.

Wonders are displayed as **unscored**. The combined word-reflection activity hides
challenge level because that setting does not change the calculation's complexity.
Its native export retains the platform-required default `medium` value. Search
time is hidden for activities that do not use candidate ranking.

## Custom rules and logic grids

Custom grids are an advanced authoring mode. New creators should use **Design a clue puzzle
for me**: provide topics, answer format and level, then let BrainBloom design the groups and
clues. Open **Advanced: provide my own rules** only when you need a specific authored puzzle.

Autopilot is bounded symbolic design, not unrestricted thought. It selects vocabulary from the
chosen offline topic meanings, samples several candidate arrangements, chooses a question whose
answer needs multiple clues, and retains the design decisions in the proof. It does not invent
real-world facts about topic words. The final solution is checked by the same exhaustive and Z3
paths as a manually authored grid.

Autopilot uses three positions: Easy has one group (three topic labels), Medium has two
groups (six labels), and Hard has three groups (nine labels). Levels that cannot include
all supplied topics are disabled. Blank topics use the category vocabulary, visibly indicated
in setup. Each run compares six candidate designs and ranks qualifying questions by minimum
supporting-clue count, clue-type variety and total clue count. A question answerable from a
single clue is rejected. Search is bounded and can ask for another variation if no candidate
qualifies. This is an automatic clue-puzzle designer; other activities remain available for
crosswords, Wonders, numerical and probability puzzles.

The **Start with a reasoning challenge** walkthrough includes a worked three-card example and
an **Try an easy animal puzzle** setup button. Hints are revealed one at a time. Every draft
includes **How BrainBloom designed this**, explaining its actual choices.

API: use `activity: "autopilot"` with topics, meanings, difficulty and answer format in
`/api/prepare`; no `grid` field is needed. CLI:

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --topic autopilot --subject "animals, space" --difficulty medium --out drafts/autopilot.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom check drafts/autopilot.json
```

Autopilot exports use `brainbloom-autopilot-v7`. They retain the dictionary snapshot, chosen
meanings, topic coverage, invented specification, search results and minimum supporting-clue
proof. Replay uses that snapshot offline and rejects changes to those records. Existing
generator routes and their versions are retained.

Custom grids use fictional labels exactly as entered; they do not assert real-world facts
about the labels. Define groups in the form `Group: value, value, value`, with one to three
groups and three or four values per group. Values must be unique across the whole grid.

Supported bounded rules are:

- before, after, immediately before, next to, or not next to;
- paired with or not paired with;
- in or not in a numbered position;
- an exact positional distance; and
- between two other values.

The setup preview enumerates every bounded arrangement and independently checks satisfiability
and uniqueness with Z3. Contradictory rules are rejected with an irreducible conflicting
subset: removing any reported rule makes that subset consistent, though it need not be the
smallest possible subset.
If **Keep my rules and add clues if needed** is selected, generated clues are labelled separately
from creator-authored rules. **Use only my rules** requires those rules to identify one complete
grid. The player preview includes a fillable grid and a check button.

Current grid analysis propagates clue constraints and all-different matching, then tries
single assumptions and rejects those that lead to a contradiction. Each domain reduction
records its reason and the remaining positions. Hints use these checked deductions.
If that bounded teaching procedure cannot finish the grid, the explanation says that the
independent exhaustive check was needed. There is no numeric quality score or fairness
rating. These are measured deductions, not an empirically validated model of how people
solve puzzles. Autopilot also checks the minimum clues needed for the specific question
and compares multiple candidate designs. Older revision-1 bundles retain their original
analysis solely for replay compatibility.

The activity supports Multiple Choice, True / False, Type Answer and Riddle across all
categories. Every group must have the same number of values. Labels use English letters,
digits, spaces and hyphens; up to 20 rules are accepted. A position is numbered left to
right; pairing means sharing a position; between is strict and may face either direction.

The workshop hides the difficulty selector for this activity. Exported difficulty is an
estimate based on group count (one/easy, two/medium, three/hard), not player-calibrated
difficulty. Batch capacity counts distinct complete-grid/question pairs, capped at 20.

The CLI accepts the same JSON model. Save this example as `examples/grid.json`:

```json
{
  "groups": "Animal: Tiger, Lion, Owl\nColour: Red, Blue, Green",
  "rules": "Tiger is before Lion.\nTiger is paired with Red.",
  "complete": true,
  "target": "Tiger",
  "answer_group": "Colour"
}
```

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --grid examples/grid.json --type multiple-choice --out drafts/grid.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom check drafts/grid.json
```

Use `activity: "logic-grid"` and this object as `grid` in `/api/prepare`; submit the
returned request to `/api/generate`. Custom-grid exports use
`brainbloom-logic-grid-v6` and retain original groups, rules, added clues, solution tables
and elimination traces. Replay reconstructs and checks the solution; v1–v5 exports remain
supported.

## Multiple words and meanings

Input `bank, crane` produces two independent meaning selectors. Choosing a financial
meaning for bank does not choose, clear or replace the meaning of crane. Both choices
are retained in the generated request and exported snapshot.

The parser matches the longest non-overlapping known phrase, so `solar system`
stays together. It preserves input order, deduplicates repeated identical terms,
skips recognised connective/request words, and records all unknown content words.
Commas are the clearest way to separate topics. This is lexical matching rather
than full instruction or sentence understanding. Unknown words block generation;
there is no automatic omission or unrelated fallback.

Ready vocabulary is merged fairly across topics, capped at 80 distinct entries.
Each entry has one clue meaning. Conflicting homonymous senses are not treated as
interchangeable. Each topic records its chosen meaning, definition, vocabulary
membership, source and any required input-word anchor. A finite matching check
ensures each topic can have a distinct representative.

If a supplied word is directly available in the chosen meaning, generation must
use it. For WordNet inflections, the corresponding root word can be the anchor.
Broad topic packs such as Space contribute related entries such as ORBIT or COMET.
Without WordNet, individual words already present in authored packs are also
recognised, with their pack providing the related vocabulary.

## Coverage is checked inside each puzzle

- **Word quizzes/riddles:** the actual displayed candidate bank covers every topic.
- **Deduction, evidence and planning:** the actual card model covers every topic.
- **Crosswords:** the placed, clued grid entries cover every topic. A heading alone
  does not count. A failed connected-grid search never drops a required topic.
- **Word Wonders:** one representative from every topic participates in the
  arrangement calculation, with exact independent checks.

Reasoning cards use invented, stated rules. Combining `bank` and `crane` does not
invent a real-world relationship between finance and birds. Related word retrieval
and formal puzzle reasoning have separate, explicit scopes.

## Examples of connected validation

- Six topics cannot fit a four-card evidence puzzle; choose another activity.
- Six topics require a seven-entry hard crossword, rather than an easy three-entry grid.
- A hard six-card deduction puzzle needs at least six usable words.
- Two fixed literal words permit only one distinct letter-arrangement reflection.
  The count is capped at one and Make another version is disabled for that case.
- A fixed speed-calculation preset cannot consume custom topics; it is not offered
  as a silent substitute for a personalised puzzle.
- Adding a topic preserves existing meaning selections; removing a topic prunes
  only that selection. Stale asynchronous responses cannot replace newer inputs.

Known capacity checks do not guarantee a connected crossword or enough distinct
drafts at every seed. Bounded search can still return a specific generation error.

## API, CLI and replay

### Crossword board sizes

When Crossword is selected, **Crossword board size** offers **Use recommended size**
and every square board from **5×5 through 15×15**. The recommendation is the smallest
board found by a bounded sample construction using the selected meanings, mandatory
input words, coverage of every topic, and the difficulty's 3/5/7 entries. It reports
the lengths of the sample's actual words. Optional long dictionary words do not force
a bigger board if shorter words can represent the same topic.

An explicit size is retained when settings change and is never silently enlarged or
trimmed. Bigger boards remain selectable for short words; they add blank space, not
extra clues. Required words that exceed the board, insufficient fitting vocabulary,
or failed connected-layout search produce an actionable message. A recommendation
is a checked sample, not a promise that every variation or batch can be constructed.

`/api/prepare` accepts `crossword_size: null` for a recommendation, or an integer
5–15. Its ready request contains the resolved size. `/api/generate` stores the exact
size, and saved replay checks the full grid and its numbered clues. The size setting
is rejected for other formats; the UI preserves it without sending it for those formats.
Historical unsized API exports retain their original trimmed-grid generation for replay.

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --subject "space, ocean" --type crossword --crossword-size 15 --out drafts/crossword-15.json
```

`POST /api/prepare` accepts the plain-language brief:

```json
{
  "category": "logic",
  "qtype": "multiple-choice",
  "activity": "deduction",
  "subject": "space, ocean",
  "meanings": {},
  "difficulty": "medium",
  "count": 1,
  "seed": 7,
  "search_effort": "balanced"
}
```

It returns per-topic choices, retained meanings, compatible activities and levels,
count limits, readiness, explanations, and a validated engine `request` when ready.
The client submits that request to `POST /api/generate`. Generation resolves and
checks the selections again rather than trusting the preview.

Current requests use `topic_mode: "combined"` and `meanings: {"topic": "sense-id"}`.
The Python Request default remains `single` for compatibility with existing clients.
The old `/api/topics` single-topic endpoint is retained for those clients.

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom topics "bank, crane"
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --subject "space, ocean" --type crossword --difficulty medium --out drafts/combined-crossword.json
```

Use repeated `--meaning "bank=ID" --meaning "crane=ID"` arguments for ambiguous
topics, taking IDs from their individual lookup choices. CLI topic generation now
combines all terms by default; `--sense ID` explicitly retains the older single-topic path.

The v5 envelope (`brainbloom-topics-v5`) stores every selected meaning, combined
vocabulary, topic memberships, anchors, original dictionary attributions and licences,
and actual `topic_coverage` for each item. Replay reconstructs the candidate and
coverage without requiring WordNet to be installed. v1–v4 replay is preserved.
Replay checks consistency and reproduction, not author authenticity or universal
truth of source definitions.

## Probability model decision

The evidence activity uses exact Bayesian inference over an explicitly specified
finite experiment, checked by independent outcome enumeration. It is a reasoning
algorithm, not a trained frontier model. The question planner uses exact dynamic
programming with independent policy and rollout checks. These are appropriate
correctness tools for these small, fully stated puzzles.

This flow update does not claim a new trained model or frontier-level intelligence.
A learned model's useful next role is quality/ranking or difficulty prediction,
evaluated against editor preferences or player outcomes. Replacing exact inference
with a larger model would require evidence of a benefit for that role.

For the written-instruction grammar and independent scrolling behaviour, see
[written instructions and panels](brainbloom-instructions.md).

## Verification

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_brainbloom_workshop.py tests/test_brainbloom_symbolic.py tests/test_brainbloom_dictionary.py tests/test_brainbloom_reasoning.py tests/test_brainbloom_flow.py
```

`tests/brainbloom_flow.cjs` exercises the actual HTML/JavaScript against the running
local API in jsdom: two ambiguous words, preserved meanings, format compatibility,
generation, unknown words, out-of-order responses, six-topic capacity, finite counts,
keyboard focus and blank-input defaults. It controls no external browser.

Install jsdom as a development-only dependency in a temporary folder, then run:

```powershell
node tests/brainbloom_flow.cjs PATH_TO_JSDOM http://127.0.0.1:8766
```

No jsdom dependency is needed to run or distribute the generator itself.
