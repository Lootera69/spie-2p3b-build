"""Path B — a deterministic, LLM-free loader for the authored question bank.

The bank (``puzzle-batch/output/batch-*.json``) is ~5000 hand/pipeline-authored quiz records. This
module only *reads* it: it decodes each batch file (UTF-8, with a recorded fall-back for the rare
mis-encoded byte), and yields immutable :class:`BankRecord` objects in a fully deterministic order
(files sorted by name, records in file order). Nothing here decides anything — the auditor
(:mod:`spie.audit.audit`) is what re-proves answers. Keeping the read side pure and ordered is what
makes the audit report byte-reproducible.

``normalize`` maps a *fixed, checked-in* set of Unicode punctuation to ASCII so the rule-based
recognizers see stable text ("If p -> q" whether the source used "->" or "→"). It never touches
letters, so it cannot silently rewrite a word into a different one.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass

# Fixed Unicode -> ASCII punctuation folding for matching only. Letters (e, o, ...) are untouched.
_FOLD = {
    "—": "-", "–": "-", "−": "-",  # em/en dash, minus sign
    "→": "->", "⇒": "->",                # arrows
    "≠": "!=", "≈": "~", "≤": "<=", "≥": ">=",
    "×": "x", "·": ".",                  # multiplication sign, middle dot
    "’": "'", "‘": "'", "ʼ": "'",    # curly apostrophes
    "“": '"', "”": '"',                  # curly quotes
    "…": "...", " ": " ", " ": " ", "​": "",  # ellipsis, spaces
}
_FOLD_RE = re.compile("|".join(re.escape(k) for k in _FOLD))
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Fold the fixed punctuation set to ASCII and collapse runs of whitespace. Deterministic and
    idempotent; used only to feed the recognizers, never to alter stored record text."""
    folded = _FOLD_RE.sub(lambda m: _FOLD[m.group(0)], text)
    return _WS_RE.sub(" ", folded).strip()


@dataclass(frozen=True)
class BankRecord:
    """One authored quiz record, with a stable ``uid`` for reproducible reporting. ``choices`` is
    empty for non-multiple-choice records; ``correct_answer`` is the authored answer verbatim."""

    uid: str
    file: str
    index: int
    rec_type: str
    category: str
    difficulty: str
    title: str
    question: str
    choices: tuple[str, ...]
    correct_answer: str
    encoding: str  # the encoding that decoded this record's file ("utf-8" in the normal case)


def _decode(path: str) -> tuple[str, str]:
    """Return ``(text, encoding)`` — strict UTF-8 where possible, else a recorded byte-preserving
    fall-back. We never silently corrupt: the chosen encoding travels with every record."""
    raw = open(path, "rb").read()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def load_bank(root: str) -> tuple[BankRecord, ...]:
    """Load every ``batch-*.json`` directly under ``root`` into ordered :class:`BankRecord`s.

    Files are taken in sorted-name order and records in their in-file order, so two runs over the
    same tree yield byte-identical sequences. A file that is not a JSON array of objects is skipped
    (it contributes no records); malformed JSON raises, since a silently-dropped batch would
    understate coverage."""
    records: list[BankRecord] = []
    for path in sorted(glob.glob(os.path.join(root, "batch-*.json"))):
        text, enc = _decode(path)
        data = json.loads(text)
        if not isinstance(data, list):
            continue
        base = os.path.basename(path)
        for i, rec in enumerate(data):
            if not isinstance(rec, dict):
                continue
            choices = rec.get("choices") or ()
            records.append(
                BankRecord(
                    uid=f"{base}#{i}",
                    file=base,
                    index=i,
                    rec_type=str(rec.get("type", "")),
                    category=str(rec.get("category", "")),
                    difficulty=str(rec.get("difficulty", "")),
                    title=str(rec.get("title", "")),
                    question=str(rec.get("question", "")),
                    choices=tuple(str(c) for c in choices) if isinstance(choices, list) else (),
                    correct_answer=str(rec.get("correctAnswer", "")),
                    encoding=enc,
                )
            )
    return tuple(records)


__all__ = ["BankRecord", "load_bank", "normalize"]
