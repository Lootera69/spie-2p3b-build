# Versioned vocabulary expansion

The coverage expansion adds **coverage-v2: eight topic packs and 106 word/meaning entries**,
and optional **Open English WordNet 2024 (OEWN)**. The original twelve packs and
pinned Princeton WordNet 3.0 remain intact. No model, API key, training or network
request is used during generation or saved-bundle replay.

The new packs cover machine learning, cybersecurity, renewable energy, robotics,
plate tectonics, genetics, cricket (sport) and neuroscience. They contain 106 entries
total (machine learning has 22; each other pack has 12). Of these, **96 entries
select exact OEWN sense IDs** and have concise edited clues; **ten additional
machine-learning entries are project-authored**, identified by `authored-v2:` IDs.
The selections received a **repository editorial review**, recorded in the data, not an independent
human or subject-expert review. All generated content remains draft material.

## Install and run

From `engine/`, with the existing Python 3.12 environment:

```powershell
./.venv/Scripts/python.exe -m pip install -e .
# Optional. Keep the original corpus; do not replace it with OEWN.
./.venv/Scripts/python.exe -m spie.questions.brainbloom dictionary-install
./.venv/Scripts/python.exe -m spie.questions.brainbloom oewn-install
./.venv/Scripts/python.exe -m spie.questions.brainbloom dictionary-info
./start-brainbloom.ps1
```

Skip an install command when its corpus is already installed. Installers refuse to
overwrite files. Both retained versions of the eight small packs ship inside the
wheel and work without any corpus download. The CLI detects `.brainbloom/wordnet.zip` and
`.brainbloom/english-wordnet-2024.xml.gz`. Restart an already-running server after
installing a corpus or changing code, then reload its page.

Use `--oewn PATH` or launcher `-OpenEnglishWordNet PATH` for another location of
the **same pinned** OEWN corpus. Use `--no-oewn` to disable it. `--no-coverage`
disables the eight new packs, for baseline comparison; the original twelve packs
remain. Python callers opt into full corpora explicitly:

```python
from pathlib import Path
from spie.questions.brainbloom.service import Generator

engine = Generator(wordnet=Path('.brainbloom/wordnet.zip'),
                   oewn=Path('.brainbloom/english-wordnet-2024.xml.gz'))
```

`Generator()` includes **20 distinct bundled topic names in 28 pack-version
records** (12 original packs, eight v1 records and eight v2 records) but loads
neither full corpus. v2 expands the same eight topics introduced in v1.

## Meanings and usable coverage

Original pack names retain their existing precedence and IDs. Lookup selects a
meaning automatically and records the selected source and the reason for the
choice. Exact authored topics take precedence; coverage topics use their latest
retained version. Other choices use a deterministic capacity and match ranking.
For example, bare `cricket` selects the latest sport pack, with twelve words.
The source-qualified insect and original sport meanings remain available as
explicit overrides. The selected meaning is visible and editable in the workshop.
An alias selects a source's meaning; it is not another independent sense.

IDs beginning `wn:` keep the old corpus meanings. `oewn2024:` identifies OEWN
synsets. `coverage-v1:` and `coverage-v2:` identify versioned edited packs and their
entry meanings. Bare topic or alias lookup uses the newest reviewed pack release
available (currently `coverage-v2`); older releases remain addressable by
source-qualified ID.
No cross-source equivalence is assumed. Lookup normalization is controlled and
results retain labels and provenance. Automatic selection is a reproducible
heuristic, not proof of the user's intended sense or subject understanding. New
pack memberships are explicitly labeled
`editorial-topic-member`, rather than asserted as scientific graph relationships.

The configuration and **Vocabulary sources and usable coverage** panel distinguish:

| Metric | Definition |
| --- | --- |
| Indexed terms | Distinct lookup keys, including compounds and aliases. The combined count deduplicates keys across sources. |
| Unique senses | Source-qualified synsets or authored entry meanings. Equivalent concepts in two corpora still have two records; this is not a count of distinct real-world concepts. Pack topic IDs are reported separately as topic packs. |
| Aliases | Extra inflected forms or editorial topic aliases, counted within each source. Synonymous lemmas may share a sense without being counted as extra-form aliases. |
| Usable entry pairs | Word/meaning pairs passing the existing 3–15 A–Z filter after removing spaces/hyphens. Proper-name capitalization remains excluded in lexical corpora. This is not a guarantee of enough related entries for a puzzle. |
| Relationships | Retained directed kind/instance/part/member/substance and broader-kind edges, or explicitly editorial topic memberships. These are not newly learned reasoning rules. |
| Unique topics | Distinct bundled topic names across all retained pack versions: 20. |
| Pack versions | Loaded topic/version records: 28. The eight coverage topics each have v1 and v2 records. |

With both corpora and all packs: **156,589 distinct lookup keys**. OEWN contributes
**5,171 keys absent from the Princeton index**, including `ransomware` and
`smartphone`. Princeton remains 151,384 indexed terms and 117,659 synsets. OEWN has
156,044 indexed terms, 120,630 synsets and 212,478 lexical-sense associations.
The coverage source rows include topic names, aliases and member lemmas: v1 has
116 lookup keys and 96 word/meaning entries; v2 has 126 keys and 106 entries.
Most OEWN concepts overlap Princeton; summing the sense records does not establish
a doubling of knowledge. Each source reports its own counts and hashes.

For example, one OEWN noun can be looked up successfully yet still yield fewer
than four usable related words. Exact topic packs address that capacity problem
for their named topics. They do not provide universal encyclopaedic topic coverage.

## Provenance, licenses and reproducibility

OEWN 2024 is derived from Princeton WordNet and developed under **CC BY 4.0**.
Attribution belongs to **Princeton WordNet and the Open English Wordnet team**.
The unmodified upstream license, including the Princeton notice, ships in
`src/spie/questions/brainbloom/data/oewn-2024-license.md`. Source URLs and hashes
are pinned in `coverage_sources.py`. The 96 OEWN-derived entries are adaptations
with their changes disclosed and source license retained; keep the notices with
exports. The ten `authored-v2:` entries are original project definitions, not
OEWN senses. Each pack context reports its own origin counts and attribution.

| Artifact | SHA256 |
| --- | --- |
| Original WordNet ZIP | `cbda5ea6eef7f36a97a43d4a75f85e07fccbb4f23657d27b4ccbc93e2646ab59` |
| OEWN 2024 gzip | `e1f633b0a93758cae34ea27c44c4dad310a8af2467b155f99dd6673af697e875` |
| Coverage packs v2 | `f6bffdfde85e40dfcc6748fdf348f624022174cbe2fff631735bcbafc2931dad` |
| Coverage packs v1 | `e2ce3449bcff2183830ead449272529c032070c64e66d60c9c4e0a3f2874d1cb` |
| OEWN upstream license | `5d02a553699c4841d8b33cc5a1313cff1f96264e36e9dc98be829dfc94a6cc73` |

The installer limits compressed input to 20 MB. The loader verifies SHA256 before
parsing and caps expansion at 150 MB. It does not fetch the XML's external DTD.
The packaged pack file is also hash-verified. Live generation only traverses the
chosen source, at the existing depth limit of two and maximum of eighty words.

Rebuild either exact snapshot offline from its pinned upstream corpus, reviewed
selection table and the ten original definitions in `AUTHORED_V2` inside
`tools/coverage_build.py`. v2 is the default. Both commands refuse to overwrite
their output and verify the resulting bytes against the pinned snapshot hash:

```powershell
./.venv/Scripts/python.exe -B tools/coverage_build.py --source .brainbloom/english-wordnet-2024.xml.gz --out rebuilt-coverage-packs-v2.json
./.venv/Scripts/python.exe -B tools/coverage_build.py --version v1 --source .brainbloom/english-wordnet-2024.xml.gz --out rebuilt-coverage-packs-v1.json
Get-FileHash rebuilt-coverage-packs-v2.json
Get-FileHash rebuilt-coverage-packs-v1.json
```

The builder intentionally reproduces v1's LF and v2's CRLF line endings on all
operating systems. Frozen files retain their original review and transformation
text. Fresh contexts attach that metadata and the snapshot hash from the selected
version, plus a provenance note that distinguishes authored additions from
upstream selections. An upstream corpus hash is separate from the snapshot hash
and the digest of the individual pack.

Every generated bundle embeds its bounded entries, original selected definitions,
edited clues, source IDs, paths, licenses and hashes. Existing envelope versions
are retained. Replay uses the saved snapshot even when all installed corpora and
packs are unavailable. Replay detects inconsistent edits relative to the saved
content; hashes do not authenticate the author or prove factual definitions.

For an update, create a **new** corpus filename, namespace and pack version.
Inspect the upstream license, record its URL and SHA256, explicitly review changed
senses/clues and rerun the benchmark and replay tests. Retain old sources and
bundles. Do not repoint an old version constant at newer meanings or automatically
fetch a moving `latest` release during generation.

## Measurements and limitations

`tools/coverage_benchmark.py` uses the four specialist topics already added by the
reliability release and the eight additional topics. It records three profiles:
original packs plus Princeton; all packs plus both corpora with explicitly
selected latest coverage meanings; and the expanded configuration using the same
automatic selection as the workshop. `--coverage-version v1` reruns the explicit
expanded profile against legacy packs; the default-flow profile still measures
the live latest-version policy. Each profile records its actual selected source
namespaces. A missing exact topic is counted as an unsupported case; unresolved
component words are not silently substituted for a missing phrase such as `machine learning`.

Each topic has fourteen cases: all six formats at medium with seeds 7 and 31,
plus a hard crossword and a hard route activity with seed 7. History is disabled.
The historical v1 comparison recorded **100/168 cases generated before; 168/168
after**, with all generated bundles replayed. A separate pre-fix v2 audit recorded
**168/168 explicitly selected cases generated and replayed**, with **96 independent
quiz calculations and zero incorrect answers**. These saved measurements do not
stand in for a fresh run of the default selection policy. Crossword,
counting and route correctness are rechecked by their existing independent validators.
This is a selected regression set, not a population-wide success rate.

```powershell
./.venv/Scripts/python.exe -B tools/coverage_benchmark.py --out artifacts/my-coverage-run
./.venv/Scripts/python.exe -B tools/coverage_benchmark.py --coverage-version v1 --out artifacts/my-legacy-coverage-run
./.venv/Scripts/python.exe -B tools/coverage_census.py --out artifacts/my-coverage-census.json
./.venv/Scripts/python.exe -B tools/coverage_query_audit.py --generate 8 --out artifacts/my-coverage-query-audit.json
./.venv/Scripts/python.exe -m pytest tests/test_brainbloom_coverage.py tests/test_coverage_versions.py tests/test_coverage_census.py tests/test_coverage_query_audit.py
```

The census evaluates each source-qualified lexical synset and each retained pack
version once, grouping v1 and v2 separately. Its capacity thresholds count usable
entries, not successfully generated puzzles. The query audit includes each of the
eight coverage topic names once, reports raw source-qualified choices separately
from automatic selection, and optionally generates and replays a bounded sample.
Use `--packs-only` with either reporting tool for an offline run without corpora.

The maintained tools were rerun on 1 October 2026 after the lookup and provenance
repairs: **100/168 baseline, 168/168 explicit v2 and 168/168 automatic-default
cases generated and replayed**. Both expanded profiles checked 96 quiz answers
independently, with zero mismatches. The query audit generated and replayed all
16 sampled cases across the eight coverage topics. See
`artifacts/coverage-integration-2026-10-01/coverage-reproducibility/report.md` for
the bounded test scope, source verification, commands and current reports.

Read `artifacts/coverage-expansion/implementation-report.md` for historical v1
evidence and `artifacts/coverage-audit-2026-10-01/audit-report.md` for the pre-fix v2
audit. Keep new release evidence in a separate directory; neither historical
package is the current release. The eight packs are useful vocabulary
for letter games, clue crosswords and fictional reasoning labels. They do not add
machine-learning inference, medical reasoning, cricket strategy or new puzzle rules.
Word-order variants remain repetitive; the category label does not change that.
The full lexical corpus is not filtered for age suitability. Human ratings of
clarity, enjoyment and difficulty, and independent subject-expert review, remain absent.


