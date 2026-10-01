# Build and use an offline workshop package

`tools/package_workshop_release.py` snapshots the checkout, builds the engine
wheel, downloads its runtime dependency wheels, and installs that wheel in a new
temporary virtual environment with `--no-index`. The source archive and wheel
include both retained coverage snapshots, the ten authored v2 definitions, static
workshop assets and source license notices. Optional full WordNet corpora are not
distributed in the package.

## Install the prepared package

The dependency wheelhouse produced on the current release machine targets
**Windows x86-64 and Python 3.12**. Python must already be installed. The source
archive is a separate snapshot for inspection and rebuilding; it is not needed
to run the installed wheel.

In PowerShell, start in the directory containing the release wheel and its
`dependencies` folder. Choose new environment and run-directory names:

```powershell
py -3.12 -m venv brainbloom-release-env
./brainbloom-release-env/Scripts/python.exe -m pip install --no-index --find-links ./dependencies ./spie-0.1.0-py3-none-any.whl
New-Item -ItemType Directory brainbloom-run
Set-Location brainbloom-run
../brainbloom-release-env/Scripts/python.exe -m spie.questions.brainbloom serve --port 8766 --no-history --no-integrations --no-oewn
```

Open <http://127.0.0.1:8766/>. This fresh run directory has no downloaded corpora,
so generation uses the bundled packs. It retains no cross-session draft history
and does not discover a sibling Studio checkout. These switches make the example
self-contained; ordinary workshop use can enable history and local integration.
Use another free port if 8766 is already in use.

To use already-installed, pinned full corpora, supply their paths with `--wordnet`
and `--oewn`, omitting `--no-oewn`. Corpus installation is an optional separate
download; see [the coverage guide](brainbloom-coverage.md). Saved bundle replay
uses the bundle's bounded snapshot, so it needs neither installed corpus:

```powershell
../brainbloom-release-env/Scripts/python.exe -m spie.questions.brainbloom check ./saved-bundle.json
```

The checksum manifest is `SHA256SUMS.json`. Keep the wheel, dependency wheelhouse,
source archive and manifests together. The checksums detect changed bytes but do
not authenticate a publisher. Do not describe this local snapshot as a signed,
published or committed release.

## Build a new package

From `engine/`, use a fresh output path. Building the wheelhouse may access the
configured Python package index. Installation and the subsequent runtime checks
are offline:

```powershell
./.venv/Scripts/python.exe -B tools/package_workshop_release.py --out artifacts/my-workshop-release --wordnet .brainbloom/wordnet.zip --oewn .brainbloom/english-wordnet-2024.xml.gz --replay-bundles artifacts/reliability-release/handoff-bundles.json artifacts/coverage-expansion/benchmark-final/expanded-bundles.json
```

Omit both corpus arguments for the bundled-pack profile alone. Additional saved
bundle arrays can follow `--replay-bundles`. The two built-in replay inputs are
`examples/workshop-handoff-bundles.json` and the revision-1 fixture. The helper
refuses an existing output directory and preserves historical packages.

`source-manifest.json` hashes every staged source file. The source ZIP fixes its
entry order and timestamps; `SHA256SUMS.json` records the final artifact bytes.
`clean-install-check.json` records the installed import path, actual dependency
versions, saved replay checks, generation profiles, corpus hashes and packaged
snapshot hashes. Replay is exercised while dictionary construction and network
sockets are blocked. Generation is exercised while network sockets are blocked.
The optional full-corpus profile repeats the generation cases using copied local
corpora, outside the checkout.

These are bounded engine checks. They do not run a production Studio database,
the external Studio editorial validator, a mobile runtime, or a human review.
Retain the separate integration and browser reports alongside a release.
