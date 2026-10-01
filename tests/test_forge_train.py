"""Offline trainer safeguards. These tests do not claim GPU training has run."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from tools.forge_train.__main__ import main
from tools.forge_train.checkpoint import REQUIRED, resume_checkpoint, seal_checkpoint
from tools.forge_train.colab import build, notebook, notebook_for_bundle
from tools.forge_train.config import COLAB_MODEL, DEFAULT_MODEL, model_profile
from tools.forge_train.data import (
    accumulation_steps,
    encode_example,
    load_corpus,
    runner_spec,
    select_splits,
    validate_minutes,
)

from spie.forge.corpus import compact, digest
from test_forge import _item


def _corpus():
    records = []
    for split, text in (("train", "Must a tagged crate be sealed?"),
                        ("validation", "Does a green signal guarantee entry?"),
                        ("test", "Does a closed gate imply an absent worker?")):
        records.append({"source": split, "split": split, "group": split, "item": _item(text)})
    return {"records": records, "manifest": {"usable_rows": 3,
            "splits": {"train": 1, "validation": 1, "test": 1}}}


def _write(path, data):
    path.write_text(compact({"data": data, "sha256": digest(data)}), encoding="utf-8")
    return path


def test_corrupt_corpus_cannot_reach_training(tmp_path):
    path = _write(tmp_path / "corpus.json", _corpus())
    assert load_corpus(path) == _corpus()
    payload = json.loads(path.read_text())
    payload["data"]["records"][0]["item"]["correctAnswer"] = "False"
    path.write_text(compact(payload))
    with pytest.raises(ValueError, match="integrity"):
        load_corpus(path)


def test_group_leakage_and_false_manifest_counts_are_fatal(tmp_path):
    data = _corpus()
    data["records"][1]["group"] = "train"
    with pytest.raises(ValueError, match="leakage"):
        load_corpus(_write(tmp_path / "group.json", data))
    data = _corpus()
    data["manifest"]["splits"]["train"] = 5000
    with pytest.raises(ValueError, match="counts"):
        load_corpus(_write(tmp_path / "counts.json", data))


def test_smoke_never_claims_full_corpus_and_test_is_never_used():
    data = _corpus()
    data["records"] += [{**data["records"][0], "source": f"train{i}"} for i in range(100)]
    assert len(select_splits(data, "smoke")["train"]) == 64
    assert len(select_splits(data, "full")["train"]) == 101
    assert "test" not in select_splits(data, "full")


class _Tokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize
        if add_generation_prompt:
            assert len(messages) == 2
            return [10, 11, 12]
        assert len(messages) == 3
        return [10, 11, 12, 20, 21, 99]


def test_training_masks_prompts_but_preserves_answer_and_end_tokens():
    encoded = encode_example(_Tokenizer(), _corpus()["records"][0], 10)
    assert encoded["input_ids"] == [10, 11, 12, 20, 21, 99]
    assert encoded["labels"] == [-100, -100, -100, 20, 21, 99]
    assert encoded["attention_mask"] == [1] * 6


def test_overlength_example_is_rejected_not_silently_truncated():
    with pytest.raises(ValueError, match="exceed"):
        encode_example(_Tokenizer(), _corpus()["records"][0], 5)


def test_incompatible_chat_template_is_fatal():
    class BadTokenizer(_Tokenizer):
        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
            if add_generation_prompt:
                return [10, 11, 777]
            return super().apply_chat_template(messages, tokenize=tokenize,
                                               add_generation_prompt=add_generation_prompt)

    with pytest.raises(ValueError, match="prefix mismatch"):
        encode_example(BadTokenizer(), _corpus()["records"][0], 10)


@pytest.mark.parametrize("value", ['', 'null', '[]', '{}', '42', '["gpu",2]', '"gpu\\nx=1"'])
def test_runner_requires_explicit_safe_configuration(value):
    with pytest.raises(ValueError):
        runner_spec(value)


def test_named_or_self_hosted_runner_configuration():
    assert runner_spec('"my-gpu-runner"') == "my-gpu-runner"
    assert runner_spec('["self-hosted","linux","gpu"]') == ["self-hosted", "linux", "gpu"]
    assert validate_minutes("120") == 120
    for value in ("0", "181", "120.0", "NaN", "15\nx=2"):
        with pytest.raises(ValueError):
            validate_minutes(value)


def test_public_repo_is_stopped_before_model_resolution(tmp_path, monkeypatch):
    path = _write(tmp_path / "corpus.json", _corpus())
    monkeypatch.setenv("REPOSITORY_PRIVATE", "false")
    monkeypatch.setenv("FORGE_GPU_RUNNER", '"gpu"')
    assert main(["preflight", "--corpus", str(path)]) == 2


def test_offline_preflight_writes_only_validated_outputs(tmp_path, monkeypatch):
    path = _write(tmp_path / "corpus.json", _corpus())
    output = tmp_path / "github-output"
    monkeypatch.setenv("REPOSITORY_PRIVATE", "true")
    monkeypatch.setenv("FORGE_GPU_RUNNER", '["self-hosted","linux","gpu"]')
    monkeypatch.setenv("TRAIN_MINUTES", "120")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main(["preflight", "--corpus", str(path)]) == 0
    assert output.read_text().splitlines() == [
        'runner=["self-hosted","linux","gpu"]', 'minutes=120',
        'revision=not-resolved-offline',
    ]


def test_stage_preserves_integrity_and_refuses_overwrite(tmp_path):
    path = _write(tmp_path / "corpus.json", _corpus())
    out = tmp_path / "staged.json"
    args = ["stage", "--corpus", str(path), "--out", str(out)]
    assert main(args) == 0
    assert load_corpus(out) == _corpus()
    assert main(args) == 2


def test_model_profiles_reject_unreviewed_models():
    assert model_profile(COLAB_MODEL)["total_gib"] == 8
    assert model_profile(DEFAULT_MODEL)["total_gib"] == 14
    with pytest.raises(ValueError, match="allowlist"):
        model_profile("unknown/model")


def test_update_groups_cover_every_row_without_partial_resume_group():
    assert accumulation_steps(3965) == 13
    assert 3965 // accumulation_steps(3965) == 305
    assert accumulation_steps(64) == 16
    for count in (1, 17, 64, 101, 3965):
        assert count % accumulation_steps(count) == 0
        assert 1 <= accumulation_steps(count) <= 16
    with pytest.raises(ValueError, match="nonempty"):
        accumulation_steps(0)


def _checkpoint(tmp_path):
    out = tmp_path / "run"
    checkpoint = out / "checkpoints/checkpoint-10"
    checkpoint.mkdir(parents=True)
    (out / "run.json").write_text(json.dumps({"resume_signature": "config"}))
    for name in REQUIRED:
        (checkpoint / name).write_text("placeholder")
    (checkpoint / "trainer_state.json").write_text(json.dumps({"global_step": 10}))
    seal_checkpoint(checkpoint, "config")
    return out, checkpoint


def test_resume_uses_complete_owned_checkpoint_and_rejects_config_drift(tmp_path):
    out, checkpoint = _checkpoint(tmp_path)
    # An interrupted newer write is not mistaken for a usable checkpoint.
    (out / "checkpoints/checkpoint-20").mkdir()
    assert resume_checkpoint(out, "auto", "config") == checkpoint.resolve()
    with pytest.raises(ValueError, match="configuration differs"):
        resume_checkpoint(out, "auto", "different")
    with pytest.raises(ValueError, match="belong"):
        resume_checkpoint(out, str(tmp_path), "config")
    with pytest.raises(ValueError, match="already exists"):
        resume_checkpoint(out, None, "config")


def test_checkpoint_corruption_is_fatal_not_silently_ignored(tmp_path):
    out, checkpoint = _checkpoint(tmp_path)
    (checkpoint / "adapter_model.safetensors").write_text("corruption")
    with pytest.raises(ValueError, match="integrity failure"):
        resume_checkpoint(out, "auto", "config")


def test_incomplete_checkpoint_cannot_be_sealed_or_resumed(tmp_path):
    out, checkpoint = _checkpoint(tmp_path)
    (checkpoint / "optimizer.pt").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        seal_checkpoint(checkpoint, "config")
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "run.json").write_text(json.dumps({"resume_signature": "config"}))
    with pytest.raises(ValueError, match="no complete checkpoint"):
        resume_checkpoint(empty, "auto", "config")


def test_notebook_cells_compile_and_have_no_outputs_or_execution():
    doc = notebook("a" * 64, "b" * 40)
    assert doc["nbformat"] == 4
    for cell in doc["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            compile("".join(cell["source"]), "<notebook>", "exec")


def test_bundle_is_minimal_private_and_byte_reproducible(tmp_path):
    root = Path(__file__).resolve().parents[1]
    corpus = _write(tmp_path / "corpus.json", _corpus())
    first = build(root, corpus, tmp_path / "first", "a" * 40)
    second = build(root, corpus, tmp_path / "second", "a" * 40)
    assert first == second
    with zipfile.ZipFile(tmp_path / "first/brainbloom-training.zip") as archive:
        names = archive.namelist()
        assert "training/brainbloom/corpus.json" in names
        assert "tools/forge_train/train.py" in names
        assert not any(".git/" in n or ".env" in n or "checkpoint-" in n for n in names)
        assert all(n.startswith(("src/spie/", "tools/forge_train/", "training/brainbloom/"))
                   or n == "bundle-manifest.json" for n in names)
        manifest = json.loads(archive.read("bundle-manifest.json"))
        assert manifest["splits"] == _corpus()["manifest"]["splits"]
    with pytest.raises(ValueError, match="exists"):
        build(root, corpus, tmp_path / "first", "a" * 40)


@pytest.mark.parametrize("version", [(3, 12, 10), (3, 13, 5), (3, 14, 0)])
def test_notebook_kernel_version_does_not_gate_training_python(version):
    cell = next(c for c in notebook("a" * 64, "b" * 40)["cells"] if c["cell_type"] == "code")
    parsed = ast.parse("".join(cell["source"]))
    parsed.body = [n for n in parsed.body if not isinstance(n, ast.Import | ast.ImportFrom)]
    calls = []
    namespace = {
        "sys": SimpleNamespace(platform="linux", version_info=version, version=str(version)),
        "subprocess": SimpleNamespace(run=lambda command, **kw: calls.append(command)),
        "shutil": SimpleNamespace(which=lambda name: "/usr/bin/" + name,
                                  disk_usage=lambda path: SimpleNamespace(free=30 * 1024**3)),
    }
    exec(compile(parsed, "<setup>", "exec"), namespace)
    assert calls == [["nvidia-smi"]]


@pytest.mark.parametrize("interpreter_version", [[3, 12, 12], [3, 13, 5]])
def test_isolated_python_setup_and_version_check(tmp_path, interpreter_version):
    cells = notebook("a" * 64, "b" * 40)["cells"]
    source = next("".join(c["source"]) for c in cells
                  if c["cell_type"] == "code" and "ENV = Path(" in "".join(c["source"]))
    source = source.replace("/content", tmp_path.as_posix())
    work = tmp_path / "work"
    requirement = work / "tools/forge_train/requirements-gpu.txt"
    requirement.parent.mkdir(parents=True)
    requirement.write_text("torch==2.6.0\n")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--managed-python" in command:
            assert command[command.index("--python") + 1] == "3.12"
            assert kwargs["env"]["UV_PYTHON_INSTALL_DIR"].startswith(tmp_path.as_posix())
            executable = Path(command[-1]) / "bin/python"
            executable.parent.mkdir(parents=True)
            executable.write_text("mock managed Python executable")

    namespace = {
        "Path": Path, "json": json, "os": os, "hashlib": hashlib, "WORK": work,
        "sys": SimpleNamespace(executable="/colab/python313"),
        "subprocess": SimpleNamespace(run=run,
                                      check_output=lambda *a, **k: json.dumps(interpreter_version)),
    }
    if interpreter_version[:2] == [3, 12]:
        exec(compile(source, "<isolated-env>", "exec"), namespace)
        assert (tmp_path / "brainbloom-venv-py312/brainbloom-ready.json").is_file()
        installs = [c for c in calls if "torch==2.6.0" in c]
        assert len(installs) == 1
        assert installs[0][0].endswith("brainbloom-venv-py312\\bin\\python") or \
            installs[0][0].endswith("brainbloom-venv-py312/bin/python")
    else:
        with pytest.raises(RuntimeError, match="must be Python 3.12"):
            exec(compile(source, "<isolated-env>", "exec"), namespace)
        assert not any("torch==2.6.0" in c for c in calls)
        assert not (tmp_path / "brainbloom-venv-py312/brainbloom-ready.json").exists()


def test_repaired_notebook_reuses_exact_original_bundle(tmp_path):
    root = Path(__file__).resolve().parents[1]
    corpus = _write(tmp_path / "corpus.json", _corpus())
    built = build(root, corpus, tmp_path / "package", "b" * 40)
    bundle = tmp_path / "package/brainbloom-training.zip"
    original = bundle.read_bytes()
    output = tmp_path / "Python312.ipynb"
    report = notebook_for_bundle(bundle, output)
    assert bundle.read_bytes() == original
    assert report["unchanged_bundle_sha256"] == built["bundle_sha256"]
    doc = json.loads(output.read_text(encoding="utf-8"))
    assert built["bundle_sha256"] in "".join(doc["cells"][1]["source"])
    with pytest.raises(ValueError, match="exists"):
        notebook_for_bundle(bundle, output)
