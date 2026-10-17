"""Save creator-path samples for an offline quality audit; never publish or mutate the engine.

Run from the engine directory. The corpus uses the same WordNet/coverage configuration
as the deployed service, with optional OEWN, persistent history and Studio disabled.
Quality judgments live in the accompanying plan, not in a fabricated universal score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from spie.questions.brainbloom.brief import ACTIVITIES, Brief, configuration, prepare
from spie.questions.brainbloom.catalog import TOPICS, Request
from spie.questions.brainbloom.service import Generator, verify_bundle


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--wordnet", type=Path, default=Path(".brainbloom/corpora/wordnet.zip"))
    parser.add_argument("--levels", default="easy,medium,hard")
    parser.add_argument("--seeds", default="7,23,91")
    parser.add_argument("--activities", default=",".join(ACTIVITIES))
    parser.add_argument("--all-formats", action="store_true")
    parser.add_argument("--formats", default="",
                        help="Explicit formats, including retired formats for boundary regressions")
    parser.add_argument("--subject", default="space, ocean")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    activities = args.activities.split(",")
    levels = args.levels.split(",")
    try:
        seeds = [int(seed) for seed in args.seeds.split(",")]
    except ValueError:
        parser.error("--seeds must be comma-separated integers")
    if any(activity not in ACTIVITIES for activity in activities):
        parser.error("--activities contains an unknown activity")
    if any(level not in ("easy", "medium", "hard") for level in levels):
        parser.error("--levels must contain easy, medium or hard")
    if not 1 <= args.count <= 20:
        parser.error("--count must be between 1 and 20")
    if args.formats and args.all_formats:
        parser.error("Choose --formats or --all-formats, not both")
    args.out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    started = time.perf_counter()
    engine = Generator(wordnet=args.wordnet, oewn=None)
    initialization = time.perf_counter() - started
    metadata = {
        "audit_version": 2,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_revision": revision,
        "source_sha256": hashlib.sha256(b"".join(
            path.relative_to("src").as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
            for path in sorted(Path("src").rglob("*.py"))
        )).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "subject": args.subject,
        "count": args.count,
        "python": platform.python_version(),
        "dictionary": engine.dictionary.configuration(),
        "inventory": configuration()["activities"],
        "initialization_seconds": round(initialization, 4),
        "scope": "local creator Brief -> prepare -> Generator.build; no live service requests",
        "limits": [
            "Local timings are not Render latency or human solve times.",
            "Native puzzle proofs run during generation; selected cases also use saved replay.",
            "Custom grids use the shipped authored example; their level comes from that grid.",
            "Word Wonder has no difficulty control and resolves to medium.",
            "Selected seeds and levels are coverage samples, not population estimates.",
        ],
    }
    manifest_path = args.out / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        identity = ("audit_version", "git_revision", "dictionary", "source_sha256",
                    "runner_sha256", "subject", "count")
        if any(previous.get(key) != metadata[key] for key in identity):
            raise SystemExit("Use a new output directory after changing the audit inputs")
    else:
        write_json(manifest_path, metadata)
    invocation = {"started_at_utc": datetime.now(UTC).isoformat(),
                  "activities": activities, "levels": levels, "seeds": seeds,
                  "all_formats": args.all_formats, "formats": args.formats,
                  "count": args.count, "subject": args.subject}
    with (args.out / "invocations.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(invocation) + "\n")
    for activity in activities:
        spec = ACTIVITIES[activity]
        qtypes = (tuple(args.formats.split(",")) if args.formats else
                  spec.types if args.all_formats else spec.types[:1])
        for level in levels:
            for seed in seeds:
                for qtype in qtypes:
                    case_id = f"{activity}__{level}__{seed}__{qtype}"
                    path = args.out / "cases" / f"{case_id}.json"
                    if path.exists():
                        continue
                    brief = Brief(
                        activity=activity,
                        category=TOPICS[spec.family].categories[0],
                        subject=args.subject if spec.uses_topics else "",
                        qtype=qtype,
                        difficulty=level,
                        seed=seed,
                        count=args.count,
                    )
                    record = {"id": case_id, "activity": activity, "brief": asdict(brief)}
                    phase = "prepare"
                    start = time.perf_counter()
                    try:
                        prepared = prepare(brief, engine.dictionary)
                        record["preparation_seconds"] = round(time.perf_counter() - start, 4)
                        record["prepared"] = {
                            key: prepared.get(key) for key in (
                                "ready", "message", "selected_activity", "request",
                                "difficulty_relevant", "reasoning_relevant", "difficulty_help",
                            )
                        }
                        if not prepared["ready"]:
                            record["status"] = "unavailable"
                        else:
                            phase = "generation"
                            start = time.perf_counter()
                            bundle = engine.build(Request(**prepared["request"]))
                            record["generation_seconds"] = round(time.perf_counter() - start, 4)
                            record["bundle"] = bundle
                            record["status"] = (
                                "accepted" if bundle["summary"]["complete"] else "partial"
                            )
                            question = "\n".join(item["question"] for item in bundle["items"])
                            record["surface"] = {
                                "question_characters": len(question),
                                "question_words": len(question.split()),
                                "numeric_tokens": len(re.findall(r"\b\d+\b", question)),
                                "choices": [len(item.get("choices", []))
                                            for item in bundle["items"]],
                                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                            }
                            if level == "hard" and seed == 7:
                                phase = "replay"
                                start = time.perf_counter()
                                record["replay_count"] = verify_bundle(bundle)
                                record["replay_seconds"] = round(time.perf_counter() - start, 4)
                    except Exception as error:
                        record.update(status="error", error_phase=phase,
                                      error_type=type(error).__name__, error=str(error))
                    write_json(path, record)
                    print(json.dumps({"case": case_id, "status": record["status"],
                                      "generation_seconds": record.get("generation_seconds"),
                                      "error": record.get("error")}), flush=True)


if __name__ == "__main__":
    main()
