# Train the BrainBloom question writer

This is real supervised QLoRA training for a language model, separate from
`tools/policy_train` and its mutation-selection weights. The free-Colab candidate is
`Qwen/Qwen2.5-1.5B-Instruct` at immutable revision
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`. Its Apache-2.0 license was checked against
Hugging Face metadata. The older GitHub route defaults to `Qwen/Qwen2.5-7B-Instruct`.
The adapter proposes questions. It does not judge correctness or publication.

## Current checked state

Local data/trainer-boundary tests pass. The actual 1.5B model tokenizer checked all
3,965 train and 490 validation rows: 2,246,381 training tokens, 278,817 validation
tokens; longest record 762 tokens. Prompt masking/prefix alignment passed, with
zero truncation. Held-out test inputs were not tokenized or used for previews.
CUDA installation, QLoRA training and real question generation have **not** run.
108 relevant lightweight tests and lint passed. A separate real-library CPU test
with a tiny random synthetic Qwen/LoRA model verified exact weight agreement after
checkpoint resume; this is not question-bank training or a GPU integration test.
The notebook also passed nbformat schema and Python cell-syntax validation.
There is no trained question-writer adapter. Colab browser access was denied;
the package is prepared locally for the user to open. No corpus upload occurred.

GitHub checks succeeded: `Lootera69/spie-2p3b-build` is public, Actions is enabled,
and no GPU runners or runner variables are configured. Hosted GPU larger runners
are paid; the selected path is free Colab, not a paid GitHub run.

## Free Colab path (selected)

Build the private bundle and notebook, from `engine`, using a NEW output directory:

```powershell
.\.venv\Scripts\python.exe -B -m tools.forge_train.colab --corpus training\brainbloom\corpus.json --out artifacts\forge\colab-v1 --revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306
```

Upload `BrainBloom-Free-Training.ipynb` in Colab. Select a free T4 runtime, then Run
all; upload `brainbloom-training.zip` and approve Drive access when prompted. Do
not upgrade or purchase compute. Keep the notebook and Drive outputs private.
The ZIP contains only reviewed source, requirements and the prepared corpus,
with per-file hashes. The notebook also pins the ZIP hash and refuses mismatches.

The notebook uses uv 0.12.19 from PyPI to create a managed Python 3.12 Linux venv,
independent of Colab's notebook-kernel Python. It verifies the child interpreter
version before installing the pinned training dependencies. It does not change
Colab's preinstalled packages or remove the trainer compatibility check.
It runs a smoke benchmark, reports a measured estimate, then runs one
full epoch if the training-only estimate is at most eight hours. This is not a
promise of quota or completion: free sessions may end at any time. Setup, previews
and validation take additional time. No keep-alive or quota bypass is implemented.

Full training uses 13 microbatches per optimizer update: all 3,965 rows exactly once
in 305 updates. Whole groups avoid partial-group resumption issues in the pinned
Trainer. Smoke uses 16 microbatches/update on 64 rows for eight updates; full-run
ETA scales the measured per-example time, and is only a rough estimate.

Drive checkpoints are saved every ten updates and sealed with file hashes only
after saving finishes. Resume checks model, corpus, code, package versions and
checkpoint integrity; it never silently restarts a changed run. Rerun the notebook
after reconnecting. A run interrupted before its first complete checkpoint needs
a new RUN_NAME. Checkpoints are recovery aids, not byte-reproducibility guarantees
across different GPUs. Google Drive mounting may need the user's approval.

After training, notebook fields accept category, question type, difficulty and
topic and generate one draft at a time with the new adapter. These do not invoke
paid APIs or publish to the app. The existing endpoint generator supports batched
requests; notebook-local inference intentionally keeps one question per call.

The user's Colab banner now says Colab is included in Google AI Plans; the earlier
Google One page check was insufficient to rule out that benefit. Exact included
compute units, eligibility and activation status remain unverified. Do not buy
additional compute or provision billable Cloud resources based on an assumed allowance.

### Repair the original notebook's Python-version assertion

The first release incorrectly required the notebook kernel itself to use Python
3.10–3.12. Only the isolated trainer needs a supported Python version. To regenerate
just the notebook while preserving the existing ZIP and code hashes:

```powershell
.\.venv\Scripts\python.exe -B -m tools.forge_train.colab --reuse-bundle artifacts\forge\colab-v1\brainbloom-training.zip --out artifacts\forge\colab-v1\BrainBloom-Training-Python312.ipynb
```

Upload the repaired notebook and reuse the same ZIP and RUN_NAME. Its new local
environment path avoids reusing or overwriting an incompatible old venv.

Sources checked: [Google AI plans](https://one.google.com/about/google-ai-plans/),
[Colab FAQ](https://research.google.com/colaboratory/faq.html).

## Optional GitHub route (not selected; no upload or dispatch)

GitHub Actions schedules the work; it does not automatically supply a GPU on an
ordinary `ubuntu-latest` runner. This configuration requires a Linux NVIDIA runner
with at least 14 GiB total and 12 GiB free VRAM and 30 GiB free disk. A 16-24 GB GPU
is the intended starting point; actual fit/speed still need the smoke test.
The checked GitHub Linux GPU rate was $0.052/minute ($3.12/hour); larger runners
require an eligible organization and do not use included free minutes. A registered
GPU self-hosted runner also works. No runner is provisioned by this workflow.

## Dataset and repository

Use a **private** repository. Do not commit the question bank to a public remote
and expect the workflow's privacy check to undo that exposure. The known local
remote is `Lootera69/spie-2p3b-build`; it is public and must not receive the bank.

The prepared bank has 4,974 usable candidates from 5,002 production rows:
3,965 train, 490 validation, 519 test. The 28 quarantined records are excluded.
Source IDs, file hashes, split groups and metadata are preserved. Imported
`validated` status does not establish human approval or factual accuracy.

Stage the already-prepared corpus locally, from the engine directory:

```powershell
.\.venv\Scripts\python.exe -B -m tools.forge_train stage --corpus artifacts\forge\bank-v1\corpus.json --out training\brainbloom\corpus.json
```

This target is gitignored deliberately. Only after checking that the selected
remote is private should the reviewed corpus be explicitly added for upload.
Never blanket-stage this checkout: it contains unrelated existing work.

Files needed in the private training repository:

- `.github/workflows/train-forge.yml`
- `tools/forge_train/` and `src/spie/forge/`
- `src/spie/__init__.py` (the existing lightweight package initializer)
- `tests/test_forge.py`, `tests/test_forge_train.py`
- `training/brainbloom/corpus.json`

The workflow sets `PYTHONPATH=src` and does not need the old solver-search trainer.

## Runner and dispatch

Set the repository variable `FORGE_GPU_RUNNER` to the actual registered runner
label encoded as JSON. Examples of the **format**, not verified runner names:

```json
"your-github-gpu-runner-name"
```

or, for an owned/approved self-hosted Linux GPU runner:

```json
["self-hosted", "linux", "x64", "gpu"]
```

Preflight fails if the variable is absent, the repository is public, the timeout
is outside 10-180 minutes, corpus hashes/counts disagree, or split groups leak.
It never silently falls back to CPU training. A label alone does not prove that a
runner exists, is online, or is affordable; check the account before dispatching.

Once the files and runner are available, use the manual **Train BrainBloom question
writer** workflow. Start with `mode=smoke`: eight optimizer updates on at most 64
training rows and 16 validation rows. Inspect its logs and artifacts before running
`mode=full`: one epoch across all 3,965 training rows, validation on 490 rows. The
519 test rows are not used for training, configuration selection or previews.

`max_minutes` bounds the GPU job, including setup. It is a time limit, not a money
budget or runtime estimate. The default is 120 minutes. Check runner price and
account spending controls before starting; the code cannot infer those limits.

## What is actually trained and retained

- Base weights are loaded from the recorded commit, in 4-bit NF4, with remote
  model code disabled. LoRA updates rank-16 projection adapters.
- Loss is applied only to assistant output tokens. The code verifies chat-template
  prefix alignment. It fails on oversized examples instead of silently truncating
  answers or pretending all rows were trained.
- The run fails if adapter weights did not change, no optimizer step completed,
  or train/validation losses are non-finite. Loss is a fitting diagnostic, not a
  puzzle-quality or correctness verdict.
- Checkpoints are saved every ten updates, retaining two. Actions uploads the run
  directory even after failure where possible; an artifact is not proof of success.
- `run.json` distinguishes `starting`, `adapter_saved`, `smoke_completed`, and
  `full_epoch_completed`. It records model/corpus hashes, selected source IDs,
  package versions, actual row counts, optimizer steps and parameter fingerprints.
- `adapter/` contains PEFT weights and tokenizer files. It needs the exact base
  model revision recorded in `run.json` to be used for inference.
- `previews.json` compares greedy base-model and tuned-model drafts for up to four
  validation briefs using TRAIN-only example retrieval. It reports deterministic
  contract/lexical-duplicate checks, not an AI judge. Human review is still needed.
- Artifacts expire after seven days unless downloaded/retained elsewhere. No model
  is automatically uploaded to a public model hub, and no question is published.

The dependency pins define a proposed Linux CUDA environment. They have not been
installed/tested on a GPU in this session. A fixed seed and recorded versions help
reproduce a run but do not promise byte-identical floating-point training across GPUs.

## After successful training

Download the adapter, `run.json` and comparison drafts. Evaluate the full-run model
against the base using fixed held-out requests, then independent answer checks
where applicable and human review for style, ambiguity and usefulness. Better
training loss alone is insufficient. Serve the chosen model plus adapter behind
the existing `spie.forge generate` endpoint interface; a separate reviewed publish
step remains necessary for the Studio/Flutter content pipeline.
