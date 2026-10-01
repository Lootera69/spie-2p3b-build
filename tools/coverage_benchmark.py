"""Compare baseline, latest/legacy exact-topic coverage, and live default lookup."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from spie.questions.brainbloom.catalog import TYPES, Request
from spie.questions.brainbloom.coverage_sources import DEFAULT_OEWN
from spie.questions.brainbloom.lexicon import DEFAULT_WORDNET
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.topics import lookup_many

SUBJECTS = [
    "photosynthesis",
    "black hole",
    "climate change",
    "quantum computing",
    "machine learning",
    "cybersecurity",
    "renewable energy",
    "robotics",
    "plate tectonics",
    "genetics",
    "cricket",
    "neuroscience",
]


def select(dictionary, subject, coverage_version=None):
    if coverage_version not in (None, "v1", "v2"):
        raise ValueError("coverage_version must be v1 or v2")
    choices = dictionary._matches(subject)
    packs = [
        c
        for c in choices
        if c["id"].startswith("coverage-v")
        and c["id"].count(":") == 1
        and (coverage_version is None or c["id"].startswith("coverage-" + coverage_version + ":"))
    ]
    if packs:
        return max(packs, key=lambda c: int(c["id"].split(":")[0].removeprefix("coverage-v")))["id"]
    for choice in choices:
        if choice["id"].startswith("pack:"):
            return choice["id"]
    if subject == "cricket":
        return next((c["id"] for c in choices if "two teams of 11" in c["definition"]), "")
    return choices[0]["id"] if len(choices) == 1 else ""


def check_answer(item, proof):
    """Independent quiz rule calculation, separate from the replay verifier."""
    if "constraints" not in proof:
        return None  # Crosswords and Wonders have distinct validators in replay.
    rule, bank = proof["constraints"], proof["word_bank"]
    if "letters" in rule:
        valid = [
            w
            for w in bank
            if Counter(w) == Counter(rule["letters"]) and w.startswith(rule["prefix"])
        ]
    elif "pattern" in rule:
        valid = [
            w
            for w in bank
            if len(w) == len(rule["pattern"])
            and all(a == "_" or a == b for a, b in zip(rule["pattern"], w, strict=True))
        ]
    else:
        valid = [sorted(bank)[rule["position"] - 1]]
    if len(valid) != 1:
        return False
    expected = str(proof["claim"] in valid) if "claim" in proof else valid[0]
    return item["correctAnswer"] == expected


def review_checks(bundle):
    entries = bundle["dictionary"]["entries"]
    leaks = [
        e["word"]
        for e in entries
        if e["word"].lower() in re.sub(r"[^a-z]", "", e["definition"].lower())
    ]
    # A screening measurement, deliberately not a claim of editorial approval.
    return {
        "answer_text_in_definition": leaks,
        "long_definitions": sum(len(e["definition"]) > 180 for e in entries),
        "human_reviewed": False,
        "expert_reviewed": False,
    }


def run_profile(engine, name, out, *, selection="explicit", coverage_version=None):
    if selection not in ("explicit", "automatic"):
        raise ValueError("selection must be explicit or automatic")
    if engine.history is not None:
        raise ValueError("Benchmark generation requires history disabled")
    rows, bundles = [], []
    for subject in SUBJECTS:
        sense = (
            select(engine.dictionary, subject, coverage_version) if selection == "explicit" else ""
        )
        row = {"subject": subject, "sense": sense, "selection_mode": selection, "cases": []}
        if selection == "explicit" and not sense:
            row.update(status="no-unambiguous-exact-topic", usable_entries=0)
            rows.append(row)
            continue
        meanings = {subject: sense} if selection == "explicit" else {}
        report = lookup_many(engine.dictionary, subject, meanings)
        row["selected_meanings"] = report["meanings"]
        row["status"] = report["status"]
        row["usable_entries"] = len(report.get("context", {}).get("entries", []))
        if report["status"] == "ready":
            cases = [
                (kind, "medium", seed, "dictionary", "auto") for kind in TYPES for seed in (7, 31)
            ]
            cases += [
                ("crossword", "hard", 7, "dictionary", "auto"),
                ("type-answer", "hard", 7, "activities", "best-move"),
            ]
            for kind, level, seed, family, variation in cases:
                case = {
                    "format": kind,
                    "difficulty": level,
                    "seed": seed,
                    "family": family,
                    "generated": False,
                    "replayed": False,
                }
                try:
                    bundle = engine.build(
                        Request(
                            family,
                            kind,
                            level,
                            seed=seed,
                            subject=subject,
                            meanings=meanings,
                            topic_mode="combined",
                            variation=variation,
                        )
                    )
                    case.update(
                        generated=bundle["summary"]["complete"],
                        independent_quiz_answer=check_answer(
                            bundle["items"][0], bundle["proofs"][0]
                        ),
                        editorial_screen=review_checks(bundle),
                    )
                    bundles.append(bundle)
                    case["replayed"] = verify_bundle(bundle) == 1
                except (ValueError, RuntimeError) as exc:
                    case["error"] = str(exc)
                row["cases"].append(case)
        rows.append(row)
        print(
            name,
            subject,
            row["usable_entries"],
            sum(c["generated"] for c in row["cases"]),
            flush=True,
        )
    result = {
        "configuration": engine.dictionary.configuration(),
        "topics": rows,
        "selection_mode": selection,
        "requested_coverage_version": coverage_version or "latest",
        "selected_coverage_namespaces": sorted(
            {
                sense.split(":", 1)[0]
                for row in rows
                for sense in row.get("selected_meanings", {}).values()
                if sense.startswith("coverage-v")
            }
        ),
        "summary": {
            "topics": len(rows),
            "ready_topics": sum(r["status"] == "ready" for r in rows),
            "scheduled_cases": len(SUBJECTS) * 14,
            "generated": sum(c["generated"] for r in rows for c in r["cases"]),
            "replayed": sum(c.get("replayed", False) for r in rows for c in r["cases"]),
            "incorrect_quiz_answers": sum(
                c.get("independent_quiz_answer") is False for r in rows for c in r["cases"]
            ),
            "independent_quiz_answers_checked": sum(
                c.get("independent_quiz_answer") is not None for r in rows for c in r["cases"]
            ),
        },
    }
    (out / f"{name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / f"{name}-bundles.json").write_text(json.dumps(bundles, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--wordnet", type=Path, default=DEFAULT_WORDNET)
    parser.add_argument("--oewn", type=Path, default=DEFAULT_OEWN)
    parser.add_argument(
        "--coverage-version",
        choices=("v1", "v2"),
        default=None,
        help="Explicit expanded profile version; defaults to latest. "
        "Default-flow profile always uses live policy.",
    )
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"Refusing to overwrite: {args.out}")
    for path in (args.wordnet, args.oewn):
        if not path.is_file():
            parser.error(f"Missing installed corpus: {path}")
    args.out.mkdir(parents=True, exist_ok=False)
    baseline_engine = Generator(wordnet=args.wordnet, coverage=False, history=None)
    baseline = run_profile(baseline_engine, "baseline", args.out)
    expanded_engine = Generator(wordnet=args.wordnet, oewn=args.oewn, history=None)
    expanded = run_profile(
        expanded_engine, "expanded", args.out, coverage_version=args.coverage_version
    )
    default = run_profile(expanded_engine, "default", args.out, selection="automatic")
    old_terms = set(baseline_engine.dictionary.index)
    new_terms = sorted(set(expanded_engine.dictionary.oewn_index) - old_terms)
    summary = {
        "baseline": baseline["summary"],
        "expanded": expanded["summary"],
        "default": default["summary"],
        "explicit_coverage_version": args.coverage_version or "latest",
        "oewn_lookup_keys_absent_from_princeton_index": len(new_terms),
        "new_lookup_examples": [
            t for t in new_terms if t in ("ransomware", "smartphone", "selfie", "blockchain")
        ],
        "method": "Baseline and expanded explicit exact-topic selection plus "
        "expanded default automatic selection; "
        "all six formats, seeds 7/31, medium; "
        "hard crossword and hard route activity, seed 7; history disabled. "
        "A missing exact topic is counted as an unsupported case, not a wrong answer.",
        "limits": "Finite engineering regression set, not random sampling or human study. "
        "Definitions and topic relevance are not proven by puzzle solvers.",
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
