"""Read-only, deterministic vocabulary query audit (not semantic understanding)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.coverage_sources import DEFAULT_OEWN
from spie.questions.brainbloom.lexicon import DEFAULT_WORDNET, Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.topics import lookup_many

EXAMPLE_LIMIT = 3
MAX_GENERATE = 8
REPRESENTATIVE_QUERIES = (
    ("geography", "continent"),
    ("geography", "mountain range"),
    ("anatomy", "heart"),
    ("anatomy", "red blood cell"),
    ("food", "bread"),
    ("food", "ice cream"),
    ("history", "renaissance"),
    ("history", "industrial revolution"),
    ("music", "orchestra"),
    ("music", "musical instrument"),
    ("economics", "inflation"),
    ("economics", "interest rate"),
    ("ecology", "ecosystem"),
    ("ecology", "food chain"),
    ("engineering", "bridge"),
    ("engineering", "electric motor"),
    ("plural", "continents"),
    ("plural", "teeth"),
    ("plural", "batteries"),
    ("ambiguous", "bank"),
    ("ambiguous", "crane"),
    ("ambiguous", "bass"),
    ("segmented", "space ocean"),
    ("segmented", "animals, plants"),
    ("unknown", "zzzxqvunknown"),
    ("mixed-unknown", "space zzzxqvunknown"),
)


def source_kind(sense):
    if sense.startswith(("pack:", "coverage-v1:", "coverage-v2:", "word:")):
        return "pack"
    if sense.startswith(("wn:", "oewn2024:")):
        return "lexical"
    return "other"


def audit_query(dictionary, category, query):
    term = " ".join(query.casefold().split())
    choices = dictionary._matches(term)
    counts, examples, sources = [], [], Counter()
    for choice in choices:
        entries, source = dictionary._entries(choice["id"])
        # Synthetic dictionaries used by the audit tests may omit an installed
        # WordNet source. Keep the exact-match audit useful without changing the
        # engine's source-loading contract.
        source = source or {"name": "unavailable synthetic source"}
        counts.append(len(entries))
        kind = source_kind(choice["id"])
        sources[kind] += 1
        if len(examples) < EXAMPLE_LIMIT:
            examples.append(
                {
                    "sense": choice["id"],
                    "source_kind": kind,
                    "source": source["name"],
                    "usable_entries": len(entries),
                    "words": [e["word"] for e in entries[:EXAMPLE_LIMIT]],
                }
            )
    report = lookup_many(dictionary, query)
    groups = report["groups"]
    return {
        "category": category,
        "query": query,
        "normalized_query": term,
        "exact": {
            "match_count": len(choices),
            "ambiguous": len(choices) > 1,
            "unambiguous": len(choices) == 1,
            "usable_entries_min": min(counts) if counts else None,
            "usable_entries_max": max(counts) if counts else None,
            "choice_sources": {key: sources[key] for key in ("pack", "lexical", "other")},
            "examples": examples,
        },
        "lookup_many": {
            "status": report["status"],
            "groups": [
                {
                    "term": g["term"],
                    "match_count": len(g["choices"]),
                    "selected": g["selected"],
                    "selection": g.get("selection", {}),
                }
                for g in groups
            ],
            "unknown_terms": report["unknown_terms"],
            "segmented": bool(groups) and (len(groups) != 1 or groups[0]["term"] != term),
            "usable_entries": len(report.get("context", {}).get("entries", [])),
        },
    }


def generation_sample(engine, rows, limit):
    """Exercise default automatic selection for a bounded sample of ready topics."""
    if not 0 <= limit <= MAX_GENERATE:
        raise ValueError(f"limit must be between 0 and {MAX_GENERATE}")
    cases = []
    selected = []
    for row in rows if limit else ():
        if (
            row["lookup_many"]["segmented"]
            or row["lookup_many"]["status"] != "ready"
            or not row["exact"]["match_count"]
        ):
            continue
        sense = row["lookup_many"]["groups"][0]["selected"]
        if not sense:
            continue
        selected.append((row, sense))
        if len(selected) == limit:
            break
    for row, sense in selected:
        term = row["normalized_query"]
        for kind in ("type-answer", "crossword"):
            case = {
                "query": row["query"],
                "sense": sense,
                "format": kind,
                "selection_mode": "automatic",
                "difficulty": "medium",
                "seed": 31,
                "generated": False,
                "replay": "not-run",
            }
            try:
                bundle = engine.build(
                    Request(
                        "dictionary", kind, "medium", seed=31, subject=term, topic_mode="combined"
                    )
                )
                case["generated"] = bool(bundle["summary"]["complete"])
            except (ValueError, RuntimeError) as exc:
                case["generation_error"] = str(exc)
            else:
                try:
                    case["replay"] = "passed" if verify_bundle(bundle) == 1 else "failed"
                except (ValueError, RuntimeError) as exc:
                    case.update(replay="failed", replay_error=str(exc))
            cases.append(case)
    return {
        "requested_topics": limit,
        "sampled_topics": len(selected),
        "cases": cases,
        "generated": sum(c["generated"] for c in cases),
        "replayed": sum(c["replay"] == "passed" for c in cases),
    }


def run_audit(dictionary, *, engine=None, generate=0):
    if not 0 <= generate <= MAX_GENERATE:
        raise ValueError(f"generate must be between 0 and {MAX_GENERATE}")
    if generate and engine is None:
        raise ValueError("Generation requires an engine with history disabled")
    if engine is not None and (engine.history is not None or engine.dictionary is not dictionary):
        raise ValueError("Generation must use the audited dictionary with history disabled")
    queries = [
        ("coverage-pack", topic)
        for topic in dict.fromkeys(p["topic"] for p in dictionary.coverage["packs"])
    ]
    queries.extend(REPRESENTATIVE_QUERIES)
    rows = [audit_query(dictionary, category, query) for category, query in queries]
    return {
        "configuration": dictionary.configuration(),
        "method": {
            "queries": "Fixed representative queries plus distinct loaded "
            "coverage-pack topic names, in order",
            "exact": "Dictionary._matches on casefolded whitespace-normalized whole input",
            "capacity": "Dictionary._entries for every exact choice; "
            "min/max do not select a meaning",
            "lookup_many": "Unselected topics API lookup, "
            "including pack-word fallback and segmentation",
            "generation": "First ready exact topics using default automatic selection; "
            "two formats; medium; seed 31; history disabled",
            "example_limit_per_query": EXAMPLE_LIMIT,
            "maximum_generation_topics": MAX_GENERATE,
        },
        "limits": [
            "Finite deterministic engineering sample, not a random vocabulary coverage estimate.",
            "Exact matches include aliases and morphology supported by the dictionary API.",
            "Raw source-qualified ambiguity is reported independently of the automatic choice; "
            "the selected meaning is a deterministic heuristic, not proof of user intent.",
            "Usable entries are bounded lexical expansions, not guaranteed puzzle capacity.",
            "Segmented readiness is not exact phrase understanding.",
            "Replay checks structural/proof consistency, "
            "not clue semantic correctness or topic relevance.",
            "No human or expert semantic review is performed.",
        ],
        "queries": rows,
        "summary": {
            "queries": len(rows),
            "coverage_topic_queries": len(queries) - len(REPRESENTATIVE_QUERIES),
            "exact_matched_queries": sum(r["exact"]["match_count"] > 0 for r in rows),
            "exact_choice_count": sum(r["exact"]["match_count"] for r in rows),
            "exact_ambiguous_queries": sum(r["exact"]["ambiguous"] for r in rows),
            "exact_unambiguous_queries": sum(r["exact"]["unambiguous"] for r in rows),
            "lookup_many_statuses": dict(Counter(r["lookup_many"]["status"] for r in rows)),
        },
        "generation": generation_sample(engine, rows, generate)
        if generate
        else {
            "requested_topics": 0,
            "sampled_topics": 0,
            "cases": [],
            "generated": 0,
            "replayed": 0,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", required=True, type=Path, help="New JSON report; never overwritten"
    )
    parser.add_argument(
        "--packs-only", action="store_true", help="Disable both external lexical corpora"
    )
    parser.add_argument(
        "--wordnet", type=Path, default=None, help=f"Optional corpus; auto-detect {DEFAULT_WORDNET}"
    )
    parser.add_argument(
        "--oewn", type=Path, default=None, help=f"Optional corpus; auto-detect {DEFAULT_OEWN}"
    )
    parser.add_argument(
        "--generate",
        type=int,
        nargs="?",
        const=2,
        default=0,
        choices=range(1, MAX_GENERATE + 1),
        metavar="1..8",
        help="Opt in to generation/replay for at most N ready exact topics "
        "using automatic meaning selection (default 2)",
    )
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"Report already exists: {args.out}")
    if args.packs_only and (args.wordnet is not None or args.oewn is not None):
        parser.error("--packs-only cannot be combined with corpus paths")
    wordnet = (
        None
        if args.packs_only
        else args.wordnet or (DEFAULT_WORDNET if DEFAULT_WORDNET.is_file() else None)
    )
    oewn = (
        None if args.packs_only else args.oewn or (DEFAULT_OEWN if DEFAULT_OEWN.is_file() else None)
    )
    engine = Generator(wordnet=wordnet, oewn=oewn, history=None) if args.generate else None
    dictionary = engine.dictionary if engine else Dictionary(wordnet=wordnet, oewn=oewn)
    result = run_audit(dictionary, engine=engine, generate=args.generate)
    result["source_paths"] = {
        "packs_only": args.packs_only,
        "wordnet": str(wordnet.resolve()) if wordnet else None,
        "oewn": str(oewn.resolve()) if oewn else None,
        "default_policy": "Load defaults only when present; explicit paths must load successfully",
    }
    with args.out.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
