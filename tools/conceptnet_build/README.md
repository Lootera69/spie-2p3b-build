# `tools.conceptnet_build` — the offline ConceptNet vocabulary builder (Step 2)

Offline, deterministic pipeline that derives SPIE's **additive** vocabulary layer
`src/spie/conceptnet_data.py` from a pinned ConceptNet 5.7.0 assertions dump. It reads the dump,
keeps only single-token English terms and the six relation kinds the engine models
(`IsA`, `UsedFor`, `CapableOf`, `HasProperty`, `Causes`, `PartOf`), derives puzzle-affordance tags
from a fixed rule table plus IsA inheritance, and **retains only words that provably invent a
formally certified puzzle** — every candidate is run through the unchanged `validate → verify →
certify` gate (Z3 + explicit search + clingo, cross-checked). No learned model touches acceptance.

This package is **not shipped**: it lives outside `src/`, is excluded from `pytest`'s `testpaths`,
and is not covered by `ruff check src tests`. The emitted artifact `src/spie/conceptnet_data.py`
imports only `hashlib`.

**Additivity invariant (what makes the layer safe):** `expand` is *outgoing-only*, and adding an
out-edge *from* a curated concept is forbidden, so appending ConceptNet words can never change any
existing word's expansion. The curated core stays the default; the sacred invariants
`invent('door').id == 'gen_0000_connect_negate'` and
`invent_traced('prize')[0].id == 'gen_0000_chain_plain'` are preserved by construction.

## The pinned source dump (provenance)

| field | value |
|---|---|
| ConceptNet version | `5.7.0` |
| file | `conceptnet-assertions-5.7.0.csv.gz` |
| size | `497,963,447` bytes (~498 MB) |
| sha256 | `accd65fe94038584295574ddc26e1500c1919c8c4532bf771811cafd0948af7e` |

The dump is listed on the ConceptNet Downloads wiki
(https://github.com/commonsense/conceptnet5/wiki/Downloads); the 5.7.0 edges file is at
`https://s3.amazonaws.com/conceptnet/downloads/2019/edges/conceptnet-assertions-5.7.0.csv.gz`.
The sha256 above is the real guarantee — verify it after downloading. Place the file at
`tools/conceptnet_build/.cache/conceptnet-assertions-5.7.0.csv.gz`. The `sha256`, version, dump
name and every build parameter are also recorded inside the artifact
(`conceptnet_data.SOURCE_DUMP_SHA256`, `CONCEPTNET_VERSION`, `BUILD_PARAMS`).

## Regenerate the artifact (local, canonical)

Run from the `engine/` directory. This is the one command; it is safe to re-run and **resumes**
from the durable verdict cache, reaching the byte-identical artifact:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File tools/conceptnet_build/run_build.ps1
```

which launches, detached, the equivalent of:

```bash
python -m tools.conceptnet_build --dump tools/conceptnet_build/.cache/conceptnet-assertions-5.7.0.csv.gz --z3-rlimit 8000000
```

Pinned build parameters (also in `BUILD_PARAMS`): `cap=3500`, `max_hops=2`, `seeds=9`,
`max_out_edges=6`, `min_out_edges=1`, `isa_hops=3`, `weight_min=1.0`, `z3_rlimit=8000000`,
`target=0` (no truncation), band `size_min=1000 ≤ len ≤ size_max=3500`. Do **not** lower `seeds`
or `max_hops` to go faster — that weakens the exhaustive gate and changes the artifact.

**Reproducibility.** The gate verdict is a pure function of a word's depth-2 neighbourhood; a
deterministic Z3 `rlimit` (not a wall-clock timeout) makes every verdict machine-independent, so a
fresh run reproduces the checked-in artifact byte-for-byte. Verdicts are written through per-word
to `.cache/verdicts.tsv`, so an interrupted run loses no proof. The current artifact:
**3,244 records**, `ARTIFACT_HASH = sha256:41a91106c6be115650a09a78c007bbfbc83b0c9e380b4162e29262f256f35708`.

## License

`src/spie/conceptnet_data.py` is an adaptation of CC BY-SA 4.0 material and is therefore itself
distributed under **CC BY-SA 4.0** (share-alike). Attribution and the full notice travel in the
repository-root `NOTICE` file; `conceptnet_data.CONCEPTNET_ATTRIBUTION` carries the same text.

## Distributed (cloud) fallback

`RUN.md` documents the optional GitHub Actions path (`build-2p3b.yml`) that shards the certify gate
across runners. It is an outward-facing, user-gated step; the local command above already produces
the identical artifact offline with no network.
