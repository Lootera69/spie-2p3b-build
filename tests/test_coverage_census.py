"""Capacity census boundaries, exact traversal, and real installed pack smoke."""

import importlib.util
import json
from pathlib import Path

import pytest

from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.vocabulary import PACKS

SPEC = importlib.util.spec_from_file_location(
    "coverage_census", Path(__file__).parents[1] / "tools" / "coverage_census.py"
)
census_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(census_tool)


def synthetic_dictionary():
    dictionary = Dictionary()
    capacities = (0, 1, 3, 4, 7, 8, 11, 12, 19, 20, 79, 80, 81)
    for prefix, target in (("wn:n:", dictionary.synsets), ("oewn2024:", dictionary.oewn_synsets)):
        for capacity in capacities:
            target[f"{prefix}{capacity:03}"] = {
                "words": ["word" + chr(97 + n // 26) + chr(97 + n % 26) for n in range(capacity)],
                "definition": "Synthetic fixture",
                "links": [],
            }
    dictionary.source = {"name": "fixture"}
    return dictionary


def test_capacity_buckets_thresholds_and_bounded_examples():
    report = census_tool.census(synthetic_dictionary(), weakest_limit=3)
    for source in report["sources"]:
        if source["source_id"] not in ("wn30", "oewn2024"):
            continue
        assert source["evaluated_sense_count"] == 13
        assert source["capacity_buckets"] == {
            "0": 1,
            "1-3": 2,
            "4-7": 2,
            "8-11": 2,
            "12-19": 2,
            "20-79": 2,
            "80": 2,
        }
        assert source["threshold_counts"] == {">=4": 10, ">=8": 8, ">=12": 6, ">=20": 4}
        assert [e["capacity"] for e in source["weakest_examples"]] == [0, 1, 3]


def test_cached_function_preserves_exact_engine_traversal():
    dictionary = synthetic_dictionary()
    # Include child, parent, sibling and a cycle to exercise directed traversal.
    dictionary.synsets["wn:n:004"]["links"] = [("~", "wn:n:008"), ("@", "wn:n:020")]
    dictionary.synsets["wn:n:008"]["links"] = [("~", "wn:n:004")]
    dictionary.synsets["wn:n:020"]["links"] = [("~", "wn:n:079")]
    helper = census_tool.cached_entries(dictionary)
    for sid in [
        *dictionary.synsets,
        *dictionary.oewn_synsets,
        *("pack:" + p for p in PACKS),
        *dictionary.coverage_entries,
    ]:
        assert helper(sid) == dictionary._entries(sid)


def test_actual_packs_cli_smoke_determinism_and_no_overwrite(tmp_path):
    output = tmp_path / "census.json"
    assert census_tool.main(["--packs-only", "--out", str(output)]) == 0
    original = output.read_bytes()
    report = json.loads(original)
    assert report["inputs"]["mode"] == "packs-only"
    assert report["sources"][0]["evaluated_sense_count"] == len(PACKS)
    dictionary = Dictionary()
    pack_count = len({p["id"] for p in dictionary.coverage["packs"]})
    sources = {s["source_id"]: s for s in report["sources"]}
    for version in ("coverage-v1", "coverage-v2"):
        assert sources[version]["evaluated_sense_count"] == 8
    assert report["evaluated_sense_count"] == len(PACKS) + pack_count
    assert report["evaluated_unique_topic_count"] == 20
    assert report["evaluated_pack_version_count"] == 28
    assert sources["coverage-v1"]["threshold_counts"][">=20"] == 0
    assert sources["coverage-v2"]["threshold_counts"][">=20"] == 1
    assert all(sources[s]["evaluated_sense_count"] == 0 for s in ("wn30", "oewn2024"))
    for source in report["sources"]:
        assert sum(source["capacity_buckets"].values()) == source["evaluated_sense_count"]
    with pytest.raises(SystemExit):
        census_tool.main(["--packs-only", "--out", str(output)])
    assert output.read_bytes() == original
    second = tmp_path / "second.json"
    census_tool.main(["--packs-only", "--out", str(second)])
    assert second.read_bytes() == original


def test_full_mode_requires_installed_corpora(tmp_path):
    output = tmp_path / "census.json"
    with pytest.raises(SystemExit):
        census_tool.main(["--wordnet", str(tmp_path / "missing.zip"), "--out", str(output)])
    assert not output.exists()
