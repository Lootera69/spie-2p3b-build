"""A persistent record of certify-gate verdicts, so a multi-hour build is restartable.

The gate is the build's entire cost: every candidate word runs the full proof stack at ``seeds``
seeds (invent -> validate -> Z3 + explicit search + clingo + both epistemic methods -> conformance
-> verify -> presentation), measured at ~9.5 s/word on 8 workers. A ~3000-word vocabulary is
therefore a multi-hour run — longer than a single process here reliably lives. Without a durable
record an interruption discards every proof already completed and the build is effectively
unrunnable; with one, a re-run resumes where it stopped.

This is a **speed-up only, never a substitute for the gate.** Three properties keep it honest:

* **The key is the proof's own input.** A row is keyed by
  :func:`~tools.conceptnet_build.gate.dependency_key` — the exhaustive depth-2 sub-KB that
  ``invent`` can read — together with the seed count. A hit therefore means *this very*
  ``gate_word`` computation already ran: same neighbourhood, byte-identical puzzle, same seeds.
  None of the *selection* parameters (cap, hops, weight floor) are reused or trusted; they only
  decide which words are asked about.
* **The gate's semantics are pinned.** :data:`~tools.conceptnet_build.gate.GATE_VERSION` is written
  into the header. Bump it whenever ``gate_word`` changes what it proves, and every stored verdict
  is refused — an old ``passed`` would otherwise silently mean something weaker than the current
  gate. A missing, malformed or mismatched header is refused the same way the edge cache refuses
  one, and the build simply re-proves everything.
* **Rows land as verdicts arrive**, line-buffered and flushed, not accumulated and written at the
  end. A teardown mid-round keeps every proof that had already completed, which is the whole point.

Keys are stored as a sha256 of the sub-KB repr rather than the repr itself: the key is only ever
compared for equality, never reconstructed, and the reprs are large (a 3000-word build would write
tens of MB of them). The ``word`` column is *informational* — a verdict is a function of the
neighbourhood alone, so the same row legitimately serves any word with that neighbourhood.
"""

from __future__ import annotations

import hashlib
import os
import sys
from typing import TextIO

from .gate import Verdict

_MAGIC = "# spie-conceptnet-verdict-cache/1"


def key_digest(dependency_key: str, seeds: int) -> str:
    """The stored row key: the sub-KB and the seed count, hashed together.

    ``seeds`` is folded into the digest rather than kept as a separate column so that a verdict
    proven at fewer seeds can never answer a request for more — it is simply a miss."""
    payload = f"{seeds}\x00{dependency_key}".encode()
    return hashlib.sha256(payload).hexdigest()


def _clean(text: str) -> str:
    """Reason slugs are tab-free today; strip separators anyway so a row can never be malformed."""
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


class VerdictCache:
    """An append-only verdict log, opened for the lifetime of one build."""

    def __init__(self, path: str, *, seeds: int, gate_version: str) -> None:
        self.path = path
        self.seeds = seeds
        self.gate_version = gate_version
        self._entries: dict[str, Verdict] = {}
        self._handle: TextIO | None = None
        self.hits = 0
        self.writes = 0

    # -- reading ---------------------------------------------------------------------------

    def load(self) -> None:
        """Read any trustworthy existing log; refuse (and report) one built by a different gate."""
        if not os.path.exists(self.path):
            print(f"  verdict cache {self.path}: absent, starting empty", file=sys.stderr)
            return
        with open(self.path, encoding="utf-8") as fh:
            header = fh.readline().rstrip("\n").split("\t")
            if len(header) != 3 or header[0] != _MAGIC:
                print(
                    f"  verdict cache {self.path}: unrecognized header, ignoring", file=sys.stderr
                )
                return
            if header[1] != self.gate_version:
                print(
                    f"  verdict cache {self.path}: built by gate version {header[1]!r}, "
                    f"this gate is {self.gate_version!r}: ignoring every stored verdict",
                    file=sys.stderr,
                )
                return
            rows = 0
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 4:  # a row torn by a kill mid-write; the rest is still good
                    continue
                digest, passed, reason, _word = parts
                self._entries[digest] = (passed == "1", reason)
                rows += 1
        duplicates = rows - len(self._entries)
        extra = f", {duplicates:,} superseded" if duplicates else ""
        print(
            f"  verdict cache {self.path}: {len(self._entries):,} verdicts reusable{extra} "
            f"(gate {header[1]})",
            file=sys.stderr,
        )

    def get(self, dependency_key: str) -> Verdict | None:
        """The stored verdict for this sub-KB at this seed count, or ``None`` for a miss."""
        hit = self._entries.get(key_digest(dependency_key, self.seeds))
        if hit is not None:
            self.hits += 1
        return hit

    # -- writing ---------------------------------------------------------------------------

    def open(self) -> None:
        """Open the log for appending, writing the provenance header when it is new."""
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        fresh = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
        # A header we could not parse is replaced wholesale rather than appended to: keeping it
        # would leave a file that this loader refuses on every future run.
        if not fresh and not self._entries and not self._header_ok():
            fresh = True
            mode = "w"
        else:
            mode = "a"
        self._handle = open(self.path, mode, encoding="utf-8", newline="\n", buffering=1)
        if fresh:
            self._handle.write(f"{_MAGIC}\t{self.gate_version}\t{self.seeds}\n")
            self._handle.flush()

    def _header_ok(self) -> bool:
        with open(self.path, encoding="utf-8") as fh:
            header = fh.readline().rstrip("\n").split("\t")
        return len(header) == 3 and header[0] == _MAGIC and header[1] == self.gate_version

    def put(self, dependency_key: str, verdict: Verdict, word: str) -> None:
        """Record one verdict, on disk before this call returns."""
        digest = key_digest(dependency_key, self.seeds)
        self._entries[digest] = verdict
        if self._handle is None:
            return
        passed, reason = verdict
        self._handle.write(f"{digest}\t{'1' if passed else '0'}\t{_clean(reason)}\t{word}\n")
        self._handle.flush()
        self.writes += 1

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None

    def __enter__(self) -> VerdictCache:
        self.load()
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["VerdictCache", "key_digest"]
