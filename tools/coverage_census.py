"""Read-only census of the installed dictionary's bounded vocabulary capacity.

Run from engine: python tools/coverage_census.py --out census.json
Use --packs-only for an explicitly corpus-free, offline smoke run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

from spie.forge.corpus import digest
from spie.questions.brainbloom import coverage_sources, lexicon
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.vocabulary import ALIASES, PACKS

BUCKETS = (
    ("0", 0, 0),
    ("1-3", 1, 3),
    ("4-7", 4, 7),
    ("8-11", 8, 11),
    ("12-19", 12, 19),
    ("20-79", 20, 79),
    ("80", 80, 80),
)
THRESHOLDS = (4, 8, 12, 20)


def cached_entries(dictionary):
    """Reuse the exact engine function with a private, cached source helper.

    Its traversal code is unchanged. Private globals avoid monkeypatching the
    engine, and eliminate a licence-file read/hash for every OEWN sense.
    """
    metadata = coverage_sources.source()
    namespace = dict(Dictionary._entries.__globals__)
    namespace["coverage_sources"] = SimpleNamespace(
        **{**vars(coverage_sources), "source": lambda: dict(metadata)}
    )
    function = FunctionType(
        Dictionary._entries.__code__,
        namespace,
        Dictionary._entries.__name__,
        Dictionary._entries.__defaults__,
        Dictionary._entries.__closure__,
    )
    return function.__get__(dictionary, Dictionary)


def census(dictionary, *, weakest_limit=10):
    """Count each lexical synset and each retained editorial pack version once."""
    if not 0 <= weakest_limit <= 100:
        raise ValueError("weakest_limit must be between 0 and 100")
    groups = [
        ("authored-v1", "topic_pack", ["pack:" + p for p in PACKS]),
        *[
            (
                version,
                "topic_pack",
                {
                    p["id"]
                    for p in dictionary.coverage["packs"]
                    if p["id"].startswith(version + ":")
                },
            )
            for version in sorted(dictionary.coverage.get("versions", {}))
        ],
        ("wn30", "source_qualified_synset", dictionary.synsets),
        ("oewn2024", "source_qualified_synset", dictionary.oewn_synsets),
    ]
    entries_for = cached_entries(dictionary)
    sources = []
    for source_id, unit, senses in groups:
        buckets = {label: 0 for label, _, _ in BUCKETS}
        thresholds = {f">={n}": 0 for n in THRESHOLDS}
        weakest = []
        evaluated = 0
        for sense in sorted(senses):
            entries, _ = entries_for(sense)
            capacity = len(entries)
            bucket = next((label for label, low, high in BUCKETS if low <= capacity <= high), None)
            if bucket is None:
                raise ValueError(f"Capacity outside census buckets: {sense}: {capacity}")
            buckets[bucket] += 1
            evaluated += 1
            for threshold in THRESHOLDS:
                thresholds[f">={threshold}"] += int(capacity >= threshold)
            if weakest_limit:
                weakest.append((capacity, sense))
                weakest.sort()
                del weakest[weakest_limit:]
        sources.append(
            {
                "source_id": source_id,
                "evaluation_unit": unit,
                "evaluated_sense_count": evaluated,
                "capacity_buckets": buckets,
                "threshold_counts": thresholds,
                "weakest_examples": [{"sense": sid, "capacity": count} for count, sid in weakest],
            }
        )
    return {
        "schema_version": 1,
        "evaluated_sense_count": sum(s["evaluated_sense_count"] for s in sources),
        "evaluated_unique_topic_count": len(
            set(PACKS) | {p["topic"] for p in dictionary.coverage["packs"]}
        ),
        "evaluated_pack_version_count": sum(
            s["evaluated_sense_count"] for s in sources if s["evaluation_unit"] == "topic_pack"
        ),
        "sources": sources,
        "installed_configuration": dictionary.configuration(),
        "implementation_sha256": {
            "lexicon": hashlib.sha256(Path(lexicon.__file__).read_bytes()).hexdigest(),
            "coverage_sources": hashlib.sha256(
                Path(coverage_sources.__file__).read_bytes()
            ).hexdigest(),
            "census": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "authored_packs": digest(PACKS),
            "authored_aliases": digest(ALIASES),
        },
        "limits": [
            "Capacity is len(Dictionary._entries(sense)[0]), not successful puzzle generation.",
            "Lexical traversal retains the engine's filtering, ordering, depth, parent rules, "
            "deduplication and 80-entry cap; bucket 80 is censored at that cap.",
            "All loaded source-qualified synsets are evaluated, including unindexed senses; "
            "overlapping concepts in different sources are counted separately.",
            "Editorial packs are evaluated once per retained version, "
            "not once per alias or member entry. "
            "Their evaluation counts therefore differ from configuration unique_senses.",
            "Thresholds measure vocabulary availability, not puzzle suitability, clue quality, "
            "human review, understanding, reasoning or new knowledge.",
            "Weakest examples are bounded per source, ordered by capacity then sense ID; "
            "no per-sense results or timing are emitted by default.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wordnet", type=Path, default=lexicon.DEFAULT_WORDNET)
    parser.add_argument("--oewn", type=Path, default=coverage_sources.DEFAULT_OEWN)
    parser.add_argument("--packs-only", action="store_true")
    parser.add_argument("--weakest-limit", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"Refusing to overwrite: {args.out}")
    if not 0 <= args.weakest_limit <= 100:
        parser.error("--weakest-limit must be between 0 and 100")
    if not args.packs_only:
        for path in (args.wordnet, args.oewn):
            if not path.is_file():
                parser.error(
                    f"Missing installed corpus: {path}; use --packs-only for an offline census"
                )
    dictionary = Dictionary(
        None if args.packs_only else args.wordnet, oewn=None if args.packs_only else args.oewn
    )
    report = census(dictionary, weakest_limit=args.weakest_limit)
    report["inputs"] = {
        "mode": "packs-only" if args.packs_only else "full",
        "wordnet": None if args.packs_only else str(args.wordnet),
        "oewn": None if args.packs_only else str(args.oewn),
    }
    # Exclusive creation also protects against another writer during the census.
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
