# BrainBloom question generator: implementation and training handoff

The product goal is to take an author's topic, category, question type, difficulty,
and count, then write fresh questions in the style of the existing BrainBloom bank.
The old `invent/evolve` action-puzzle search and its 600-observation operator policy
do not learn to write these questions. They remain available as separate research tools.

## What the new path does

`python -m spie.forge` reads the actual bank, prepares supervised training examples,
selects related training examples for a writing request, calls an explicitly chosen
model endpoint, and saves draft questions using the platform's fields. It never
writes to Firestore, changes publication state, or downloads a model implicitly.

The writer may be a base model for an initial baseline, or the eventual fine-tuned
model. Example retrieval is BM25 over corpus words. **Retrieval and preparation are
not language-model fine-tuning. No new language-model weights have been trained.**

Inputs: `category`, `type`, `difficulty`, `topic`, `count`, optional `lesson-group`.
Outputs: questions, choices/accepted answers, answer, both explanations, lesson,
XP, and curriculum group. Provenance and check reports are kept outside the items.

The current bank covers four quiz types: multiple-choice, true-false, type-answer,
and riddle. Flutter supports nine kinds. Sudoku, crossword, cipher, story, and
the separate `wonder` type require their own structured data; this bank does not
train those five formats. The `wonders` CATEGORY is different from the `wonder` TYPE.

## Existing application connection

Inspected `brainbloom_flutter/lib/core/models/puzzle.dart`: wire values and content
fields match the bank. `puzzle_service.dart` loads published Firestore `puzzles`.
The web project `BrainBloom` owns Studio and its existing `lib/forge/verify.ts`.
The generator can call that exact verifier locally via `--platform-verifier`.
The receiving workflow is Studio review followed by publishing; Flutter then
loads the content through its existing service. No mobile or backend code was changed.

Draft format is compatible at the field level; no live Studio import, Firestore
write, or Flutter device test has been performed for these generated drafts.

## Corpus preparation

Production source: `../puzzle-batch/output/validated/batch-NNN.validated.json`.
The nine-row `batch-000-demo` fixture is excluded. Sources are hashed; content is
not edited. Only `forgeId`/`forgeScore` metadata, missing empty choices on typed
answers/riddles, and curly curriculum apostrophes are normalized on a copy.

The checked preparation run read 5,002 rows. It retained 4,974 and quarantined 28:
26 violate the stricter lesson-line contract; 2 omit the canonical answer from
their accepted variants. These are training-preparation findings, not an assertion
that the original platform verifier is wrong. See the manifest for every source ID.

Splits: 3,965 train, 490 validation, 519 test. Exact duplicate stems are deduplicated;
conflicting authored answers for an identical stem are quarantined. Numeric and
lexically near-identical variants form groups before splitting. This reduces
lexical leakage; semantic paraphrase/family leakage is NOT established as absent.
Only train records are used for retrieval. Split sources and group IDs are saved
alongside chat-format JSONL. Inputs contain category/type/difficulty/curriculum;
the target question and answer are assistant outputs, not leaked user inputs.

`validated` means prior contract checks, **not** human approval or factual truth.
Training targets need editorial sampling and factual review before a production
fine-tuning run. The old formal auditor recognized just 10 of all 5,011 raw rows
in the checked run, so it cannot certify this entire bank.

## Commands (PowerShell, from engine)

Use a new output path each time; the tool deliberately refuses to overwrite.

```powershell
.\.venv\Scripts\python.exe -B -m spie.forge prepare --bank ..\puzzle-batch\output\validated --out artifacts\forge\bank-v2

.\.venv\Scripts\python.exe -B -m spie.forge request --corpus artifacts\forge\bank-v1\corpus.json --category logic --type multiple-choice --difficulty medium --topic "warehouse security conditional reasoning" --count 1 --out artifacts\forge\request-new.json
```

`request` is offline and produces `messages` plus source references. For a configured
local or hosted endpoint implementing the chat-completions protocol:

```powershell
.\.venv\Scripts\python.exe -B -m spie.forge generate --corpus artifacts\forge\bank-v1\corpus.json --category logic --type multiple-choice --difficulty medium --topic "warehouse security conditional reasoning" --count 1 --endpoint "http://127.0.0.1:8000/v1/chat/completions" --model "YOUR_SERVED_MODEL" --platform-verifier "C:\Users\singh\Downloads\BrainBloom\lib\forge\verify.ts" --out artifacts\forge\draft-new.json
```

The local URL/model above are placeholders, not a running service. For an
authenticated HTTPS endpoint, use `--key-env NAME_OF_KEY_VARIABLE`. Keys are never
stored in requests or output files. The endpoint receives the request and selected
examples. Run `generate` only after choosing the model/provider and authorizing use
of the bank with that provider. There are no automatic retries or training jobs.

To inspect a manually obtained writer response without calling a model:

```powershell
.\.venv\Scripts\python.exe -B -m spie.forge receive --corpus artifacts\forge\bank-v1\corpus.json --request artifacts\forge\warehouse-request.json --response artifacts\forge\warehouse-response.json --platform-verifier "C:\Users\singh\Downloads\BrainBloom\lib\forge\verify.ts" --out artifacts\forge\warehouse-draft-new.json
```

The warehouse sample was proposed by the current coding assistant against the
retrieved references. It is an integration demonstration, **not output from a
fine-tuned model**. `receive` does not generate text.

## Actual training and evaluation still required

1. Select a base model, license, training environment and budget. This laptop has
   an NVIDIA MX330 with 2 GB VRAM; it is unsuitable for practical fine-tuning of
   a capable question-writing model. Use an approved hosted training service or
   a larger GPU for an open model. No data has been uploaded.
   The [training setup](../tools/forge_train/README.md) now includes a free-Colab
   notebook and private bundle for Qwen2.5-1.5B-Instruct. The real tokenizer checked
   all train/validation targets with no truncation. GPU training has not run.
   GitHub checks succeeded, but the remote is public with no configured GPU runner,
   and hosted GPU runners are paid. Nothing was pushed or dispatched. Colab browser
   access was denied; the user must open the prepared notebook or re-enable access.
2. Review a stratified sample of training targets, especially empirical claims,
   explanations, ambiguous riddles and accepted-answer variants. Quarantine bad
   targets rather than teach the writer to reproduce them.
3. Run the base model with corpus examples as a baseline. Fine-tune a copy on train
   JSONL; use validation for configuration decisions and keep test untouched.
4. Compare baseline and tuned generations on the same held-out briefs: contract
   pass rate, exact/lexical repeats, category/type compliance, independent answer
   checks where applicable, and blind human judgments of style, fairness and variety.
   A low training loss or a schema pass is not a puzzle-quality result.
5. Connect the chosen model to the writer and then the Studio authoring flow.
   Any live import/publish is a separate explicit action.

No learned model is used as the correctness or acceptance judge. Free-text drafts
remain `published: false`, `reviewStatus: draft`, `answer_correctness: unverified`.
The Studio verifier can reject editorial violations but cannot prove open-world
science facts or the uniqueness of arbitrary riddle answers. Formal certificates
must only be attached where a supported formal representation was actually checked.

## Checks performed in this implementation pass

84 affected tests passed (`test_forge`, `test_questions`, `test_audit`,
`test_chance`); `ruff check src tests` passed. The writer endpoint was exercised
with a stub, not a live model. The warehouse draft passed the real Studio verifier
with one lexical-overlap warning; its answer remains marked unverified.
The full historical engine suite has not been revalidated in this pass.

The ConceptNet and operator-model artifact hashes and the `door`/`prize` ID pins
match their recorded values. The legacy aggregate examples byte pin does NOT:
current raw aggregate is `85a6763453a79c47a60bfc2fda145c854436f960f072b8ffb822a710aa6f11a6`,
recorded expectation is `8b334f2cd8b616843042fe37702fbe058e43a712d6e378109117d279c7c7733e`.
All 20 files currently use CRLF; their contents match Git HEAD after line-ending
normalization. Even the LF-normalized aggregate differs from the recorded pin,
so CRLF alone has not explained the discrepancy. No example file was edited.
This pin is unresolved, not a passed check.
