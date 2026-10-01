"""Local preparation and explicit model endpoint generation. Never publishes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .contract import GROUPS, TYPES, XP
from .corpus import compact, digest, prepare
from .platform import check_platform
from .propose import Brief, intake, training_example, writing_request


def write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("model endpoint redirected; configure its final URL explicitly")


def call_writer(endpoint: str, model: str, messages: list[dict], key_env: str | None) -> str:
    """Explicit chat-completions endpoint, standard JSON protocol, bounded response.

No credential discovery, automatic upload, training job, or provider is implicit.
The API key is read only from the named variable and never saved in artifacts.
"""
    url = urlparse(endpoint)
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("endpoint must not contain credentials, a query, or fragment")
    local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if not url.hostname or not (url.scheme == "https" or (url.scheme == "http" and local)):
        raise ValueError("endpoint requires HTTPS (HTTP allowed only on loopback)")
    headers = {"Content-Type": "application/json"}
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            raise ValueError(f"API key environment variable {key_env} is not set")
        headers["Authorization"] = f"Bearer {key}"
    body = compact({"model": model, "messages": messages, "max_tokens": 8192}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=55) as response:
            raw = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"writer HTTP {exc.code}; response body omitted") from None
    except urllib.error.URLError:
        raise ValueError("writer connection failed") from None
    if len(raw) > 2_000_000:
        raise ValueError("writer response exceeds 2 MB")
    choice = json.loads(raw)["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("writer did not finish normally; truncated/tool output is not accepted")
    content = choice["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("writer did not return text")
    return content


def _brief(args) -> Brief:
    return Brief(args.category, args.type, args.difficulty,
                 args.topic, args.count, args.lesson_group)


def _load(path: str) -> dict:
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    if artifact.get("sha256") != digest(artifact.get("data")):
        raise ValueError("corpus artifact hash mismatch; rebuild from source")
    return artifact["data"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BrainBloom corpus-conditioned question writer")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="audit bank and export supervised training candidates")
    prep.add_argument("--bank", required=True, help="directory of production validated batches")
    prep.add_argument("--out", required=True, help="new output directory (never overwrite)")
    for name in ("request", "generate", "receive"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--corpus", required=True)
        cmd.add_argument("--out", required=True)
        if name != "request":
            cmd.add_argument("--platform-verifier", help="path to Studio lib/forge/verify.ts")
        if name == "receive":
            cmd.add_argument("--request", required=True)
            cmd.add_argument("--response", required=True)
            continue
        cmd.add_argument("--category", choices=tuple(GROUPS), required=True)
        cmd.add_argument("--type", choices=TYPES, required=True)
        cmd.add_argument("--difficulty", choices=tuple(XP), required=True)
        cmd.add_argument("--topic", required=True)
        cmd.add_argument("--count", type=int, default=1)
        cmd.add_argument("--lesson-group")
        if name == "generate":
            cmd.add_argument("--endpoint", required=True, help="full chat-completions URL")
            cmd.add_argument("--model", required=True, help="base or fine-tuned model identifier")
            cmd.add_argument("--key-env", help="environment variable holding the endpoint API key")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        out = Path(args.out)
        if out.exists():
            raise ValueError(f"output exists: {out}; choose a new path")
        if args.command == "prepare":
            data = prepare(Path(args.bank))
            files = {
                "corpus.json": compact({"sha256": digest(data), "data": data}) + "\n",
                "manifest.json": json.dumps(data["manifest"], indent=2, ensure_ascii=False) + "\n",
            }
            for split in ("train", "validation", "test"):
                rows = [r for r in data["records"] if r["split"] == split]
                files[f"{split}.jsonl"] = "".join(compact(training_example(r)) + "\n" for r in rows)
                files[f"{split}.sources.json"] = compact([
                    {k: r[k] for k in ("source", "group")} for r in rows]) + "\n"
            for name, text in files.items():
                write_new(out / name, text)
            manifest = data["manifest"]
            print(compact({k: manifest[k] for k in ("input_rows", "usable_rows", "splits")}))
            print("Training files prepared. Language-model weights have NOT been trained.")
            return 0
        data = _load(args.corpus)
        records = data["records"]
        if args.command == "receive":
            request = json.loads(Path(args.request).read_text(encoding="utf-8"))
            if request.get("corpus_sha256") != digest(data):
                raise ValueError("request belongs to a different corpus")
            brief = Brief(**request["brief"])
            response = Path(args.response).read_text(encoding="utf-8")
        else:
            brief = _brief(args)
            request = {**writing_request(records, brief), "corpus_sha256": digest(data)}
            if args.command == "request":
                write_new(out, json.dumps(request, ensure_ascii=False, indent=2) + "\n")
                print(f"Saved request with {len(request['reference_ids'])} corpus examples.")
                return 0
            response = call_writer(args.endpoint, args.model, request["messages"], args.key_env)
        result = intake(response, records, brief)
        result["provenance"].update({"corpus_sha256": digest(data),
                                     "reference_ids": request["reference_ids"]})
        result["provenance"]["writer"] = (
            {"mode": "endpoint", "model": args.model, "endpoint": args.endpoint}
            if args.command == "generate" else {"mode": "external-response", "model": "unrecorded"}
        )
        if args.platform_verifier:
            result = check_platform(result, Path(args.platform_verifier))
        write_new(out, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(f"{len(result['items'])} unpublished drafts; {len(result['rejected'])} rejected.")
        return 1 if result["rejected"] else 0
    except (ValueError, OSError, KeyError, IndexError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"forge: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
