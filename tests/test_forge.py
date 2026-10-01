"""The corpus writer must not confuse training, retrieval, or schema with truth."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from spie.forge.__main__ import _load, call_writer, main
from spie.forge.contract import canonical_item, issues
from spie.forge.corpus import compact, digest, prepare, split_rows
from spie.forge.propose import Brief, intake, retrieve, training_example, writing_request


def _item(question="Every sealed crate is tagged. This crate is sealed. Must it be tagged?"):
    return {
        "type": "true-false", "category": "logic", "difficulty": "easy",
        "title": "The Loading Dock", "question": question,
        "choices": ["True", "False"], "correctAnswer": "True", "xpReward": 10,
        "correctExplanation": "The stated rule applies to every sealed crate.",
        "incorrectExplanation": "The answer is True: this crate meets the rule's condition.",
        "lessonContent": "Read the rule's direction.\nCheck its condition.\n"
                         "Separate certainty from possibility.\nShare this: explain a rule.",
        "lessonGroup": "Think Straight",
    }


def _brief(count=1):
    return Brief("logic", "true-false", "easy", "warehouse conditionals", count)


def _row(item=None, source="batch-001#0", split="train"):
    return {"item": item or _item(), "source": source, "split": split, "group": source}


def test_contract_rejects_publish_flags_and_wrong_answer_options():
    assert not issues(_item())
    assert "field-set" in issues({**_item(), "published": True})
    assert "answer-choice" in issues({**_item(), "correctAnswer": "Maybe"})
    assert issues({**_item(), "choices": [None, 2]})
    assert issues({**_item(), "category": []})
    assert issues({**_item(), "type": []})


def test_only_documented_import_metadata_is_removed():
    original = {**_item(), "forgeId": "x", "forgeScore": 100}
    assert canonical_item(original) == _item()
    assert "forgeId" in original
    assert "field-set" in issues(canonical_item({**original, "published": True}))


def test_brief_fails_on_unsupported_combinations():
    for changes in ({"count": 0}, {"count": True}, {"topic": ""},
                    {"lesson_group": "Physics Fun"}, {"qtype": "sudoku"}):
        with pytest.raises(ValueError):
            replace(_brief(), **changes)


def test_numeric_and_near_duplicate_variants_cannot_cross_splits():
    rows = [_row(_item("A warehouse has 12 crates and 4 labels. Which crate has no label?")),
            _row(_item("A warehouse has 24 crates and 8 labels. Which crate has no label?"), "b"),
            _row(_item("A warehouse has 12 crates and 4 labels. Which crate has no label today?"),
                 "c")]
    result = split_rows(rows)
    assert len({r["split"] for r in result}) == 1
    assert len({r["group"] for r in result}) == 1
    assert result == split_rows(rows)


def test_retrieval_cannot_use_holdout_or_wrong_request_filters():
    rows = [_row(), _row(source="heldout", split="test"),
            _row(source="validation", split="validation"),
            _row({**_item(), "difficulty": "hard"}, "hard")]
    assert [r["source"] for r in retrieve(rows, _brief())] == ["batch-001#0"]
    request = writing_request(rows, _brief())
    assert request["reference_ids"] == ["batch-001#0"]
    assert "heldout" not in compact(request)


def test_supervised_input_does_not_contain_target_stem_or_answer():
    example = training_example(_row())
    messages = example["messages"]
    assert _item()["question"] not in messages[1]["content"]
    assert "correctAnswer" not in messages[1]["content"]
    assert json.loads(messages[2]["content"]) == {"items": [_item()]}


def test_intake_keeps_even_plausible_answer_unverified_and_unpublished():
    result = intake(compact({"items": [_item()]}), [], _brief())
    assert len(result["items"]) == 1
    assert result["intendedImport"] == {
        "createdBy": "corpus-forge", "published": False, "reviewStatus": "draft"}
    assert result["checks"]["answer_correctness"] == "unverified"
    assert result["checks"]["platform_verifier"] == "not-run"


def test_intake_rejects_old_and_within_batch_duplicates():
    response = compact({"items": [_item()]})
    assert not intake(response, [_row()], _brief())["items"]
    result = intake(compact({"items": [_item(), _item()]}), [], _brief(2))
    assert len(result["items"]) == len(result["rejected"]) == 1


def test_intake_rejects_request_mismatch_and_model_approval_claim():
    response = compact({"items": [{**_item(), "difficulty": "hard", "xpReward": 50}]})
    result = intake(response, [], _brief())
    assert "request-mismatch:difficulty" in result["rejected"][0]["issues"]
    result = intake(compact({"items": [{**_item(), "reviewStatus": "approved"}]}), [], _brief())
    assert not result["items"]


@pytest.mark.parametrize("response", ['[]', '{"items": []}', '{"items": [], "ok": true}', 'oops'])
def test_intake_does_not_repair_bad_model_output_silently(response):
    with pytest.raises(ValueError):
        intake(response, [], _brief())


def test_prepare_preserves_bank_and_excludes_demo_and_conflicting_answers(tmp_path):
    batch = tmp_path / "batch-001.validated.json"
    conflicting = {**_item(), "correctAnswer": "False"}
    usable = _item("If the light is on, the door is closed. The light is on. Is the door closed?")
    original = compact({"items": [_item(), conflicting, usable]})
    batch.write_text(original, encoding="utf-8")
    (tmp_path / "batch-000-demo.validated.json").write_text("bad demo", encoding="utf-8")
    data = prepare(tmp_path)
    assert len(data["manifest"]["quarantined"]) == 2
    assert len(data["records"]) == 1
    assert data == prepare(tmp_path)
    assert batch.read_text(encoding="utf-8") == original


def test_cli_exports_candidates_and_refuses_overwrite(tmp_path):
    bank = tmp_path / "bank"
    bank.mkdir()
    (bank / "batch-001.validated.json").write_text(compact({"items": [_item()]}))
    out = tmp_path / "prepared"
    args = ["prepare", "--bank", str(bank), "--out", str(out)]
    assert main(args) == 0
    artifact = _load(str(out / "corpus.json"))
    assert artifact["manifest"]["language_model_training"].startswith("not run")
    assert sum(len((out / f"{s}.jsonl").read_text().splitlines())
               for s in ("train", "validation", "test")) == 1
    assert main(args) == 2


def test_artifact_tampering_fails(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(compact({"data": {"changed": 1}, "sha256": digest({})}))
    with pytest.raises(ValueError, match="hash mismatch"):
        _load(str(path))


def test_writer_rejects_unsafe_endpoint_before_network():
    for endpoint in ("http://example.org/chat", "https://user:secret@example.org/chat",
                     "https://example.org/chat?key=secret", "file:///example"):
        with pytest.raises(ValueError):
            call_writer(endpoint, "model", [], None)


def test_generate_round_trip_with_stub_writer(tmp_path, monkeypatch):
    # A protocol test, not evidence that a real model generated or was trained.
    from spie.forge import __main__ as cli

    records = [_row(_item("Do all checklists eliminate every possible warehouse mistake?"))]
    data = {"records": records}
    artifact = tmp_path / "corpus.json"
    artifact.write_text(compact({"data": data, "sha256": digest(data)}), encoding="utf-8")
    monkeypatch.setattr(cli, "call_writer", lambda *a: compact({"items": [_item()]}))
    out = tmp_path / "drafts.json"
    assert main(["generate", "--corpus", str(artifact), "--out", str(out),
                 "--category", "logic", "--type", "true-false", "--difficulty", "easy",
                 "--topic", "warehouse", "--endpoint", "http://localhost:9999/v1/chat/completions",
                 "--model", "stub"]) == 0
    draft = json.loads(out.read_text(encoding="utf-8"))
    assert draft["items"][0] == _item()
    assert draft["provenance"]["reference_ids"] == [records[0]["source"]]
    assert not draft["intendedImport"]["published"]
    assert draft["provenance"]["writer"]["model"] == "stub"


def test_platform_rejection_is_load_bearing(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from spie.forge import platform

    verifier = tmp_path / "verify.ts"
    verifier.write_text("test verifier placeholder")
    report = {"items": [{"index": 0, "passed": False, "rejects": [{"rule": "unfair"}]}]}
    monkeypatch.setattr(platform.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=compact(report)))
    result = platform.check_platform(intake(compact({"items": [_item()]}), [], _brief()), verifier)
    assert not result["items"]
    assert result["rejected"][0]["stage"] == "platform-editorial"
    assert result["checks"]["answer_correctness"] == "unverified"
