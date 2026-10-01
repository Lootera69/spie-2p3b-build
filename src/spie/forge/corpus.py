"""Read the actual question bank and make reproducible, traceable training splits.

Existing `validated` files establish prior editorial-contract checks, not factual
truth or human approval. Malformed rows are quarantined with source IDs. Numeric
variants and lexically near-identical stems stay together across train/eval.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .contract import canonical_item, issues, normalized


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(compact(value).encode("utf-8")).hexdigest()


def stem_key(text: str) -> str:
    return re.sub(r"\b\d+\b", "NUMBER", normalized(text))


def shingles(text: str) -> frozenset[str]:
    words = stem_key(text).split()
    return frozenset(" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2)))


def overlap(a: frozenset, b: frozenset) -> bool:
    """Fixed lexical threshold (4/5); no claim to detect semantic paraphrases."""
    return bool(a and b) and 5 * len(a & b) >= 4 * len(a | b)


def read_bank(root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    rows, rejected, sources = [], [], []
    files = sorted(p for p in root.glob("batch-*.validated.json")
                   if re.fullmatch(r"batch-\d{3}\.validated\.json", p.name)
                   and not p.name.startswith("batch-000"))
    if not files:
        raise ValueError(f"no production validated batches found in {root}")
    for path in files:
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(envelope, dict) or not isinstance(envelope.get("items"), list):
            raise ValueError(f"invalid batch envelope: {path.name}")
        sources.append({"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
                        "rows": len(envelope["items"])})
        for index, raw_item in enumerate(envelope["items"]):
            uid = f"{path.name}#{index}"
            item = canonical_item(raw_item) if isinstance(raw_item, dict) else raw_item
            errors = issues(item)
            if errors:
                rejected.append({"source": uid, "issues": errors})
            else:
                rows.append({"source": uid, "item": item})
    return rows, rejected, sources


def split_rows(rows: list[dict]) -> list[dict]:
    """Deduplicate exact stems; group numeric/near variants before a stable 80/10/10 split.

Conflicting authored answers for an exact stem are excluded by `prepare`, never
resolved by voting. Connected-component grouping prevents near-duplicate bridges
from leaking across splits. Semantic/family-level leakage remains unmeasured.
"""
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    inverted: dict[str, list[int]] = defaultdict(list)
    features = []
    for i, row in enumerate(rows):
        feature = shingles(row["item"]["question"])
        candidates = {j for token in feature for j in inverted[token]}
        for j in sorted(candidates):
            if overlap(feature, features[j]):
                parent[find(i)] = find(j)
        features.append(feature)
        for token in sorted(feature):
            inverted[token].append(i)
    members: dict[int, list[int]] = defaultdict(list)
    for i in range(len(rows)):
        members[find(i)].append(i)
    result = []
    for group in members.values():
        key = min(stem_key(rows[i]["item"]["question"]) for i in group)
        group_id = digest(key)
        bucket = int(group_id[:8], 16) % 10
        split = "test" if bucket == 0 else "validation" if bucket == 1 else "train"
        for i in group:
            result.append({**rows[i], "group": group_id, "split": split})
    return sorted(result, key=lambda row: row["source"])


def prepare(root: Path) -> dict:
    rows, rejected, sources = read_bank(root)
    by_stem: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_stem[normalized(row["item"]["question"])].append(row)
    unique = []
    duplicates = []
    for group in by_stem.values():
        answers = {normalized(row["item"]["correctAnswer"]) for row in group}
        if len(answers) != 1:
            rejected.extend({"source": row["source"], "issues": ["conflicting-answer"]}
                            for row in group)
        else:
            unique.append(group[0])
            duplicates.extend({"source": row["source"], "duplicate_of": group[0]["source"]}
                              for row in group[1:])
    records = split_rows(unique)
    if not records:
        raise ValueError("no training candidates remain after contract checks")
    manifest = {
        "version": 1, "source_sha256": digest(sources), "sources": sources,
        "input_rows": sum(s["rows"] for s in sources), "usable_rows": len(records),
        "splits": dict(sorted(Counter(r["split"] for r in records).items())),
        "categories": dict(sorted(Counter(r["item"]["category"] for r in records).items())),
        "quarantined": rejected, "duplicates": duplicates,
        "split_method": "normalized/numeric/4-of-5 lexical groups, SHA256 buckets 80/10/10",
        "answer_verification": "not established by these contract checks",
        "human_review": "not established by source validated status",
        "language_model_training": "not run; these are supervised training candidates",
    }
    return {"manifest": manifest, "records": records}
