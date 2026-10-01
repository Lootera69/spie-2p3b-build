"""Manual GitHub Actions preflight and real QLoRA supervised training entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

from spie.forge.corpus import digest

from .config import DEFAULT_MODEL, MODEL_PROFILES, model_profile
from .data import load_corpus, runner_spec, validate_minutes


def resolve_model_revision(model: str = DEFAULT_MODEL) -> str:
    model_profile(model)
    # Public model metadata only; no question content is sent to Hugging Face.
    url = f"https://huggingface.co/api/models/{model}/revision/main"
    with urllib.request.urlopen(url, timeout=30) as response:
        info = json.loads(response.read(2_000_000))
    revision = info.get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("model service did not supply an immutable revision")
    if info.get("cardData", {}).get("license") != "apache-2.0":
        raise ValueError("base-model license requires review; expected apache-2.0")
    return revision


def preflight(args) -> None:
    # The question bank is private input unless the owner explicitly decides otherwise.
    if os.environ.get("REPOSITORY_PRIVATE") != "true":
        raise ValueError("training workflow requires a PRIVATE repository; do not upload to public")
    runner = runner_spec(os.environ.get("FORGE_GPU_RUNNER", ""))
    minutes = validate_minutes(os.environ.get("TRAIN_MINUTES", "120"))
    data = load_corpus(Path(args.corpus))
    revision = resolve_model_revision() if args.resolve_model else "not-resolved-offline"
    summary = {"corpus_sha256": digest(data), "splits": data["manifest"]["splits"],
               "runner": runner, "timeout_minutes": minutes,
               "base_revision": revision, "training": "not started; preflight only"}
    print(json.dumps(summary, indent=2))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"runner={json.dumps(runner, separators=(',', ':'))}\n")
            stream.write(f"minutes={minutes}\n")
            stream.write(f"revision={revision}\n")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8") as stream:
            stream.write("## Question-writer training preflight\n\n```json\n")
            stream.write(json.dumps(summary, indent=2) + "\n```\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--corpus", required=True)
    pre.add_argument("--resolve-model", action="store_true")
    stage = sub.add_parser("stage", help="stage verified corpus for a PRIVATE training repo")
    stage.add_argument("--corpus", required=True)
    stage.add_argument("--out", required=True)
    fit = sub.add_parser("train")
    fit.add_argument("--corpus", required=True)
    fit.add_argument("--out", required=True)
    fit.add_argument("--mode", choices=("smoke", "full"), required=True)
    fit.add_argument("--revision", required=True, help="immutable 40-hex model commit")
    fit.add_argument("--model", choices=tuple(MODEL_PROFILES), default=DEFAULT_MODEL)
    fit.add_argument("--resume", help="auto or a checkpoint path within the same output run")
    fit.add_argument("--max-length", type=int, default=2048)
    fit.add_argument("--preview-count", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            preflight(args)
        elif args.command == "stage":
            data = load_corpus(Path(args.corpus))
            out = Path(args.out)
            if out.exists():
                raise ValueError("staging output exists; choose a new path")
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump({"sha256": digest(data), "data": data}, stream, ensure_ascii=False)
                stream.write("\n")
            print(f"Staged {data['manifest']['usable_rows']} records locally. Not uploaded.")
        else:
            from .train import train

            train(args)
    except (ValueError, OSError, ImportError) as exc:
        print(f"forge-train: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
