"""python -m spie.questions.brainbloom: local generator, preview, and proof replay."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from .catalog import CATEGORIES, DIFFICULTIES, TOPICS, TYPES, VARIATIONS, Request
from .coverage_sources import DEFAULT_OEWN, install_oewn
from .lexicon import DEFAULT_WORDNET, install_wordnet
from .service import Generator, verify_bundle, write_bundle
from .topics import lookup_many


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BrainBloom non-LLM draft generator")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "serve"):
        command = commands.add_parser(name)
        command.add_argument("--bank", type=Path, help="Read-only validated bank for deduplication")
        command.add_argument(
            "--wordnet", type=Path,
            help="Local pinned WordNet ZIP; auto-detect .brainbloom/wordnet.zip",
        )
        command.add_argument(
            "--platform-verifier", type=Path, help="Local Studio lib/forge/verify.ts"
        )
        if name == "serve":
            command.add_argument("--port", type=int, default=None,
                                 help="Listening port; default $PORT, else 8766")
            command.add_argument("--host", default=None,
                                 help="Bind address; default $BRAINBLOOM_HOST, else 127.0.0.1")
            command.add_argument("--public-origin", default=None,
                                 help="Deployed origin such as https://host, which widens the "
                                      "same-origin allowlist and caps requests per client; "
                                      "default $BRAINBLOOM_PUBLIC_ORIGIN")
            command.add_argument("--open", action="store_true", help="Open the local workshop")
            command.add_argument("--history", type=Path,
                                 default=Path(".brainbloom/draft-history.sqlite3"),
                                 help="Archive generated design fingerprints across sessions")
            command.add_argument("--no-history", action="store_true",
                                 help="Do not retain or compare cross-session draft fingerprints")
            command.add_argument("--no-integrations", action="store_true",
                                 help="Do not auto-detect the sibling bank and Studio verifier")
        else:
            command.add_argument("--category", choices=(*CATEGORIES, "wonder"))
            command.add_argument("--topic", choices=tuple(TOPICS))
            command.add_argument(
                "--grid", type=Path,
                help="JSON file defining custom grid groups and rules",
            )
            command.add_argument(
                "--subject", default="", help="Your dictionary topic word or phrase"
            )
            command.add_argument("--sense", default="", help="Explicit sense ID from topic lookup")
            command.add_argument("--meaning", action="append", default=[], metavar="TOPIC=ID",
                                 help="Select a meaning for each ambiguous topic; repeat as needed")
            command.add_argument(
                "--variation", default="auto",
                choices=tuple(dict.fromkeys(v for styles in VARIATIONS.values() for v in styles)),
            )
            command.add_argument(
                "--search-effort", default="balanced", choices=("quick", "balanced", "thorough"),
                help="Reasoning lab: compare 12, 32 or 80 candidate models",
            )
            command.add_argument("--type", dest="qtype", choices=TYPES, default="multiple-choice")
            command.add_argument("--difficulty", choices=tuple(DIFFICULTIES), default="medium")
            command.add_argument("--seed", type=int, default=0)
            command.add_argument("--count", type=int, default=1)
            command.add_argument("--crossword-size", type=int, choices=range(5, 16),
                                 help="Exact crossword board side length (5–15)")
            command.add_argument("--out", type=Path, required=True)
    replay = commands.add_parser(
        "check", help="Re-generate and independently re-prove saved drafts"
    )
    replay.add_argument("path", type=Path)
    install = commands.add_parser(
        "dictionary-install", help="Download the pinned WordNet corpus once"
    )
    install.add_argument("--out", type=Path, default=DEFAULT_WORDNET)
    lookup = commands.add_parser("topics", help="Look up dictionary meanings and usable words")
    lookup.add_argument("subject")
    lookup.add_argument("--sense", default="")
    lookup.add_argument("--meaning", action="append", default=[], metavar="TOPIC=ID")
    lookup.add_argument("--wordnet", type=Path)
    benchmark = commands.add_parser("benchmark", help="Measure reasoning gates and search quality")
    benchmark.add_argument("--subject", default="space")
    benchmark.add_argument("--sense", default="")
    benchmark.add_argument("--seeds", type=int, default=3)
    benchmark.add_argument("--wordnet", type=Path)
    benchmark.add_argument("--out", type=Path, required=True)
    supplement = commands.add_parser("oewn-install", help="Install additive pinned OEWN 2024")
    supplement.add_argument("--out", type=Path, default=DEFAULT_OEWN)
    info = commands.add_parser("dictionary-info", help="Report source-specific coverage counts")
    info.add_argument("--wordnet", type=Path)
    for name in ("generate", "serve", "topics", "benchmark", "dictionary-info"):
        command = commands.choices[name]
        command.add_argument("--oewn", type=Path,
                             help="Additive OEWN 2024 gzip; auto-detect the installed file")
        command.add_argument("--no-oewn", action="store_true", help="Disable optional OEWN")
        command.add_argument("--no-coverage", action="store_true",
                             help="Disable the eight additional versioned topic packs")
    args = parser.parse_args(argv)
    try:
        meanings = {}
        for value in getattr(args, "meaning", []):
            term, separator, sense = value.partition("=")
            term = " ".join(term.casefold().split())
            if not separator or not term or not sense or term in meanings:
                raise ValueError("Use --meaning TOPIC=ID once for each ambiguous topic")
            meanings[term] = sense
        if args.command == "dictionary-install":
            install_wordnet(args.out)
            print(f"Installed pinned WordNet 3.0 at {args.out}; subsequent generation is offline.")
            return 0
        if args.command == "oewn-install":
            install_oewn(args.out)
            print(f"Installed additive OEWN 2024 at {args.out}; generation remains offline.")
            return 0
        if args.command == "check":
            bundle = json.loads(args.path.read_text(encoding="utf-8-sig"))
            count = verify_bundle(bundle)
            print(f"{count} drafts reproduced and re-proved; editorial review not re-run.")
            return 0
        if args.command in ("generate", "benchmark") and args.out.exists():
            raise ValueError(f"Output already exists: {args.out}; choose a new path")
        wordnet = args.wordnet or (DEFAULT_WORDNET if DEFAULT_WORDNET.exists() else None)
        if args.no_oewn and args.oewn:
            raise ValueError("Choose --oewn or --no-oewn, not both")
        oewn = None if args.no_oewn else (
            args.oewn or (DEFAULT_OEWN if DEFAULT_OEWN.exists() else None))
        bank = getattr(args, "bank", None)
        verifier = getattr(args, "platform_verifier", None)
        history = None
        if args.command == "serve":
            if not args.no_integrations:
                default_bank = Path("../puzzle-batch/output/validated")
                default_verifier = Path("../../BrainBloom/lib/forge/verify.ts")
                if bank is None and default_bank.is_dir():
                    bank = default_bank
                if verifier is None and default_verifier.is_file() and shutil.which("node"):
                    verifier = default_verifier
            history = None if args.no_history else args.history
        engine = Generator(
            bank, verifier, wordnet, history, oewn=oewn, coverage=not args.no_coverage
        )
        if args.command == "dictionary-info":
            print(json.dumps(engine.dictionary.configuration(), indent=2))
            return 0
        if args.command == "benchmark":
            from .benchmark import run

            report = run(engine, args.subject, args.seeds, args.sense)
            write_bundle(args.out, report)
            print(json.dumps(report["summary"], indent=2))
            print(f"Saved local regression measurements to {args.out}")
            return 0 if report["summary"]["rejected"] == 0 else 1
        if args.command == "topics":
            result = (engine.dictionary.lookup(args.subject, args.sense) if args.sense
                      else lookup_many(engine.dictionary, args.subject, meanings))
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "serve":
            from .web import serve

            # The environment supplies the endpoint on a hosted run; flags win locally.
            port = args.port
            if port is None:
                raw = os.environ.get("PORT", "").strip()
                try:
                    port = int(raw) if raw else 8766
                except ValueError:
                    raise ValueError(f"PORT must be a port number, not {raw!r}") from None
            serve(
                engine,
                port,
                open_browser=args.open,
                host=args.host or os.environ.get("BRAINBLOOM_HOST") or "127.0.0.1",
                public_origin=args.public_origin
                or os.environ.get("BRAINBLOOM_PUBLIC_ORIGIN")
                or None,
            )
            return 0
        category = args.category or (
            TOPICS[args.topic].categories[0]
            if args.topic
            else {"riddle": "riddles", "wonder": "wonders", "crossword": "puzzles"}.get(
                args.qtype, "logic"
            )
        )
        if category == "wonder":
            category = "wonders"
        topics = [
            key
            for key, value in TOPICS.items()
            if category in value.categories and args.qtype in value.types
        ]
        if not topics:
            raise ValueError("This category does not yet support the selected question type")
        topic = args.topic or (
            "logic-grid" if args.grid else "dictionary" if args.subject else topics[0]
        )
        request = Request(topic, args.qtype, args.difficulty, args.count, args.seed, category,
                          args.subject, args.sense, args.variation, args.search_effort,
                          topic_mode=("combined" if topic in VARIATIONS and not args.sense
                                      else "single"), meanings=meanings,
                          grid=json.loads(args.grid.read_text(encoding="utf-8-sig"))
                          if args.grid else None, crossword_size=args.crossword_size)
        result = engine.build(request)
        write_bundle(args.out, result)
        print(f"Saved {len(result['items'])}/{request.count} unpublished drafts to {args.out}")
        print("No learned model used. Human review required; nothing imported or published.")
        return 0 if result["summary"]["complete"] else 1
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"brainbloom: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
