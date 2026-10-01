"""Optional local SQLite archive of released draft fingerprints, across sessions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ...forge.corpus import digest


def fingerprint(item: dict, proof: dict) -> str:
    return ("structure:" + proof["structural_key"] if proof.get("structural_key") else
            "content:" + digest(item.get("crosswordData", item["question"])))


class History:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS drafts (fingerprint TEXT PRIMARY KEY, "
                       "item_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def keys(self) -> set[str]:
        with self.connect() as db:
            return {row[0] for row in db.execute("SELECT fingerprint FROM drafts")}

    def record(self, bundle: dict):
        rows = [(fingerprint(item, proof), digest(item))
                for item, proof in zip(bundle["items"], bundle["proofs"], strict=True)]
        try:
            with self.connect() as db:
                db.executemany("INSERT INTO drafts (fingerprint, item_hash) VALUES (?, ?)", rows)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Another request already saved this design. Generate again.") from exc
