"""Version-specific attribution and exact, offline snapshot reconstruction."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from spie.forge.corpus import digest
from spie.questions.brainbloom import coverage_sources
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle


def tool(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "tools" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "version,checksum",
    [
        ("v1", coverage_sources.PACKS_SHA256),
        ("v2", coverage_sources.PACKS_V2_SHA256),
    ],
)
def test_context_uses_its_own_frozen_snapshot_metadata(version, checksum):
    dictionary = Dictionary()
    document = json.loads(
        coverage_sources.DATA.joinpath(f"coverage-packs-{version}.json").read_bytes()
    )
    for pack in document["packs"]:
        _, source = dictionary._entries(pack["id"])
        assert source["snapshot_sha256"] == checksum
        assert source["sha256"] == digest(pack)
        assert source["review"] == document["review"]
        assert source["transformations"] == document["transformations"]
        assert source["entry_sources"] == pack["entries"]
        assert source["version"] == document["version"]
        authored = 10 if version == "v2" and pack["topic"] == "machine learning" else 0
        assert source["entry_origin_counts"] == {"oewn2024": 12, "authored-v2": authored}
        if authored:
            assert "project-authored additions" in source["attribution"]
            assert "not OEWN senses" in source["provenance_note"]
        else:
            assert "project-authored additions" not in source["attribution"]
    bundle = Generator().build(
        Request(
            "dictionary",
            "type-answer",
            seed=31,
            subject="machine learning",
            topic_mode="combined",
            meanings={"machine learning": f"coverage-{version}:machine-learning"},
        )
    )
    assert bundle["dictionary"]["sources"][0]["snapshot_sha256"] == checksum
    assert verify_bundle(bundle) == 1


def test_index_counts_include_alias_and_topic_keys_without_counting_versions_as_topics():
    dictionary = Dictionary()
    config = dictionary.configuration()
    assert len(config["packs"]) == config["unique_topic_count"] == 20
    assert config["pack_version_count"] == 28
    rows = {row["id"]: row for row in config["sources"]}
    for version, expected in (("v1", 116), ("v2", 126)):
        row = rows[f"coverage-{version}"]
        keys = {
            term
            for term, choices in dictionary.coverage_index.items()
            if any(sense.startswith(f"coverage-{version}:") for sense, _ in choices)
        }
        assert row["indexed_terms"] == len(keys) == expected
        assert row["alias_terms"] == 14
        assert row["unique_topic_count"] == row["pack_version_count"] == 8
        assert row["review"] == dictionary.coverage["versions"][f"coverage-{version}"]["review"]


def test_both_snapshots_rebuild_exact_bytes_from_pinned_upstream():
    if not coverage_sources.DEFAULT_OEWN.is_file():
        pytest.skip("Optional pinned OEWN corpus not installed")
    builder = tool("coverage_build")
    for version, checksum in (
        ("v1", coverage_sources.PACKS_SHA256),
        ("v2", coverage_sources.PACKS_V2_SHA256),
    ):
        rebuilt = builder.build(coverage_sources.DEFAULT_OEWN, version)
        assert (
            rebuilt == coverage_sources.DATA.joinpath(f"coverage-packs-{version}.json").read_bytes()
        )
        assert hashlib.sha256(rebuilt).hexdigest() == checksum
    assert builder.build.__defaults__ == ("v2",)
    with pytest.raises(ValueError, match="version"):
        builder.build(coverage_sources.DEFAULT_OEWN, "v99")


def test_benchmark_defaults_to_latest_and_retains_explicit_older_version():
    benchmark = tool("coverage_benchmark")
    dictionary = Dictionary()
    assert benchmark.select(dictionary, "machine learning") == "coverage-v2:machine-learning"
    assert benchmark.select(dictionary, "machine learning", "v1") == "coverage-v1:machine-learning"
    assert benchmark.select(dictionary, "space") == "pack:space"
    with pytest.raises(ValueError, match="coverage_version"):
        benchmark.select(dictionary, "machine learning", "v99")


def test_benchmark_records_actual_default_and_legacy_contexts(tmp_path, monkeypatch):
    benchmark = tool("coverage_benchmark")
    monkeypatch.setattr(benchmark, "SUBJECTS", ["machine learning"])
    engine = Generator()
    for name, options, namespace, count in (
        ("latest", {}, "coverage-v2", 22),
        ("legacy", {"coverage_version": "v1"}, "coverage-v1", 12),
        ("default", {"selection": "automatic"}, "coverage-v2", 22),
    ):
        report = benchmark.run_profile(engine, name, tmp_path, **options)
        assert report["selected_coverage_namespaces"] == [namespace]
        assert report["topics"][0]["usable_entries"] == count
        assert report["summary"]["generated"] == report["summary"]["replayed"] == 14
        assert report["summary"]["incorrect_quiz_answers"] == 0
        assert report["summary"]["independent_quiz_answers_checked"] == 8
        bundles = json.loads((tmp_path / f"{name}-bundles.json").read_text())
        assert len(bundles) == 14
        assert all(
            b["dictionary"]["topics"][0]["sense"].startswith(namespace + ":") for b in bundles
        )


def test_benchmark_retains_generation_measure_when_replay_fails(tmp_path, monkeypatch):
    benchmark = tool("coverage_benchmark")
    monkeypatch.setattr(benchmark, "SUBJECTS", ["machine learning"])

    def fail(_bundle):
        raise ValueError("Deliberate replay failure")

    monkeypatch.setattr(benchmark, "verify_bundle", fail)
    report = benchmark.run_profile(Generator(), "failed-replay", tmp_path)
    assert report["summary"]["generated"] == 14
    assert report["summary"]["replayed"] == 0
    assert len(json.loads((tmp_path / "failed-replay-bundles.json").read_text())) == 14
    assert all("Deliberate replay failure" in c["error"] for c in report["topics"][0]["cases"])
