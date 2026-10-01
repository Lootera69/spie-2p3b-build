# BrainBloom workshop: six question types, no LLMs

The local workshop constructs unpublished drafts using mathematics, symbolic
solvers, constrained search and curated vocabulary. It supports **all six requested
types** and **all five categories**, through **16 programmed families plus
dictionary and reasoning families**. These accept user-entered English topics, resolve
word meanings and construct puzzles from related vocabulary. They perform lexical
matching, not unrestricted prose understanding. See [dictionary topics](brainbloom-dictionary.md).

No LLM, model endpoint, GPU, API key or training run is involved. Non-LLM machine
learning is allowed for future quality ranking or difficulty prediction; no such
model is claimed to have been trained here. Formal checks remain separate from
learned quality scores.

## Run it

From `engine/` in PowerShell:

```powershell
./start-brainbloom.ps1
```

The launcher opens `http://127.0.0.1:8766` and stays in the terminal. Stop it with
**Ctrl+C**. Options: `-Port 8768`, `-NoBrowser`, `-Bank PATH`, `-PlatformVerifier PATH`.
Use `-WordNet PATH` for a custom location of the pinned WordNet ZIP; the default is
`.brainbloom/wordnet.zip` when present. Corpus installation is a separate explicit command.
It detects the known sibling bank and Studio verifier when available, using them
read-only. The setup text reports which checks are active.

`serve` also enables a local SQLite design history at
`.brainbloom/draft-history.sqlite3`. It compares newly generated structures with
previously saved ones across server restarts. Use `--history PATH` for another
archive or `--no-history` for deterministic fresh generation. `--no-integrations`
disables automatic sibling discovery; explicit paths remain supported.
The Python `Generator()` and one-shot `generate` command do not enable history
implicitly. With history enabled, requesting the same seed can skip designs
already generated, so export and keep the entire bundle for reproducibility.

On a fresh checkout with Python 3.12+, create the environment once:

```powershell
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
```

Without the Windows launcher:

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom serve --open
```

## Coverage

| Category | Topics and families | Formats |
| --- | --- | --- |
| Logic | Warehouse, library, laboratory and delivery implications; ordering; explicit sequence rules | Multiple Choice, True / False, Type Answer |
| Logic | Logic vocabulary crossword | Crossword |
| Riddles | Number mysteries with a unique solution in a stated range | Multiple Choice, True / False, Type Answer, Riddle |
| Riddles | Reversed-word riddles | Multiple Choice, Type Answer, Riddle |
| Riddles | Everyday-word crossword | Crossword |
| Science | Motion, electric circuits, density; formulas and assumptions are stated | Multiple Choice, True / False, Type Answer |
| Science | Science glossary crossword | Crossword |
| Puzzles | Everyday arithmetic, explicit sequences, number mysteries | Multiple Choice, True / False, Type Answer; Riddle for number mysteries |
| Puzzles | Mathematical vocabulary crossword | Crossword |
| Wonder | Doubling, birthday probability, pigeonhole guarantees | Wonder |
| All five | User topic: sourced vocabulary with checked letter/order constraints, crossword search or permutation counting | All six |
| All five | Reasoning lab: multi-clue deduction, Bayesian evidence, adaptive question planning | Multiple Choice, True / False, Type Answer, Riddle |
| All five | Activities: rule discovery, contradiction repair, weighted route choice, Bayesian scanner evidence | Multiple Choice, True / False, Type Answer, Riddle |

The displayed category **Wonder** exports as `wonders`, matching BrainBloom's
existing wire value. The question type is `wonder` (singular).

Difficulty is family-specific: implication depth, number of ordering objects,
arithmetic operations, rule complexity, constraint range, word length, crossword
entry count, or size of a mathematical thought experiment. These are structural
heuristics, not player-calibrated difficulty estimates. Crosswords have 3/5/7
connected entries for easy/medium/hard. Reversed-word riddle pools remain small.
The dictionary family uses length bands and more candidates or fewer revealed letters.
Topic-specific word pools are bounded, even when using the large WordNet corpus.

## Preview and export

1. Choose the platform category and how players answer.
2. Enter topics or keywords. The workshop selects suitable meanings automatically
   and shows its choices. **Change meaning (optional)** lets you override a choice.
   **Choose for me** defaults to hard multi-clue deduction or adaptive planning.
3. Choose challenge level and count. Reproduction and search controls are under
   **More options**. Incompatible levels and known finite-count limits are explained.
4. Generate; solve choices, type an answer, fill crossword cells or consider a Wonder.
5. Reveal the answer/insight and inspect the reasoning and check scope.
6. Download draft JSON. No import or publication occurs.

See [the full input flow](brainbloom-workshop-flow.md) for how settings depend on
each other. Setup and drafts scroll independently, with fixed action bars and
small-screen tabs. The green/cream styling remains consistent. A written-instruction
option is documented in [written instructions and panels](brainbloom-instructions.md).

Typed formats include accepted variants. Riddles include hints. Crossword exports
contain `crosswordData.size`, a square letter/null `grid`, and numbered clues with
`answer`, `startRow`, `startCol` and `direction`. Wonders contain an insight in
`lessonContent`, a `sharePrompt`, empty choices and zero XP; they are unscored.

The v2 envelope carries `items`, aligned `proofs`, the request and seeds, checks,
provenance and an `intendedImport` block with `published: false` / `reviewStatus: draft`.
The envelope is a handoff artifact, not an executed import instruction.
Dictionary drafts use a v3 envelope with the bounded vocabulary, selected meaning,
relationship paths and source licence embedded for offline replay.
The [reasoning lab](brainbloom-reasoning.md) uses v4 with the explicit world model,
search measurements, independently checked answer and structural fingerprint.
Current topic-based workshop drafts use **v5**, preserving a meaning and vocabulary
membership for every topic, all source licences and per-puzzle coverage checks.
v3/v4 remain the legacy single-topic formats. Logic grids use v6, Autopilot v7,
and discovery/decision activities v8. New requests record `engine_revision: 4`.
Revision 4 uses concise reasoning and contradiction wording that fits Studio's
120-word question ceiling, with short titles that do not repeat the answer.
The mathematical models, assumptions and answers remain unchanged.
Saved requests without that field replay with revision 1, preserving the old
rendering and quality calculations without presenting them as current findings.

CLI examples:

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --category science --topic motion --type type-answer --difficulty hard --seed 7 --out drafts/science.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --category puzzles --type crossword --difficulty medium --out drafts/crossword.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --category riddles --topic number-riddles --type riddle --out drafts/riddle.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --type wonder --topic probability --out drafts/wonder.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom check drafts/crossword.json
```

`--bank PATH` and `--platform-verifier PATH` also work with `generate`. The CLI
refuses to overwrite files. `check` re-creates content and checks using recorded
seeds; it rejects altered items, proofs, counts or publication state. It supports
all envelope versions v1 through v8 and engine revisions 1 through 4.
It does not authenticate the author or re-run
the saved editorial review. Outputs are deterministic for the same implementation,
solver version, inputs and bank.

## Current activity behavior and design history

Rule discovery presents input/output examples and four candidate rules, identifies
the unique matching rule, and asks for its output on a new input. Arithmetic
enumeration and Z3 check both the rule and answer. The rule is revealed in the
explanation, not stated as the task's premise.

Route choice supplies a directed weighted map and asks for the first stop on the
cheapest complete trip. Dijkstra and exhaustive path enumeration agree on each
option's cost. Medium and hard cases make a cheap first edge insufficient.
The Bayesian activity remains a hidden-card scanner task with stated probabilities;
it does not discover real-world causal explanations.

Grid fingerprints include the actual clues and queried relationship. They ignore
names, input value order, group order and left/right reflection. This is a specific
structural equivalence policy, not a proof that every generated puzzle is a new idea.
Generation and replay share the same in-batch acceptance rule, including activities.
Stored history blocks repeats within these fingerprint definitions and exact items.

## Studio and Flutter handoff

In the sibling web project, open `/studio/import` under the existing Studio login.
Select one workshop JSON bundle, review the previews, then use **Save unpublished
drafts**. The importer validates all six formats and compares item content hashes;
it does not authenticate the author or execute Python solver proofs. Draft status
is forced even for administrators. This is an explicit save action, not automatic
publication. Existing Studio storage behavior applies, including local fallback.

`tools/check_flutter_handoff.py` exercises the real Flutter puzzle model's
`fromMap`/`toMap` and accepted-answer grader using the Dart SDK, without a device
or database. Pass a JSON array of bundles and `--flutter-root PATH`; on Windows,
pass `--dart C:/src/flutter/bin/cache/dart-sdk/bin/dart.exe` if needed.

## Local player pilot

Prepare twelve checked puzzles across six families at easy and hard levels:

```powershell
./.venv/Scripts/python.exe -B tools/player_study.py create --out artifacts/player-study
./.venv/Scripts/python.exe -B tools/player_study.py report --manifest artifacts/player-study/manifest.json
```

Open the generated `index.html`. It randomizes order, hides intended levels,
records answer time, hints, skips, difficulty/enjoyment/clarity ratings and notes,
and downloads an anonymous session file. Only rated, saved responses are exported;
closing the page loses unsaved data. No responses are uploaded automatically.
Add actual downloaded response paths after the `report` command to summarize them.
Use the most recent export once per session. The report recomputes correctness,
rejects duplicates and invalid data, and reports zero responses when none are supplied.
This pilot is observational, and needs actual participants before any calibration
or enjoyment claims can be made. Session-file authenticity is not verified.

## What the checks establish

| Family | Check | Limit |
| --- | --- | --- |
| Conditional reasoning | Z3 + exhaustive truth tables, measured minimum proof depth | Consequences of supplied assumptions |
| Arithmetic and science calculations | Exact Python arithmetic + Z3 | The formula and units stated in the question |
| Ordering | All permutations + Z3 | Unique order satisfying the clues |
| Number mysteries | All integers in the range + Z3 | Unique integer satisfying every clue |
| Word riddles | Two exact reversal implementations | Letter transformation; vocabulary is curated |
| Crosswords | Independent run reconstruction, numbering, cell coverage and connectivity | Grid integrity; clue meaning is curated, not formally proven |
| Wonders | Exact arithmetic, counting or probability cross-checks | The stated model; reflection is unscored |
| Dictionary quizzes | Exhaustive finite-bank constraints, checked by a second computation | Unique answer within the displayed bank; definitions are sourced |
| Dictionary Wonders | Factorial quotient and independent binomial counting | Letter arrangements, not the number of meaningful words |
| Deduction lab | Z3 plus exhaustive permutations and exact minimum-support search | Consequences of explicitly invented card-position clues |
| Bayesian lab | Exact fractions plus independent finite-outcome enumeration | The stated priors and conditional-independence assumptions |
| Planning lab | Bellman recursion, exhaustive policy costs, branch-by-branch rollout | Optimal among the four supplied unit-cost questions |

Every draft passes local field validation. The optional Studio verifier covers the
four quiz types only. Crosswords and Wonders use local validation against the web
and Flutter native fields and explicitly report that Studio's quiz verifier does
not cover them. No live Flutter device test or Studio import was performed.

The existing production bank loader handles quiz batches. Crosswords and Wonders
do not claim comparison against that bank. Within a batch their layouts/content
are compared exactly; quiz questions use exact in-batch comparison and lexical
bank comparison. Parameter variations are not claimed as new underlying ideas.

Studio may reject repetitive questions, especially large same-family batches.
Rejections are reported and proofs remain aligned with retained items. A short
batch is marked incomplete; zero accepted items produce a rejection report.
If the generator itself exhausts its bounded search, it returns a clear error
rather than filling the batch with copies.

## Verification and next extensions

The tests cover all 303 catalogued family/category/type/difficulty combinations, replay,
malformed bundles, tamper detection, wrong solver verdicts, crossword corruption,
offline generation, CLI defaults, and web request handling. Dictionary tests additionally
cover sense separation, lexical matching, anagram collisions, compound words, source
attribution, snapshot corruption and replay without the original dictionary file.
Reasoning tests separately exercise each reasoning skill, format and difficulty,
base-rate effects, corrupted plans, minimal supporting clue sets and solver disagreement.

The next content work is broader mathematical families and a larger reviewed
science source collection and richer topic-specific puzzle rules. Classical ML can rank structural features
or learn difficulty when suitable review labels or player outcomes are available.
The existing bank alone does not establish player difficulty or automatically
extract a generative rule for every question.
