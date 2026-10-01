# Topic-driven puzzles without LLMs

## Use the workshop

Run `./start-brainbloom.ps1` from `engine/` and open the local workshop.

1. Choose the platform category and how players answer.
2. Enter English topics separated by commas, such as `space, ocean, animals`.
3. Topics and suitable meanings are selected automatically. The selected definition
   is visible, with **Change meaning (optional)** for corrections. Related-word previews
   are grouped by topic. Every unrecognised term
   must be corrected or removed by the user before generation.
4. Choose **Unscramble a word**, **Find the missing letters**, **Put words in order**,
   or a compatible crossword/Wonder activity. Set the challenge level and count.
   **More options** contains the variation number used for reproducibility.
5. Generate, play, reveal the explanation and download the unpublished JSON.

All supplied topics contribute to the puzzle. Every topic retains its own
selected meaning in the export. Explicit overrides survive edits to other topics;
automatic choices can be ranked again when the surrounding topics change.
Every word bank, card model and crossword must contain a representative of each
topic; a directly available input word is retained. Wonders combine one word from
each topic in their calculation. This is lexical topic combination, not unrestricted
understanding of prose or invented factual connections between unrelated subjects.
See [the connected workflow](brainbloom-workshop-flow.md).

## Dictionary sources

The [versioned coverage expansion](brainbloom-coverage.md) additionally ships eight
versioned topic packs (106 current entries: 96 adapted from OEWN and ten project-authored)
and supports additive Open English
WordNet 2024. It preserves the original sources described below and reports each
source separately. Its review and benchmark limitations are recorded explicitly.

Twelve authored packs ship with the code: Logic, Science, Puzzles, Riddles, Space,
Animals, Plants, Ocean, Black Hole, Climate Change, Photosynthesis and Quantum
Computing. Their definitions are project-authored. Common aliases include astronomy,
solar system, wildlife, botany, garden and marine life. The four specialist packs
each contain ten terms. They improve usable vocabulary coverage; they do not add
subject-specific inference or establish the scientific accuracy of generated relationships.

For broader lookup, install **Princeton WordNet 3.0** once:

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom dictionary-install
```

The installer downloads the corpus ZIP from NLTK's data repository, checks SHA256
`cbda5ea6eef7f36a97a43d4a75f85e07fccbb4f23657d27b4ccbc93e2646ab59`, and writes
`.brainbloom/wordnet.zip` without overwriting an existing file. It is dictionary data,
not a trained model. No NLTK package, API key or GPU is required.

The launcher and CLI automatically load that file when present. `--wordnet PATH`
(or launcher `-WordNet PATH`) selects another location for the same pinned corpus.
Python integrations explicitly use `Generator(wordnet=Path(...))`; `Generator()`
uses authored packs only. Neither generation nor replay downloads anything.

The installed index contains **151,384 terms including inflections and compounds**
and **117,659 senses**. These numbers are lookup coverage, not a promise that every
word can produce every puzzle. Existing authored topic packs take precedence over
WordNet senses for their topic names and aliases.

For a selected WordNet meaning the engine collects synonyms, kinds, instances,
members, substances and parts, through at most two relationship steps. Direct
broader kinds are included, but their unrelated sibling branches are not expanded.
Every selected entry records its sense and relationship path. Word banks contain at
most 80 distinct entries with 3–15 A–Z letters. Compound spaces and hyphens are
omitted and this convention is stated in the question. Uppercase proper-name
lemmas and entries outside these constraints are excluded.

WordNet is an older general English lexical resource. It is not an encyclopaedia
of current science, a multilingual dictionary, or a child-audience editorial filter.
Its definitions and relations are source material; formal checks establish puzzle
constraints, not the universal truth or suitability of a dictionary definition.

## Formats and variations

| Format | Construction and check |
| --- | --- |
| Multiple Choice | Four options; exactly one satisfies the explicit letter or ordering rule |
| True / False | A proposed answer is checked against the same exact rule |
| Type Answer | A unique word from the displayed bank, with accepted answer wrappers |
| Riddle | A constrained word riddle with dictionary clue, displayed bank and two hints |
| Crossword | 3/5/7 connected sourced entries, independently reconstructed and checked |
| Wonder | An unscored letter-arrangement thought experiment, counted two ways |

Quiz variations are **anagram**, **missing letters**, **alphabetical ordering**, or
**automatic**. Anagrams preserve the letter multiset; when two bank entries are
anagrams, an explicit starting prefix disambiguates them. Missing-letter masks are
extended until exactly one bank word fits. Ordering positions use A–Z order.
The independent checks enumerate the actual bank, so false alternatives are not
based on guessing that two dictionary definitions cannot overlap.

The workshop suggests an activity based on category, answer format and topic capacity.
Crosswords and Wonders have their own rules, so they do not expose a separate variation
control. All six formats are available in each category for this
family; the chosen category is an editorial label, not a claim that any topic becomes
a scientific calculation. The existing formula-based science families remain selectable.

Difficulty changes target word-length bands, bank size, revealed-letter count, or
crossword entry count. It is a structural heuristic, not player-calibrated ML.
Wonders count *all distinct arrangements*, not meaningful dictionary words.

At least four usable words across the combined topics are required. Hard crosswords need at least
seven and may still fail to find a connected layout. A narrow sense, unknown topic
or exhausted finite batch produces an actionable error instead of unrelated fillers
or an incomplete export. Repeated seeds are reproducible; new seeds create parameter
variations, not necessarily new underlying puzzle ideas.

## CLI

```powershell
# Inspect the automatic choice and optional alternative meanings.
./.venv/Scripts/python.exe -m spie.questions.brainbloom topics bank

# --subject selects the dictionary family when --topic is omitted.
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --subject animals --category riddles --type riddle --variation anagram --count 3 --seed 7 --out drafts/animal-riddles.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --subject ocean --category science --type crossword --difficulty hard --out drafts/ocean-crossword.json
./.venv/Scripts/python.exe -m spie.questions.brainbloom check drafts/ocean-crossword.json
```

The CLI now combines topics by default. Use repeated `--meaning TOPIC=ID` arguments
to override automatic choices, using IDs under each topic's `choices` from `topics`.
The older `--sense ID` explicitly selects the legacy single-topic path.
Both paths validate meanings against the input.

## Exports and verification

Current combined-topic bundles identify themselves as `brainbloom-topics-v5`, version `5`.
Legacy single-topic dictionary bundles retain `brainbloom-dictionary-v3`.
They include the request, selected senses, bounded dictionary snapshot, source
identity, corpus hash, source licence, generated items and aligned proofs.
Each proof binds the full snapshot's digest. Replay reconstructs the questions
and rechecks answers using the embedded snapshot, so the original WordNet file is
not needed. Existing v1–v4 replay remains supported. v5 explicitly checks per-topic
memberships, anchors, selected meanings, source licences and actual puzzle coverage.

Replay detects edits relative to the recorded request and snapshot; it does not
authenticate the author or independently audit the source definitions. It does not
run the live platform import or repeat saved editorial review. WordNet's full
licence travels in `dictionary.source.license`; retain it with redistributed data
and derived exports. The wire fields on each question remain the platform's native
quiz/crossword/Wonder fields, with metadata in the surrounding draft envelope.

## Verification commands

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_brainbloom_dictionary.py tests/test_brainbloom_workshop.py tests/test_brainbloom_symbolic.py
./.venv/Scripts/python.exe -m ruff check src/spie/questions/brainbloom tests/test_brainbloom_dictionary.py tests/test_brainbloom_workshop.py
node --check src/spie/questions/brainbloom/static/app.js
```

The WordNet integration tests run when the pinned corpus is installed, and skip
explicitly when it is absent. The authored-pack, API, exact-rule and replay tests
run without it.
