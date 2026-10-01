"""Dependency-free data integrity checks shared by preflight, training and tests."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from spie.forge.contract import issues, normalized
from spie.forge.corpus import digest
from spie.forge.propose import training_example


def load_corpus(path: Path) -> dict:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    data = artifact.get("data")
    if not isinstance(data, dict) or artifact.get("sha256") != digest(data):
        raise ValueError("corpus integrity check failed")
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("empty or malformed corpus")
    sources, stems, group_splits = set(), set(), {}
    for row in records:
        if row.get("split") not in {"train", "validation", "test"}:
            raise ValueError("unknown split")
        if issues(row.get("item")):
            raise ValueError(f"invalid training target: {row.get('source')}")
        source, group = row.get("source"), row.get("group")
        if not isinstance(source, str) or not isinstance(group, str) or not source or not group:
            raise ValueError("source and group identifiers are required")
        if source in sources:
            raise ValueError("duplicate source ID")
        sources.add(source)
        stem = normalized(row["item"]["question"])
        if stem in stems:
            raise ValueError("duplicate question stem")
        stems.add(stem)
        if group in group_splits and group_splits[group] != row["split"]:
            raise ValueError("group leakage across splits")
        group_splits[group] = row["split"]
    counts = dict(Counter(r["split"] for r in records))
    if any(counts.get(s, 0) == 0 for s in ("train", "validation", "test")):
        raise ValueError("train, validation and test must all be nonempty")
    if counts != data.get("manifest", {}).get("splits"):
        raise ValueError("manifest split counts disagree with records")
    if len(records) != data["manifest"].get("usable_rows"):
        raise ValueError("manifest total disagrees with records")
    return data


def runner_spec(raw: str) -> str | list[str]:
    """Only a runner label or list of labels; never interpolate raw input in a shell."""
    try:
        value = json.loads(raw)
    except ValueError:
        raise ValueError("set FORGE_GPU_RUNNER to a JSON label or label list") from None
    labels = [value] if isinstance(value, str) else value
    if (not isinstance(labels, list) or not labels
            or any(not isinstance(s, str) or not re.fullmatch(r"[\w .-]{1,100}", s)
                   for s in labels)):
        raise ValueError("FORGE_GPU_RUNNER must be a JSON runner label or list of labels")
    return value


def validate_minutes(raw: str) -> int:
    if not re.fullmatch(r"\d+", raw) or not 10 <= int(raw) <= 180:
        raise ValueError("training timeout must be between 10 and 180 minutes")
    return int(raw)


def encode_example(tokenizer, row: dict, max_length: int) -> dict:
    """Train on assistant tokens only. Reject, never truncate, oversized targets."""
    messages = training_example(row)["messages"]
    prefix = tokenizer.apply_chat_template(messages[:2], tokenize=True, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
    if full[:len(prefix)] != prefix:
        raise ValueError("chat template prefix mismatch; cannot safely mask the training prompt")
    if len(full) > max_length:
        raise ValueError(f"{row['source']}: {len(full)} tokens exceed max_length={max_length}")
    if len(full) <= len(prefix):
        raise ValueError("no assistant target tokens")
    return {"input_ids": full, "attention_mask": [1] * len(full),
            "labels": [-100] * len(prefix) + full[len(prefix):]}


def select_splits(data: dict, mode: str) -> dict[str, list[dict]]:
    if mode not in {"smoke", "full"}:
        raise ValueError("mode must be smoke or full")
    result = {s: [r for r in data["records"] if r["split"] == s]
              for s in ("train", "validation")}
    if mode == "smoke":
        result["train"] = result["train"][:64]
        result["validation"] = result["validation"][:16]
    return result


def accumulation_steps(row_count: int) -> int:
    """Whole update groups avoid partial-group resume bugs in the pinned Trainer.

    Never drop or duplicate a training row to make a batch fit. For this bank,
    3,965 rows use 13 microbatches per update (305 updates per full epoch).
    """
    if row_count < 1:
        raise ValueError("training split must be nonempty")
    return max(n for n in range(1, 17) if row_count % n == 0)
