"""Fail-closed resumption of our own complete training checkpoints."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REQUIRED = (
    "adapter_config.json", "adapter_model.safetensors", "optimizer.pt",
    "scheduler.pt", "rng_state.pth", "trainer_state.json",
)


def file_sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def seal_checkpoint(path: Path, signature: str) -> None:
    """Write completion marker LAST; interruption before this is not resumable."""
    for name in REQUIRED:
        if not (path / name).is_file():
            raise ValueError(f"incomplete checkpoint: missing {name}")
    files = {p.name: file_sha256(p) for p in sorted(path.iterdir()) if p.is_file()
             and p.name not in {"complete.json", "complete.tmp"}}
    marker = path / "complete.tmp"
    marker.write_text(json.dumps({"signature": signature, "files": files}), encoding="utf-8")
    marker.replace(path / "complete.json")


def resume_checkpoint(out: Path, requested: str | None, signature: str) -> Path | None:
    if requested is None:
        if out.exists():
            raise ValueError("output already exists; choose a new directory or explicitly resume")
        return None
    record = json.loads((out / "run.json").read_text(encoding="utf-8"))
    if record.get("resume_signature") != signature:
        raise ValueError("resume configuration differs: corpus/model/code/software/settings drift")
    root = (out / "checkpoints").resolve()
    if requested == "auto":
        candidates = [p for p in root.glob("checkpoint-*")
                      if re.fullmatch(r"checkpoint-\d+", p.name)
                      and (p / "complete.json").is_file()]
        if not candidates:
            raise ValueError("no complete checkpoint; choose a new output directory to restart")
        path = max(candidates, key=lambda p: int(p.name.split("-")[1])).resolve()
    else:
        path = Path(requested).resolve()
    if path.parent != root or not re.fullmatch(r"checkpoint-\d+", path.name):
        raise ValueError("checkpoint must belong to this run's checkpoints directory")
    marker = json.loads((path / "complete.json").read_text(encoding="utf-8"))
    files = marker.get("files", {})
    if marker.get("signature") != signature or not set(REQUIRED) <= files.keys():
        raise ValueError("checkpoint signature or required files disagree")
    for name, expected in files.items():
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("unsafe checkpoint filename")
        if file_sha256(path / name) != expected:
            raise ValueError(f"checkpoint integrity failure: {name}")
    state = json.loads((path / "trainer_state.json").read_text(encoding="utf-8"))
    if state.get("global_step") != int(path.name.split("-")[1]):
        raise ValueError("checkpoint step mismatch")
    return path
