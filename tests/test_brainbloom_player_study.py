"""Study reports validate exports and never substitute generated participant results."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "player_study", Path(__file__).parents[1] / "tools/player_study.py"
)
study_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study_tool)


@pytest.fixture
def study(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"id": "test-only", "cases": [{
        "id": "A", "family": "test", "level": "easy", "hints": ["Hint"],
        "item": {"choices": ["yes", "no"], "correctAnswer": "yes"},
    }]}))
    response = {"id": "A", "answer": "yes", "skipped": False, "seconds": 12.5,
                "hints": 1, "difficulty": 2, "enjoyment": 3, "clarity": 4, "notes": ""}
    return manifest, response


def export(path, responses):
    path.write_text(json.dumps({"study": "test-only", "session": "test-session",
                                "responses": responses}))
    return path


def test_report_without_participants_is_empty(study, tmp_path):
    manifest, _ = study
    report = study_tool.summarize(manifest, [])
    assert report["sessions"] == report["responses"] == 0
    assert report["results"] == []
    empty = export(tmp_path / "empty.json", [])
    assert study_tool.summarize(manifest, [empty])["sessions"] == 0


def test_report_recomputes_correctness_and_does_not_trust_client_verdict(study, tmp_path):
    manifest, response = study
    response.update(answer="no", correct=True)
    path = export(tmp_path / "response.json", [response])
    report = study_tool.summarize(manifest, [path])
    assert report["responses"] == report["sessions"] == 1
    assert report["results"][0]["correct_rate"] == 0
    assert report["results"][0]["median_seconds"] == 12.5
    with pytest.raises(ValueError, match="Duplicate"):
        study_tool.summarize(manifest, [path, path])


@pytest.mark.parametrize("field,value", [
    ("difficulty", True), ("enjoyment", 6), ("clarity", 0), ("seconds", float("nan")),
    ("seconds", float("inf")), ("seconds", -1), ("hints", 2), ("skipped", "false"),
    ("skipped", True), ("answer", None), ("answer", "unlisted"), ("id", "unknown"),
])
def test_invalid_responses_are_rejected(study, tmp_path, field, value):
    manifest, response = study
    response[field] = value
    path = export(tmp_path / "invalid.json", [response])
    with pytest.raises(ValueError):
        study_tool.summarize(manifest, [path])
