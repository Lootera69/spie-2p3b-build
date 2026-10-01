# BrainBloom symbolic generator v1: conditional-reasoning specification

**Current release:** see [the six-format workshop](brainbloom-workshop.md) for v2,
which adds the other platform formats and categories. This document describes the
original conditional engine, retained so v1 draft bundles can still be reproduced.

`python -m spie.questions.brainbloom` invents conditional-reasoning quiz questions
for the BrainBloom bank **without any language model in the answer path**. Every
question is a small propositional-logic problem; every answer is proven correct two
independent ways and fails closed if they disagree. It is a sibling of, and
deliberately separate from, the corpus-conditioned LLM writer in
[the question writer doc](brainbloom-generator.md): that path *writes* free-text in
the bank's style and leaves answers `unverified`; this path *constructs* questions
whose answers carry a checkable certificate.

This is the same discipline as the puzzle engine (`creativity from search,
correctness from formal solvers`), narrowed to the one question family it can prove:
conditional (implication-chain) reasoning.

## Start the workshop on Windows

From `engine/` in PowerShell:

```powershell
./start-brainbloom.ps1
```

The launcher opens `http://127.0.0.1:8766`, uses this project's `.venv`, and keeps
the server in the current terminal. Stop it with **Ctrl+C**. It detects the known
sibling bank (`../puzzle-batch/output/validated`) and Studio verifier
(`../../BrainBloom/lib/forge/verify.ts`, when Node is installed); both are read-only.
Use `-Port 8768`, `-NoBrowser`, `-Bank PATH`, or `-PlatformVerifier PATH` as needed.
The setup text in the form shows which checks are active.

If setting up a fresh checkout, install Python 3.12+ and run:

```powershell
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
```

Choose the setting, question format, difficulty and count, then **Generate questions**.
Try an answer, reveal the reasoning, and download the draft JSON. The preview breaks
the deduction into individual steps. Short batches show the editorial rejection
reasons; if every item is rejected, the download is labelled a rejection report.

## Non-LLM development direction

LLMs are excluded from generation, checking and explanation in this path. Classical
ML and mathematical methods are allowed. The current release uses symbolic logic
and controlled language only. Future additions can use constraint search and
evolutionary search to propose structures, and a non-LLM ranker or difficulty model
to score them. Such scores must remain separate from formal correctness checks.
Player-calibrated difficulty needs player outcomes; the existing question bank alone
does not provide that evidence. No such model has been trained in this release.

## What it produces

A draft **bundle** (canonical JSON) of one or more items in BrainBloom's existing
draft contract — `type`, `category`, `difficulty`, `title`, `question`, `choices`,
`correctAnswer`, both explanations, `lessonContent`, `lessonGroup`, `xpReward` —
each paired with a machine-checkable **proof**. The bundle is always an unpublished
draft (`published: false`, `reviewStatus: draft`) and records that no learned model
was used. It is never imported or published; that remains a separate human action.

Supported inputs (this release, deliberately narrow):

- **category**: `logic` only.
- **topic**: `warehouse`, `library`, `laboratory`, `delivery` (a controlled noun +
  attribute vocabulary per theme).
- **type**: `multiple-choice`, `true-false`.
- **difficulty**: `easy` / `medium` / `hard` = exactly 1 / 2 / 3 reasoning steps.
- **count**: 1–20; **seed**: 0–4294967295.

Any other value is rejected at `Request` construction rather than silently coerced.

## How an answer is certified

Each question is a `Problem`: a set of boolean attributes, a handful of implication
`Rule`s (`before → after`), and known `facts`. The generator builds an implication
chain of the requested depth, adds a decoy rule, and picks a direction — **forward**
(follow the chain) or **contraposition** (rule out the sufficient conditions) — then
asks whether a candidate literal is *entailed by the stated rules and facts*.

Entailment is decided **twice, by code that shares nothing**:

1. **Z3** (`spie.questions.prover.decide`) — the claim is valid iff `Not(Implies(...))`
   is unsatisfiable; an `unknown` result raises rather than being trusted as a proof.
2. **Exhaustive truth tables** (`logic.worlds`) — enumerate every interpretation of the
   attributes, keep those satisfying the facts and rules, and check the claim holds in
   all of them. This is a plain Python enumerator, not a second call into Z3.

`logic.analyze` runs both and **raises on any disagreement** — on satisfiability
(`Z3/truth-table satisfiability disagreement`) or on any candidate's entailment
(`Z3/truth-table entailment disagreement`). Contradictory premises are refused
outright, so a question can never be made "vacuously true" by an inconsistent setup.
For every non-entailed choice the proof stores a concrete **counterexample** world.

Multiple-choice questions must have **exactly one** entailed option (checked, not
assumed); true/false questions state a single claim and answer with its verdict.

## Difficulty is measured, not asserted

`difficulty` is the **exact minimal number of rules** needed for the deduction, found
by searching rule subsets in increasing size (`logic.minimum_rules`). The generator
recomputes this for the constructed question and **rejects it unless the measured
minimum equals the requested depth** (`Difficulty mismatch`). Difficulty is therefore
a structural property of the proof, not a label — though it is a *structural* heuristic
and is **not** calibrated against real players.

## Determinism and replay

Randomness comes from `derive_rng` (a SHA-256-seeded RNG keyed on version, topic,
difficulty, type, and seed), so identical inputs yield **byte-identical** bundles,
even across processes with different `PYTHONHASHSEED`. Bundles serialize through the
canonical `compact`/`digest` helpers shared with the puzzle engine.

`check` (or `verify_bundle`) does not trust a saved stamp: it **re-generates from the
recorded seeds and re-proves**, then rejects any bundle whose item or proof does not
match the fresh result (`does not match freshly checked generation`), whose import
block was flipped to published/altered (`unpublished draft`), or that duplicates or
mis-seeds an item. Tampering with the question, answer, choices, explanation, or the
`agree` flag is caught this way.

## Novelty, contract, and the optional editorial gate

Within a batch and against an optional **read-only** bank, candidates are excluded by
**lexical** duplicate checks only (stem key + shingle overlap, via `spie.forge.corpus`);
structural/template novelty is explicitly *not* claimed. Every item must pass the same
BrainBloom shape contract (`spie.forge.contract.issues`) the LLM path uses. If a local
Studio `verify.ts` is supplied, its editorial verdict can still reject a formally
correct draft; accepted proofs are kept aligned with accepted items, and a short batch
is reported as `complete: false` rather than padded.

## Commands (from `engine/`)

Generate a draft bundle to a new file (the tool refuses to overwrite):

```bash
./.venv/Scripts/python.exe -m spie.questions.brainbloom generate --topic warehouse --difficulty hard --count 3 --seed 7 --out drafts/warehouse.json
```

Independently re-generate and re-prove a saved bundle:

```bash
./.venv/Scripts/python.exe -m spie.questions.brainbloom check drafts/warehouse.json
```

Run the local preview (loopback only; no publishing endpoint):

```bash
./.venv/Scripts/python.exe -m spie.questions.brainbloom serve --port 8766 --open
```

Optional flags: `--bank PATH` (a read-only validated bank, for lexical de-duplication
only) and `--platform-verifier PATH` (a local Studio `lib/forge/verify.ts`). Neither
writes to the bank, Firestore, or Studio. `generate` exits non-zero if the batch is
incomplete, and `2` on any error or an existing output path — so it composes in scripts.

## The local preview is a workshop, not a service

`spie.questions.brainbloom.web` serves a single-page workshop on `127.0.0.1` and is
**hardened to stay local**:

- Binds loopback only and handles requests **serially** — Z3's global context is not
  shared across threads.
- Rejects any request whose `Host`/`Origin` is not the bound localhost (a DNS-rebinding
  guard), sends `Content-Security-Policy: default-src 'none'`, `Cache-Control: no-store`,
  and `X-Content-Type-Options: nosniff`.
- Accepts only `POST /api/generate` with a 1–4096-byte `application/json` body under a
  read timeout; there is **no** publish, import, upload, or filesystem endpoint.
- Times out idle connections before header parsing so browser preconnections cannot
  hold the serial server indefinitely; truncated request bodies are rejected.
- Fails closed: if the formal gate disagrees, it returns `500` and releases no items.
- Consumes the request body on every path — including rejections — so a settled reply
  closes the socket cleanly instead of resetting it (a Windows `ConnectionAbortedError`).

## Scope and honest limits

- A proof certifies a **logical consequence of the stated assumptions**, not a
  real-world fact. The rendered rules are premises to reason from, not truth claims.
- Difficulty is a structural rule-count heuristic, **not** player-calibrated.
- De-duplication is **lexical only**; semantic or template novelty is not established.
- Drafts are **unpublished** and require human editorial review before any import.
- One question family (conditional reasoning), two formats, four themes — by design.
- Studio's stricter word-overlap duplicate rule can reject most of a same-theme batch.
  A tested warehouse batch of three retained one. This is reported as incomplete;
  changing wording to bypass the quality gate is not a substitute for new families.
- The JSON envelope is accepted by the existing Forge batch verifier's `loadItems`
  contract. No direct Studio draft-import screen was found or added. Live app import
  remains separate; the existing bulk seeder marks content approved/published and
  must not be used as an unpublished-draft importer.

## Tests

`tests/test_brainbloom_symbolic.py` exercises the whole path: exhaustiveness over every
supported input, agreement between Z3 and the truth-table checker (with counterexamples),
byte-identical reproduction across processes, tamper and publish rejection in `check`,
fail-closed behaviour when a solver disagrees or returns `unknown`, the load-bearing
difficulty measurement, lexical de-duplication, batch variation, CLI replay/no-overwrite,
and the loopback web server's origin, contract, and fail-closed guarantees.
