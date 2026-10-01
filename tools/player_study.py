"""Prepare a local anonymous player pilot and summarize real downloaded responses."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from spie.forge.corpus import digest
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.service import Generator, verify_bundle

TEMPLATE = Path(__file__).parent / "templates/player_study.html"


def create(out: Path):
    if out.exists() and any(out.iterdir()):
        raise ValueError("Study output directory must be empty")
    engine = Generator()
    cases = []
    for family, variation in (("autopilot", "auto"), ("reasoning", "deduction"),
                              ("activities", "pattern"), ("activities", "contradiction"),
                              ("activities", "best-move"), ("reasoning", "bayesian")):
        for level in ("easy", "hard"):
            bundle = engine.build(Request(family, variation=variation, difficulty=level,
                                          subject="space, ocean", topic_mode="combined", seed=17))
            verify_bundle(bundle)
            item, proof = bundle["items"][0], bundle["proofs"][0]
            cases.append({"item": item, "family": family + "/" + variation,
                          "level": level, "proof": proof,
                          "hints": proof.get("quality", {}).get("hints", [
                              "Write down what is given, then compare each possible answer."]),
                          "explanation": "\n".join(proof.get("steps", []))})
    random.Random(90210).shuffle(cases)
    for i, case in enumerate(cases, 1):
        case["id"] = f"Puzzle {i:02}"
    study = {"id": "brainbloom-player-pilot-" + digest(cases)[:12], "cases": cases}
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(study, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    public = {"id": study["id"], "cases": [{k: case[k] for k in
              ("id", "item", "hints", "explanation")} for case in cases]}
    for case in public["cases"]:
        case["item"] = {k: v for k, v in case["item"].items()
                        if k not in ("difficulty", "title", "lessonContent", "lessonGroup")}
    payload = json.dumps(public, ensure_ascii=False).replace("<", "\\u003c")
    page = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload)
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"Created {len(cases)} checked cases in {out}. No participant responses collected.")


def summarize(manifest: Path, inputs: list[Path]):
    study = json.loads(manifest.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in study["cases"]}
    seen, groups, sessions = set(), defaultdict(list), set()
    for path in inputs:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("study") != study["id"] or not isinstance(data.get("session"), str)
                or not data["session"].strip() or not isinstance(data.get("responses"), list)):
            raise ValueError("Responses do not belong to this study")
        if data["responses"]:
            sessions.add(data["session"])
        for response in data["responses"]:
            required = {"id", "answer", "skipped", "seconds", "hints", "difficulty",
                        "enjoyment", "clarity", "notes"}
            if not isinstance(response, dict) or not required <= response.keys():
                raise ValueError("Response is missing required fields")
            if not isinstance(response["id"], str) or response["id"] not in cases:
                raise ValueError("Response refers to an unknown puzzle")
            key = (data["session"], response["id"])
            if key in seen:
                raise ValueError("Duplicate session/puzzle response; use one export per session")
            seen.add(key)
            case = cases[response["id"]]
            if any(type(response[k]) is not int or not 1 <= response[k] <= 5
                   for k in ("difficulty", "enjoyment", "clarity")):
                raise ValueError("Ratings must be integers from 1 to 5")
            if (type(response["seconds"]) not in (int, float) or
                    not 0 <= response["seconds"] <= 86400):
                raise ValueError("Invalid response duration")
            if (type(response["hints"]) is not int or
                    not 0 <= response["hints"] <= len(case["hints"])):
                raise ValueError("Invalid hint count")
            if type(response["skipped"]) is not bool:
                raise ValueError("Invalid skip flag")
            if response["answer"] not in (None, *case["item"]["choices"]):
                raise ValueError("Answer is not an offered choice")
            if response["skipped"] != (response["answer"] is None):
                raise ValueError("Skipped answers must be empty; attempted answers need a choice")
            if not isinstance(response["notes"], str) or len(response["notes"]) > 1000:
                raise ValueError("Notes must be text of at most 1000 characters")
            correct = (not response["skipped"] and
                       response["answer"] == case["item"]["correctAnswer"])
            groups[(case["family"], case["level"])].append({**response, "correct": correct})
    rows = []
    for (family, level), values in sorted(groups.items()):
        rows.append({"family": family, "intended_level": level, "responses": len(values),
                     "correct_rate": sum(v["correct"] for v in values) / len(values),
                     "skip_rate": sum(v["skipped"] for v in values) / len(values),
                     "median_seconds": statistics.median(v["seconds"] for v in values),
                     **{f"mean_{k}": statistics.mean(v[k] for v in values)
                        for k in ("difficulty", "enjoyment", "clarity", "hints")}})
    return {"study": study["id"], "sessions": len(sessions), "responses": len(seen),
            "scope": "Supplied response exports only; an observational pilot, not calibrated "
                     "difficulty or causal evidence. Participant authenticity is not verified.",
            "results": rows}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    make.add_argument("--out", type=Path, required=True)
    report = sub.add_parser("report")
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("responses", nargs="*", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        create(args.out)
    else:
        print(json.dumps(summarize(args.manifest, args.responses), indent=2))


if __name__ == "__main__":
    main()
