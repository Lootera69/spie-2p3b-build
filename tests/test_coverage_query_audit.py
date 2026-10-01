"""Focused checks for read-only exact-query audit semantics."""

import importlib.util
import json
from pathlib import Path

import pytest

from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator

SPEC = importlib.util.spec_from_file_location(
    "coverage_query_audit", Path(__file__).parents[1] / "tools" / "coverage_query_audit.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_exact_and_segmented_are_separate():
    dictionary = Dictionary()
    exact = audit.audit_query(dictionary, "test", "space")
    segmented = audit.audit_query(dictionary, "test", "space ocean")
    assert exact["exact"]["match_count"] == 1
    assert exact["exact"]["choice_sources"]["pack"] == 1
    assert segmented["exact"]["match_count"] == 0
    assert segmented["exact"]["usable_entries_max"] is None
    assert segmented["lookup_many"]["status"] == "ready"
    assert segmented["lookup_many"]["segmented"]


def test_unknown():
    row = audit.audit_query(Dictionary(), "test", "zzzxqvunknown")
    assert row["exact"]["match_count"] == 0
    assert row["lookup_many"]["status"] == "unknown"
    assert row["lookup_many"]["unknown_terms"] == ["zzzxqvunknown"]


def test_raw_ambiguity_is_reported_separately_from_automatic_selection():
    dictionary = Dictionary()
    dictionary.source = {"name": "synthetic WordNet", "sha256": "fixture", "license": "fixture"}
    dictionary.index["bank"] = ["wn:n:1", "wn:n:2"]
    dictionary.synsets.update(
        {
            "wn:n:1": {
                "words": ["bank", "lender", "credit", "money"],
                "definition": "first",
                "links": [],
            },
            "wn:n:2": {
                "words": ["bank", "shore", "river", "water", "stream"],
                "definition": "second",
                "links": [],
            },
        }
    )
    row = audit.audit_query(dictionary, "test", "bank")
    assert row["exact"]["ambiguous"]
    assert row["exact"]["match_count"] == 2
    assert row["exact"]["usable_entries_min"] == 4
    assert row["exact"]["usable_entries_max"] == 5
    assert row["exact"]["choice_sources"]["lexical"] == 2
    assert row["lookup_many"]["status"] == "ready"
    assert row["lookup_many"]["groups"][0]["selected"] in {"wn:n:1", "wn:n:2"}
    engine = Generator()
    engine.dictionary = dictionary
    cases = audit.generation_sample(engine, [row], 1)["cases"]
    assert len(cases) == 2
    assert all(c["selection_mode"] == "automatic" for c in cases)


def test_output_no_overwrite_and_generation_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "Generator", lambda **kw: pytest.fail("Generation not requested"))
    out = tmp_path / "report.json"
    assert audit.main(["--packs-only", "--out", str(out)]) == 0
    before = out.read_bytes()
    report = json.loads(before)
    assert report["generation"]["cases"] == []
    topics = [r["query"] for r in report["queries"] if r["category"] == "coverage-pack"]
    assert len(topics) == len(set(topics)) == 8
    assert report["summary"]["coverage_topic_queries"] == 8
    with pytest.raises(SystemExit):
        audit.main(["--packs-only", "--out", str(out)])
    assert out.read_bytes() == before


def test_optional_generation_and_replay(tmp_path):
    out = tmp_path / "generated.json"
    audit.main(["--packs-only", "--generate", "1", "--out", str(out)])
    report = json.loads(out.read_text())
    cases = report["generation"]["cases"]
    assert {c["format"] for c in cases} == {"type-answer", "crossword"}
    assert all(c["generated"] and c["replay"] == "passed" for c in cases)
    assert all(c["sense"] == "coverage-v2:machine-learning" for c in cases)
    assert list(tmp_path.iterdir()) == [out]


def test_replay_failure_does_not_erase_generation(monkeypatch):
    def fail(bundle):
        raise ValueError("replay deliberately failed")

    monkeypatch.setattr(audit, "verify_bundle", fail)
    engine = Generator()
    row = audit.audit_query(engine.dictionary, "test", "space")
    result = audit.generation_sample(engine, [row], 1)
    assert all(c["generated"] and c["replay"] == "failed" for c in result["cases"])
    assert all("generation_error" not in c for c in result["cases"])


def test_generation_sample_zero_limit_does_not_generate():
    engine = Generator()
    row = audit.audit_query(engine.dictionary, "test", "space")
    result = audit.generation_sample(engine, [row], 0)
    assert result["cases"] == []
    assert result["sampled_topics"] == 0
    with pytest.raises(ValueError, match="limit"):
        audit.generation_sample(engine, [row], audit.MAX_GENERATE + 1)
