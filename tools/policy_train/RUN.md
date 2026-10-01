# `tools.policy_train` — the frozen SPIE decision-model trainer

Offline trainer for the propose-only decision model (Item 3, Phase C3). It runs SPIE against itself
to harvest a corpus of `(parent-context -> child-survived)` examples, fits a tiny disjoint-LinUCB
model (per-operator ridge stats, Li et al. 2010) **once**, and freezes it into the checked-in
artifact `src/spie/decision_model.py`. At runtime `spie.decision.FrozenProposer` loads it and only
*proposes* which operator to try; the unchanged `validate -> verify -> certify` gate remains the sole
judge of acceptance, and the model never learns online.

This package is **not shipped** (it lives outside `src/` and is excluded from `pytest`'s testpaths)
and imports `spie` only to reuse its search, feature and ridge math — the emitted artifact itself
imports nothing but `hashlib`.

## Prerequisites

- Python 3.12 and the pinned solver toolchain: `pip install -r requirements-build.txt`
  (z3 + clingo; the `==` pins are what make a verdict reproduce across machines).

## Commands

Run from the `engine/` directory.

```bash
python -m tools.policy_train build
```

Harvest the corpus over the pinned grid, fit the weights, and (re)write `src/spie/decision_model.py`.
Logs the corpus size, survivor count, operator count and the emitted `ARTIFACT_HASH` to stderr.

```bash
python -m tools.policy_train check
```

Regenerate the weights in memory and assert the emitted module is **byte-identical** to the
checked-in artifact. Exit 0 = reproduced; exit 1 = weights or formatting drifted. This is the
reproducibility proof and needs no network. `--out PATH` targets a different artifact path.

```bash
python -m tools.policy_train report
```

Print the frozen model's in-sample calibration on the corpus (base rate, Brier, Brier skill, ECE) —
**reported, never a gate** (mirrors the Gate G5 discipline).

## The pinned build configuration

Held in `build.py` and written into the artifact's `BUILD_PARAMS` so anyone can reproduce it:

- **seed populations** — four hand-authored puzzle triples, giving the explorer distinct starting
  niches.
- **integer seeds** `0, 1, 2` and **iterations** `50` per run (4 populations x 3 seeds x 50 = 600
  MAP-Elites iterations total).
- **alpha** `1.0`, **ridge** `1.0`, **dim** `7` — imported from `spie.context_policy` /
  `spie.mapelites` so train and inference share one feature/hyper-parameter definition (no skew).

Survival is deliberately rare (a few percent), so the grid is sized to harvest enough absolute
positives; the model is a modest-but-honest proposer, and its quality never affects correctness or
determinism.

## Reproducibility in CI

`.github/workflows/train-policy.yml` (`workflow_dispatch`) runs `policy_train check` on
`ubuntu-latest` with the pinned toolchain to prove a clean runner regenerates the checked-in weights
byte-for-byte. Running it requires a git repository and push access — an outward-facing step; local
`check` already delivers the same guarantee offline.
