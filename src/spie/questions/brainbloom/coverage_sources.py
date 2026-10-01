"""Versioned, additive lexical sources. Network access is installer-only."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from importlib.resources import files
from pathlib import Path

from spie.forge.corpus import digest

OEWN_URL = "https://en-word.net/static/english-wordnet-2024.xml.gz"
OEWN_SHA256 = "e1f633b0a93758cae34ea27c44c4dad310a8af2467b155f99dd6673af697e875"
DEFAULT_OEWN = Path(".brainbloom/english-wordnet-2024.xml.gz")
MAX_COMPRESSED = 20_000_000
MAX_EXPANDED = 150_000_000
PACKS_SHA256 = "e2ce3449bcff2183830ead449272529c032070c64e66d60c9c4e0a3f2874d1cb"
PACKS_V2_SHA256 = "f6bffdfde85e40dfcc6748fdf348f624022174cbe2fff631735bcbafc2931dad"
LICENSE_SHA256 = "5d02a553699c4841d8b33cc5a1313cff1f96264e36e9dc98be829dfc94a6cc73"
DATA = files("spie.questions.brainbloom").joinpath("data")
RELATIONS = {
    "hyponym": "~",
    "instance_hyponym": "~i",
    "mero_part": "%p",
    "mero_member": "%m",
    "mero_substance": "%s",
    "hypernym": "@",
    "instance_hypernym": "@i",
}


def _checked(data: bytes, expected: str, label: str) -> bytes:
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{label} SHA256 mismatch; install the pinned source")
    return data


def source() -> dict:
    license_text = _checked(
        DATA.joinpath("oewn-2024-license.md").read_bytes(), LICENSE_SHA256, "OEWN licence"
    ).decode("utf-8")
    return {
        "name": "Open English WordNet 2024",
        "version": "2024",
        "sha256": OEWN_SHA256,
        "url": OEWN_URL,
        "license": license_text,
        "attribution": "Princeton WordNet and the Open English Wordnet team",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "license_sha256": LICENSE_SHA256,
        "license_source_url": "https://raw.githubusercontent.com/globalwordnet/english-wordnet/"
        "2024-edition/LICENSE.md",
        "transformations": "Source-qualified IDs; bounded lexical graph traversal",
    }


def install_oewn(path: Path) -> None:
    """Explicit bounded download, pinned hash, no overwrite or implicit upgrades."""
    if path.exists():
        raise ValueError(f"Dictionary already exists: {path}")
    with urllib.request.urlopen(OEWN_URL, timeout=60) as response:
        data = response.read(MAX_COMPRESSED + 1)
    if len(data) > MAX_COMPRESSED:
        raise ValueError("OEWN download exceeds the size limit")
    _checked(data, OEWN_SHA256, "OEWN")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def load_oewn(path: Path) -> tuple[dict, dict, dict]:
    if not path.is_file():
        raise ValueError(f"No OEWN corpus at {path}; run `oewn-install` or omit --oewn")
    if path.stat().st_size > MAX_COMPRESSED:
        raise ValueError("OEWN file exceeds the size limit")
    data = _checked(path.read_bytes(), OEWN_SHA256, "OEWN")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        xml = stream.read(MAX_EXPANDED + 1)
    if len(xml) > MAX_EXPANDED:
        raise ValueError("OEWN expanded data exceeds the size limit")
    # Only hash-verified XML reaches the standard parser; no DTD is fetched.
    synsets, index, members = {}, defaultdict(list), defaultdict(list)
    lemmas, forms, associations = set(), set(), 0
    for _, element in ET.iterparse(io.BytesIO(xml), events=("end",)):
        if element.tag == "LexicalEntry":
            lemma = element.find("Lemma").get("writtenForm")
            variants = [f.get("writtenForm") for f in element.findall("Form")]
            lemmas.add(lemma.casefold())
            forms.update(f.casefold() for f in variants)
            for sense in element.findall("Sense"):
                sid = "oewn2024:" + sense.get("synset")
                associations += 1
                if lemma not in members[sid]:
                    members[sid].append(lemma)
                for term in [lemma, *variants]:
                    key = term.casefold()
                    if sid not in index[key]:
                        index[key].append(sid)
            element.clear()
        elif element.tag == "Synset":
            sid = "oewn2024:" + element.get("id")
            links = [
                (RELATIONS[r.get("relType")], "oewn2024:" + r.get("target"))
                for r in element.findall("SynsetRelation")
                if r.get("relType") in RELATIONS
            ]
            synsets[sid] = {"definition": element.findtext("Definition"), "links": links}
            element.clear()
    for sid, node in synsets.items():
        node["words"] = [w.replace(" ", "_") for w in members[sid]]
        if any(target not in synsets for _, target in node["links"]):
            raise ValueError("OEWN relationship target missing")
    stats = lexical_counts(index, synsets)
    stats.update(
        lemma_terms=len(lemmas),
        alias_terms=len(forms - lemmas),
        lexical_sense_associations=associations,
    )
    return synsets, index, stats


def lexical_counts(index: dict, synsets: dict) -> dict:
    entries = {
        (re.sub(r"[_-]", "", w), sid)
        for sid, node in synsets.items()
        for w in node["words"]
        if re.fullmatch(r"[a-z]{3,15}", re.sub(r"[_-]", "", w))
    }
    return {
        "indexed_terms": len(index),
        "unique_senses": len(synsets),
        "usable_entry_pairs": len(entries),
        "usable_spellings": len({w for w, _ in entries}),
        "relationships": sum(len(set(map(tuple, n["links"]))) for n in synsets.values()),
    }


def pack_source(pack: dict, version_metadata: dict) -> dict:
    """Describe one frozen pack without attributing authored additions to OEWN.

    Snapshot review/transformations remain verbatim for reproducibility. The
    origin note clarifies v2's mixed provenance without rewriting pinned data.
    """
    upstream_count = sum(e["source_sense"].startswith("oewn2024:") for e in pack["entries"])
    authored_count = sum(e["source_sense"].startswith("authored-v2:") for e in pack["entries"])
    if upstream_count + authored_count != len(pack["entries"]):
        raise ValueError("Unknown coverage entry origin")
    version = pack["id"].split(":", 1)[0].removeprefix("coverage-")
    provenance = (
        f"{upstream_count} entries select exact OEWN 2024 senses with adapted clues; "
        "the OEWN and Princeton notices apply to that derived material."
    )
    attribution = "Princeton WordNet and the Open English Wordnet team"
    if authored_count:
        provenance += (
            f" {authored_count} entries identified by authored-v2: are original "
            "BrainBloom project definitions, not OEWN senses or source definitions."
        )
        attribution += "; BrainBloom project-authored additions (authored-v2: entries)"
    return {
        **source(),
        **version_metadata,
        "name": f"Coverage topic packs {version} / {pack['topic']}",
        "sha256": digest(pack),
        "attribution": attribution,
        "entry_sources": pack["entries"],
        "entry_origin_counts": {"oewn2024": upstream_count, "authored-v2": authored_count},
        "provenance_note": provenance,
    }


def load_packs() -> dict:
    documents = []
    versions = {}
    for filename, checksum, schema in (
        ("coverage-packs-v1.json", PACKS_SHA256, 1),
        ("coverage-packs-v2.json", PACKS_V2_SHA256, 2),
    ):
        payload = _checked(DATA.joinpath(filename).read_bytes(), checksum, "Coverage packs")
        result = json.loads(payload)
        if result.get("schema") != schema or result.get("version") != f"coverage-packs-v{schema}":
            raise ValueError("Invalid coverage pack version")
        versions[f"coverage-v{schema}"] = {
            "version": result["version"],
            "snapshot_sha256": checksum,
            "upstream_sha256": result["source_sha256"],
            "review": result["review"],
            "transformations": result["transformations"],
        }
        documents.append(result)
    result = {
        "schema": 2,
        "version": "coverage-packs-v2",
        "packs": [],
        "versions": versions,
        "review": documents[-1]["review"],
        "transformations": documents[-1]["transformations"],
    }
    for document in documents:
        result["packs"].extend(document["packs"])
    if len(result["packs"]) > 32:
        raise ValueError("Invalid coverage pack size")
    seen = set()
    for pack in result["packs"]:
        if pack["id"] in seen or not re.fullmatch(r"coverage-v[12]:[a-z0-9-]+", pack["id"]):
            raise ValueError("Invalid coverage pack identity or capacity")
        if not 4 <= len(pack["entries"]) <= 80 or not pack.get("topic"):
            raise ValueError("Invalid coverage pack capacity")
        seen.add(pack["id"])
        words = set()
        for entry in pack["entries"]:
            if (
                not re.fullmatch(r"[A-Z]{3,15}", entry["word"])
                or entry["word"] in words
                or not entry.get("lemma")
                or not entry.get("source_sense", "").startswith(("oewn2024:", "authored-v2:"))
                or not entry["source_definition"]
            ):
                raise ValueError("Invalid coverage pack entry")
            words.add(entry["word"])
    return result
