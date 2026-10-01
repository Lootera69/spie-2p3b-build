"""Additive sources, bounded installs, source integrity and usable topic coverage."""

import copy
import io
import json
import socket
import subprocess
from collections import Counter

import pytest

from spie.questions.brainbloom import coverage_sources
from spie.questions.brainbloom.catalog import TYPES, Request
from spie.questions.brainbloom.lexicon import DEFAULT_WORDNET, Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.topics import lookup_many

PACKS = coverage_sources.load_packs()["packs"]


@pytest.mark.parametrize("pack", PACKS, ids=[p["topic"] for p in PACKS])
@pytest.mark.parametrize("kind", TYPES)
def test_new_topics_generate_checked_offline_bundles(pack, kind, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Network or model subprocess used during generation or replay")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    result = Generator().build(Request("dictionary", kind, subject=pack["topic"],
                                       meanings={pack["topic"]: pack["id"]},
                                       topic_mode="combined", seed=31))
    assert result["summary"]["complete"]
    assert verify_bundle(json.loads(json.dumps(result))) == 1
    context = result["dictionary"]
    version = pack["id"].split(":", 1)[0]
    if version == "coverage-v1":
        # The original coverage contract remains a fixed twelve-entry pack.
        assert len(pack["entries"]) == 12
    else:
        # Reviewed v2 packs may expand the original pack capacity.
        assert len(pack["entries"]) >= 12
    assert len(context["entries"]) == len(pack["entries"])
    source = context["sources"][0]
    assert source["upstream_sha256"] == coverage_sources.OEWN_SHA256
    assert "WordNet 3.0 Copyright" in source["license"]
    assert "Creative Commons Attribution 4.0" in source["license"]
    assert source["review"]["human_review"] is False
    assert len(source["entry_sources"]) == len(pack["entries"])
    assert all(e["path"][1].startswith("editorial-topic-member:") for e in context["entries"])
    proof, item = result["proofs"][0], result["items"][0]
    if kind not in ("crossword", "wonder"):
        rule = proof["constraints"]
        bank = proof["word_bank"]
        if "letters" in rule:
            valid = [w for w in bank if Counter(w) == Counter(rule["letters"])
                     and w.startswith(rule["prefix"])]
        elif "pattern" in rule:
            valid = [w for w in bank if len(w) == len(rule["pattern"])
                     and all(x == "_" or x == y for x, y in zip(rule["pattern"], w, strict=True))]
        else:
            valid = [sorted(bank)[rule["position"] - 1]]
        assert len(valid) == 1
        expected = str(proof["claim"] in valid) if kind == "true-false" else valid[0]
        assert item["correctAnswer"] == expected


def test_counts_separate_lookup_keys_meanings_aliases_entries_and_memberships():
    dictionary = Dictionary()
    config = dictionary.configuration()
    new = next(r for r in config["sources"] if r["id"] == "coverage-v1")
    assert new["unique_senses"] == new["usable_entry_pairs"] == new["relationships"] == 96
    assert new["alias_terms"] == 14
    assert new["topic_packs"] == 8
    assert config["unique_senses"] == sum(s["unique_senses"] for s in config["sources"])
    assert config["indexed_terms"] < sum(s["indexed_terms"] for s in config["sources"])
    config["sources"][0]["indexed_terms"] = -1
    assert dictionary.configuration()["sources"][0]["indexed_terms"] >= 0


def test_pack_aliases_and_individual_senses_retain_identity():
    dictionary = Dictionary()
    for pack in PACKS:
        expected = dictionary._entries(pack["id"])
        for alias in pack["aliases"]:
            assert any(c["id"] == pack["id"] for c in dictionary._matches(alias))
            assert dictionary._entries(pack["id"]) == expected
    report = lookup_many(dictionary, "ransomware")
    # Newest authored vocabulary is automatic; older source-qualified IDs
    # remain explicit alternatives and retain their original entries.
    assert report["status"] == "ready"
    group = report["groups"][0]
    assert {choice["id"] for choice in group["choices"]} == {
        "coverage-v1:cybersecurity:ransomware",
        "coverage-v2:cybersecurity:ransomware",
    }
    assert group["selected"] == "coverage-v2:cybersecurity:ransomware"
    assert group["selection_mode"] == "automatic"
    assert report["meanings"] == {"ransomware": group["selected"]}
    for sense in sorted(choice["id"] for choice in group["choices"]):
        selected = lookup_many(dictionary, "ransomware", {"ransomware": sense})
        assert selected["status"] == "ready"
        topic = selected["context"]["topics"][0]
        assert topic["sense"] == sense
        assert topic["anchor"] == "RANSOMWARE"
        version = sense.split(":", 1)[0]
        assert all(entry["sense"].startswith(version + ":")
                   for entry in selected["context"]["entries"])


def test_legacy_packs_keep_their_exact_entries_and_sources():
    old, new = Dictionary(coverage=False), Dictionary()
    for topic in ("space", "photosynthesis", "black hole", "climate change", "quantum computing"):
        assert old.resolve(topic, "", "logic") == new.resolve(topic, "", "logic")


def test_replay_needs_neither_pack_nor_external_lexicon(monkeypatch):
    bundle = Generator().build(Request("dictionary", subject="cybersecurity"))
    monkeypatch.setattr(coverage_sources, "load_packs", lambda: pytest.fail("Loaded live pack"))
    monkeypatch.setattr(coverage_sources, "load_oewn", lambda _: pytest.fail("Loaded corpus"))
    assert verify_bundle(bundle) == 1
    changed = copy.deepcopy(bundle)
    changed["dictionary"]["source"]["entry_sources"][0]["source_sense"] = "altered"
    with pytest.raises(ValueError):
        verify_bundle(changed)


def test_installer_fails_closed_for_oversize_corrupt_or_existing_data(monkeypatch, tmp_path):
    target = tmp_path / "oewn.gz"
    monkeypatch.setattr(coverage_sources.urllib.request, "urlopen",
                        lambda *a, **kw: io.BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="SHA256"):
        coverage_sources.install_oewn(target)
    assert not target.exists()
    monkeypatch.setattr(coverage_sources, "MAX_COMPRESSED", 2)
    with pytest.raises(ValueError, match="size limit"):
        coverage_sources.install_oewn(target)
    target.write_bytes(b"existing")
    with pytest.raises(ValueError, match="already exists"):
        coverage_sources.install_oewn(target)
    assert target.read_bytes() == b"existing"


def test_source_and_pack_hashes_are_enforced(monkeypatch, tmp_path):
    broken = tmp_path / "oewn.gz"
    broken.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="SHA256"):
        coverage_sources.load_oewn(broken)
    monkeypatch.setattr(coverage_sources, "PACKS_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="SHA256"):
        Dictionary()


@pytest.fixture(scope="module")
def expanded_dictionary():
    if not DEFAULT_WORDNET.exists() or not coverage_sources.DEFAULT_OEWN.exists():
        pytest.skip("Optional pinned corpora not installed")
    return Dictionary(DEFAULT_WORDNET, oewn=coverage_sources.DEFAULT_OEWN)


def test_oewn_is_additive_and_does_not_replace_or_cross_original_senses(expanded_dictionary):
    dictionary = expanded_dictionary
    original = Dictionary(DEFAULT_WORDNET, coverage=False)
    assert dictionary.index == original.index
    assert dictionary.synsets == original.synsets
    choices = dictionary._matches("bank")
    for prefix in ("wn:", "oewn2024:"):
        sid = next(c["id"] for c in choices
                   if c["id"].startswith(prefix) and "sloping land" in c["definition"])
        entries, source = dictionary._entries(sid)
        assert all(e["sense"].startswith(prefix) for e in entries)
        assert source["sha256"] != ""
    stats = {r["id"]: r for r in dictionary.configuration()["sources"]}
    assert stats["wn30"]["indexed_terms"] == 151384
    assert stats["wn30"]["unique_senses"] == 117659
    assert stats["oewn2024"]["unique_senses"] == 120630
    assert "ransomware" not in original.index
    assert "ransomware" in dictionary.oewn_index


def test_oewn_bundle_uses_bounded_attributed_snapshot(expanded_dictionary, monkeypatch):
    dictionary = expanded_dictionary
    sid = next(c["id"] for c in dictionary._matches("vehicle")
               if c["id"].startswith("oewn2024:") and "conveyance" in c["definition"])
    engine = Generator()
    engine.dictionary = dictionary
    bundle = engine.build(Request("dictionary", subject="vehicle", sense=sid))
    assert 4 <= len(bundle["dictionary"]["entries"]) <= 80
    assert bundle["dictionary"]["source"]["sha256"] == coverage_sources.OEWN_SHA256
    monkeypatch.setattr(coverage_sources, "load_oewn", lambda _: pytest.fail("Loaded corpus"))
    assert verify_bundle(bundle) == 1
