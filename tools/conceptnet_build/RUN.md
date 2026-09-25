# Running the distributed 2.3b build on GitHub Actions

This is the manual fallback. Normally I (Claude) drive these steps with the already-authenticated
`gh` CLI and pause to confirm with you right before the public push. The commands are here so you
can run them yourself, or check exactly what I am about to do.

## What this does

Shards the ~3,244-word certify gate across GitHub Actions runners (GitHub Pro → 40 concurrent),
merges the per-shard verdict caches, and returns one `verdicts.merged.tsv`. Nothing about the
puzzles or the artifact is decided in the cloud — the runners only *prove* verdicts that are then
**validated against this machine** before any of them are trusted. See `build-2p3b.yml`.

## Prerequisites (one-time, already done)

- `gh auth login` — authenticated as your GitHub account, scopes include `repo` and `workflow`.
- The build tool committed, including `tools/conceptnet_build/.cache/edges.tsv.gz` (~444KB, the
  only data input the runners need — **not** the 497MB dump).

## 1. Create the (temporary) public repo and push

The repo must be **public** so Actions minutes are free. It exists only for this run and is deleted
after. No secrets live in the tree.

```bash
git init
git add -A
git commit -m "SPIE 2.3b distributed certify-gate build"
gh repo create spie-2p3b-build --public --source=. --push
```

## 2. Trigger the matrix build

```bash
gh workflow run build-2p3b.yml
gh run watch
```

80 shard jobs run 40-at-a-time (~2 waves), each proving ~40 words (~90 min), then one `merge` job
concatenates them. Expect ~3h wall.

## 3. Download the merged verdicts

```bash
gh run download --name verdicts-merged --dir tools/conceptnet_build/.cache/
```

## 4. Validate cloud verdicts against the local ground truth (NON-NEGOTIABLE)

The local build has been running the whole time as the oracle. Diff the cloud verdicts against it
on every shared dependency-key:

```bash
.venv/Scripts/python.exe -m tools.conceptnet_build.merge_verdicts validate \
  --against tools/conceptnet_build/.cache/verdicts.tsv \
  tools/conceptnet_build/.cache/verdicts.merged.tsv
```

- **Exit 0, "VALIDATE OK":** every shared key agrees → the cloud toolchain reproduces this machine
  byte-for-byte. Safe to trust.
- **Non-zero:** hard stop. Discard the cloud verdicts entirely. The local build finishes on its own.

## 5. Finish the build locally (only after VALIDATE OK)

Stop the local build, install the merged cache as the verdict log, and relaunch. Round 1 becomes
all cache hits; only the few keys newly exposed in fixpoint rounds 2+ are gated locally, then the
artifact is emitted.

```bash
# stop the running local build (it has served its purpose as oracle), then:
cp tools/conceptnet_build/.cache/verdicts.merged.tsv tools/conceptnet_build/.cache/verdicts.tsv
powershell -NoProfile -ExecutionPolicy Bypass -File tools/conceptnet_build/run_build.ps1
```

## 6. Delete the public repo

```bash
gh repo delete spie-2p3b-build --yes
```

Deleting removes GitHub's copy; it cannot recall any external copy already taken while public
(accepted risk for a brief, unannounced repo with no secrets).
