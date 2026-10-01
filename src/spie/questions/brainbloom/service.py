"""Read-only bank comparison and optional existing Studio editorial verification."""

from __future__ import annotations

import json
from pathlib import Path

from ...forge.corpus import compact, digest, read_bank
from ...forge.platform import check_platform
from . import workshop
from .catalog import Request as WorkshopRequest
from .generate import VERSION, Request, candidate, generate
from .lexicon import Dictionary, validate_context
from .topics import resolve_many


class Generator:
    def __init__(self, bank: Path | None = None, verifier: Path | None = None,
                 wordnet: Path | None = None, history: Path | None = None,
                 *, oewn: Path | None = None, coverage: bool = True):
        from .history import History

        self.history = History(history) if history is not None else None
        self.dictionary = Dictionary(wordnet, oewn=oewn, coverage=coverage)
        self.verifier = verifier.resolve(strict=True) if verifier is not None else None
        self.existing: tuple[dict, ...] = ()
        self.bank_manifest: dict | None = None
        if bank is not None:
            rows, rejected, sources = read_bank(bank)
            self.existing = tuple(r["item"] for r in rows)
            self.bank_manifest = {
                "files": len(sources),
                "source_manifest_sha256": digest(sources),
                "rows_compared": len(rows),
                "malformed_rows_excluded": len(rejected),
                "scope": "lexical duplicate checks only; no training or answer inference",
            }

    def build(self, request: Request | WorkshopRequest) -> dict:
        excluded = self.history.keys() if self.history is not None else set()
        build = workshop.generate if isinstance(request, WorkshopRequest) else generate
        if (isinstance(request, WorkshopRequest)
                and request.topic in ("dictionary", "reasoning", "autopilot", "activities")):
            context = (resolve_many(self.dictionary, request.subject, request.meanings,
                                    request.category) if request.topic_mode == "combined"
                       else self.dictionary.resolve(
                           request.subject, request.sense, request.category))
            result = workshop.generate(request, self.existing, context, excluded=excluded)
        else:
            result = (build(request, self.existing, excluded=excluded)
                      if isinstance(request, WorkshopRequest) else build(request, self.existing))
        result["provenance"]["bank"] = self.bank_manifest
        if self.verifier is not None and request.qtype in {
            "multiple-choice",
            "true-false",
            "type-answer",
            "riddle",
        }:
            result = check_platform(result, self.verifier)
            # The editorial gate can reject otherwise formally correct drafts.
            # Keep proofs aligned with accepted items; never present a partial
            # batch as though it met the requested count.
            retained = {digest(item) for item in result["items"]}
            result["proofs"] = [p for p in result["proofs"] if p["item_sha256"] in retained]
        elif self.verifier is not None:
            result["checks"]["platform_verifier"] = {
                "status": "not-supported-for-type",
                "scope": (
                    "Studio's quiz verifier supports four quiz types; "
                    "native crossword/Wonder contracts checked locally"
                ),
            }
        result["summary"] = {
            "requested": request.count,
            "accepted": len(result["items"]),
            "rejected": len(result["rejected"]),
            "complete": len(result["items"]) == request.count,
            "published": False,
        }
        if self.history is not None:
            self.history.record(result)
            result["provenance"]["history"] = {
                "compared": len(excluded), "recorded": len(result["items"]),
                "scope": "local draft fingerprints across sessions; replay ignores history",
            }
        return result


def verify_bundle(bundle: object) -> int:
    """Re-generate and re-prove retained drafts, not just trust a stored stamp.

    Does not authenticate a file's author or re-run Studio/duplicate review.
    Reproduction is pinned to this generator and solver version.
    """
    if not isinstance(bundle, dict):
        raise ValueError("Bundle must be a JSON object")
    version = bundle.get("version")
    if type(version) is not int or (bundle.get("generator"), version) not in {
        (VERSION, 1),
        (workshop.VERSION, 2),
        (workshop.DICTIONARY_VERSION, 3),
        (workshop.REASONING_VERSION, 4),
        (workshop.TOPIC_VERSION, 5),
        (workshop.GRID_VERSION, 6),
        (workshop.AUTOPILOT_VERSION, 7),
        (workshop.ACTIVITIES_VERSION, 8),
    }:
        raise ValueError("Unsupported generator/version")
    if bundle.get("intendedImport") != {
        "createdBy": "symbolic-generator",
        "reviewStatus": "draft",
        "published": False,
    }:
        raise ValueError("Bundle must remain an unpublished draft")
    if not isinstance(bundle.get("request"), dict):
        raise ValueError("Bundle request must be an object")
    try:
        fields = dict(bundle["request"])
        if version != 1:
            fields.setdefault("engine_revision", 1)
        request = (Request if version == 1 else WorkshopRequest)(**fields)
    except TypeError as exc:
        raise ValueError("Invalid bundle request") from exc
    context = None
    if (version == 6) != (getattr(request, "topic", None) == "logic-grid"):
        raise ValueError("Custom logic grids require version 6")
    if (version == 7) != (getattr(request, "topic", None) == "autopilot"):
        raise ValueError("Autopilot designs require version 7")
    if (version == 8) != (getattr(request, "topic", None) == "activities"):
        raise ValueError("Discovery activities require version 8")
    if version in (3, 4, 5, 7, 8):
        context = validate_context(bundle.get("dictionary"))
        expected_topics = ("activities",) if version == 8 else (
            ("autopilot",) if version == 7 else (
            ("dictionary", "reasoning") if version == 5 else (
            "reasoning" if version == 4 else "dictionary",
        )))
        if (request.topic not in expected_topics
                or context["subject"] != ((request.subject.strip() if version in (5, 7, 8)
                                           else request.subject) or request.category)
                or (request.sense and context["sense"] != request.sense)):
            raise ValueError("Dictionary snapshot does not match the request")
        if version in (5, 7, 8):
            if request.topic_mode != "combined" or "topics" not in context:
                raise ValueError("Combined-topic drafts require all selected topic records")
            selected = {t["term"]: t["sense"] for t in context["topics"]}
            if request.meanings != selected:
                raise ValueError("Saved meanings do not match the request")
        elif request.topic_mode != "single" or "topics" in context:
            raise ValueError("Combined-topic drafts require version 5")
    elif version == 2 and request.topic in ("dictionary", "reasoning"):
        raise ValueError("Topic-driven requests require a versioned dictionary snapshot")
    items, proofs = bundle.get("items"), bundle.get("proofs")
    if not isinstance(items, list) or not isinstance(proofs, list) or len(items) != len(proofs):
        raise ValueError("Item/proof count mismatch")
    if not items:
        raise ValueError("No retained drafts to verify")
    rejected = bundle.get("rejected")
    if (
        not isinstance(rejected, list)
        or any(not isinstance(r, dict) for r in rejected)
        or len(items) + len(rejected) != request.count
    ):
        raise ValueError("Saved draft count does not match the request")
    if "summary" in bundle and compact(bundle["summary"]) != compact(
        {
            "requested": request.count,
            "accepted": len(items),
            "rejected": len(rejected),
            "complete": len(items) == request.count,
            "published": False,
        }
    ):
        raise ValueError("Saved summary does not match retained drafts")
    seen: set[str] = set()
    structures: set[str] = set()
    previous_seed = request.seed - 1
    for item, proof in zip(items, proofs, strict=True):
        if not isinstance(item, dict) or not isinstance(proof, dict):
            raise ValueError("Each item and proof must be an object")
        seed = proof.get("seed")
        if (
            type(seed) is not int
            or not previous_seed < seed
            or not request.seed <= seed < request.seed + request.count * 30
        ):
            raise ValueError("Invalid candidate seed")
        previous_seed = seed
        expected_item, expected_proof = (
            candidate(request, seed) if version == 1
            else workshop.candidate(request, seed, context)
        )
        if digest(item) in seen:
            raise ValueError("Duplicate item in saved bundle")
        seen.add(digest(item))
        if compact(item) != compact(expected_item) or compact(proof) != compact(expected_proof):
            raise ValueError("Saved item/proof does not match freshly checked generation")
        structural = workshop.structure_key(proof)
        if structural is not None:
            if structural in structures:
                raise ValueError("Repeated reasoning structure in saved batch")
            structures.add(structural)
    return len(items)


def write_bundle(path: Path, result: dict) -> None:
    """Explicit local export, exclusive creation; never overwrite an existing run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
