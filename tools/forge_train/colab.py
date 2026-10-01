"""Build a private, minimal Colab bundle and a standard, output-free notebook.

This does not upload data, allocate a GPU, install packages or start training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import textwrap
import zipfile
from pathlib import Path

from spie.forge.corpus import compact, digest

from .config import COLAB_MODEL
from .data import load_corpus


def _cell(kind: str, source: str) -> dict:
    source = textwrap.dedent(source).strip() + "\n"
    cell = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        compile(source, "<notebook>", "exec")
        cell.update({"execution_count": None, "outputs": []})
    return cell


def notebook(bundle_hash: str, revision: str) -> dict:
    cells = [
        _cell("markdown", """
        # BrainBloom — train your question generator (free Colab)

        This tunes **Qwen2.5-1.5B-Instruct** on 3,965 of your questions. 490 are for
        validation; 519 are held out. It starts with an 8-update smoke test, then
        runs one training epoch and creates base/tuned comparison drafts.

        **Use Runtime → Change runtime type → T4 GPU, then Run all.** Do not choose
        paid compute or upgrade. Free GPU availability/time limits are controlled
        by Google. If no free GPU is available, stop and try another time normally.
        Stay within Colab's interactive notebook rules; no keep-alives or remote servers.

        Upload `brainbloom-training.zip` when asked and approve the Drive connection
        yourself. Drive retains private checkpoints if the session disconnects.
        Do not share this notebook with saved outputs, the ZIP, or the Drive run folder.
        Drive access is a Google permission decision, not a requirement to pay.

        Training has **not** been run merely by creating this notebook. Its measured
        time estimate appears after four optimizer updates. Model loss and schema
        checks do **not** prove answer correctness or useful question quality.
        All outputs are unpublished drafts. Nothing connects to Firebase or GitHub.
        """),
        _cell("code", f'''
        import hashlib, json, os, shutil, subprocess, sys, zipfile
        from pathlib import Path, PurePosixPath
        from google.colab import files, drive

        MODEL = {COLAB_MODEL!r}
        REVISION = {revision!r}
        EXPECTED_BUNDLE_SHA256 = {bundle_hash!r}
        # Retain this name to resume. Change only to deliberately start a separate run.
        RUN_NAME = "brainbloom-qwen15-v1"
        print("Notebook Python:", sys.version.split()[0])
        assert sys.platform == "linux", "Use a hosted Linux Colab GPU runtime."
        # The notebook kernel may be newer; training gets its own Python 3.12 below.
        if shutil.which("nvidia-smi") is None:
            raise RuntimeError("No NVIDIA GPU. Select Runtime > Change runtime type > T4 GPU.")
        subprocess.run(["nvidia-smi"], check=True)
        assert shutil.disk_usage("/content").free >= 20 * 1024**3, "Need 20 GiB free local disk."
        print("GPU visible. Use only your free Colab allocation; no paid resources requested.")
        '''),
        _cell("markdown", """
        ## Private upload and persistent storage

        The following cell requests Google Drive access. Review and approve it
        yourself. It writes only a new `MyDrive/BrainBloom-training` run folder.
        On reconnection the saved ZIP is reused; no repeated question-bank upload.
        """),
        _cell("code", '''
        drive.mount("/content/drive")
        STORE = Path("/content/drive/MyDrive/BrainBloom-training") / RUN_NAME
        STORE.mkdir(parents=True, exist_ok=True)
        bundle = STORE / "brainbloom-training.zip"
        if not bundle.exists():
            uploaded = files.upload()
            assert set(uploaded) == {"brainbloom-training.zip"}, "Select only the training ZIP."
            raw = uploaded["brainbloom-training.zip"]
            assert hashlib.sha256(raw).hexdigest() == EXPECTED_BUNDLE_SHA256, "Wrong ZIP."
            with bundle.open("xb") as stream:
                stream.write(raw)
        assert hashlib.sha256(bundle.read_bytes()).hexdigest() == EXPECTED_BUNDLE_SHA256, \
            "Saved ZIP differs; use its matching notebook or a new RUN_NAME."
        WORK = Path("/content/brainbloom-work")
        WORK.mkdir(exist_ok=True)
        with zipfile.ZipFile(bundle) as archive:
            names = archive.namelist()
            manifest = json.loads(archive.read("bundle-manifest.json"))
            assert len(names) == len(set(names)), "Duplicate archive member."
            assert set(names) == set(manifest["files"]) | {"bundle-manifest.json"}
            for name, expected in manifest["files"].items():
                path = PurePosixPath(name)
                assert not path.is_absolute() and ".." not in path.parts and "\\\\" not in name
                raw = archive.read(name)
                assert hashlib.sha256(raw).hexdigest() == expected, "Bundle file hash mismatch."
                dest = WORK.joinpath(*path.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
        os.environ["PYTHONPATH"] = str(WORK / "src") + os.pathsep + str(WORK)
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        print("Private bundle verified:", manifest["splits"])
        '''),
        _cell("markdown", """
        ## Isolated training environment

        This downloads packages from PyPI/the official PyTorch wheel index and the
        public base weights from Hugging Face. No Hugging Face token is required.
        A separate **Python 3.12** environment preserves Colab's notebook Python and
        preinstalled packages, including on newer notebook kernels. The pinned uv
        package from PyPI installs managed Python using Astral's python-build-standalone
        distribution. First setup downloads several GB; setup time is not included
        in the training estimate. No runtime downgrade or kernel restart is needed.
        """),
        _cell("code", '''
        ENV = Path("/content/brainbloom-venv-py312")
        if not (ENV / "bin/python").exists():
            if ENV.exists():
                raise RuntimeError("Incomplete training environment; choose a new ENV directory.")
            BOOTSTRAP = Path("/content/brainbloom-bootstrap-uv01219")
            if not (BOOTSTRAP / "uv/__main__.py").is_file():
                subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps",
                                "--only-binary=:all:", "--target", str(BOOTSTRAP),
                                "--index-url", "https://pypi.org/simple", "uv==0.12.19"],
                               check=True)
            bootstrap_env = os.environ.copy()
            bootstrap_env["PYTHONPATH"] = str(BOOTSTRAP)
            bootstrap_env["UV_PYTHON_INSTALL_DIR"] = "/content/brainbloom-managed-python"
            bootstrap_env["UV_CACHE_DIR"] = "/content/brainbloom-uv-cache"
            subprocess.run([sys.executable, "-m", "uv", "venv", "--managed-python",
                            "--python", "3.12", "--seed", str(ENV)],
                           env=bootstrap_env, check=True)
        PYTHON = str(ENV / "bin/python")
        interpreter = json.loads(subprocess.check_output([
            PYTHON, "-c", "import json, sys; print(json.dumps(list(sys.version_info[:3])))"
        ], text=True))
        if interpreter[:2] != [3, 12]:
            raise RuntimeError(f"Training interpreter must be Python 3.12; found {interpreter}")
        print("Isolated training Python:", ".".join(map(str, interpreter)))
        def run(arguments):
            subprocess.run([PYTHON, *arguments], cwd=WORK, env=os.environ.copy(), check=True)
        ready = ENV / "brainbloom-ready.json"
        requirements_hash = hashlib.sha256(
            (WORK / "tools/forge_train/requirements-gpu.txt").read_bytes()).hexdigest()
        if not ready.exists() or json.loads(ready.read_text())["requirements"] != requirements_hash:
            run(["-m", "pip", "install", "--no-cache-dir", "torch==2.6.0",
                 "--index-url", "https://download.pytorch.org/whl/cu124"])
            run(["-m", "pip", "install", "--no-cache-dir", "-r",
                 "tools/forge_train/requirements-gpu.txt"])
            run(["-m", "pip", "check"])
            run(["-c", "import torch, transformers, peft, bitsandbytes; "
                 "assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"])
            ready.write_text(json.dumps({"requirements": requirements_hash}))
        print("Training dependencies import successfully. No paid services configured.")
        '''),
        _cell("markdown", """
        ## Benchmark, then one full epoch

        Every example is tokenized without truncation; oversized records stop the
        run. Checkpoints are sealed with hashes every ten updates, retaining two.
        Re-run the notebook after a normal disconnect to resume the newest complete
        checkpoint with the same model, data, code and package versions. An incomplete
        first run with no checkpoint needs a new RUN_NAME; it is never overwritten.

        Smoke estimates are approximate: only 64 training examples are sampled.
        The notebook stops if its estimated training time exceeds eight hours.
        It does not bypass quotas, retry unavailable GPUs, or upgrade your account.
        """),
        _cell("code", '''
        CORPUS = str(WORK / "training/brainbloom/corpus.json")
        def train_mode(mode):
            output = STORE / mode
            if (output / "run.json").exists():
                status = json.loads((output / "run.json").read_text())["status"]
                expected = "smoke_completed" if mode == "smoke" else "full_epoch_completed"
                if status == expected:
                    print(mode, "already completed; preserved.")
                    return
            arguments = ["-m", "tools.forge_train", "train", "--corpus", CORPUS,
                         "--out", str(output), "--mode", mode, "--model", MODEL,
                         "--revision", REVISION, "--max-length", "2048", "--preview-count", "4"]
            if output.exists():
                arguments += ["--resume", "auto"]
            run(arguments)

        train_mode("smoke")
        progress = json.loads((STORE / "smoke/progress.json").read_text())
        estimate = progress["full_epoch_training_seconds_estimate"]
        print("Measured estimate for training only:", round(estimate / 3600, 2), "hours")
        assert estimate <= 8 * 3600, "Estimate exceeds eight hours; stop before full run."
        train_mode("full")
        report = json.loads((STORE / "full/run.json").read_text())
        print(json.dumps({k: report[k] for k in
                         ("status", "used_split_counts", "optimizer_steps", "quality_status")},
                         indent=2))
        '''),
        _cell("markdown", """
        ## Generate a question from your own inputs

        Edit the four fields below and run this cell again. It generates one new
        draft and saves raw output even if JSON/contract checks fail. Correctness
        is unverified; review before importing into BrainBloom Studio. More kinds
        need more training examples: this bank covers MCQ, true-false, type-answer,
        and riddle only. Repeating identical inputs uses deterministic decoding.
        """),
        _cell("code", '''
        CATEGORY = "logic" # @param {type:"string"}
        QUESTION_TYPE = "multiple-choice" # @param {type:"string"}
        DIFFICULTY = "medium" # @param ["easy", "medium", "hard"]
        TOPIC = "conditional reasoning in a warehouse" # @param {type:"string"}
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        draft_path = STORE / "drafts" / (stamp + ".json")
        run(["-m", "tools.forge_train.generate", "--run", str(STORE / "full"),
             "--corpus", CORPUS, "--out", str(draft_path), "--category", CATEGORY,
             "--type", QUESTION_TYPE, "--difficulty", DIFFICULTY, "--topic", TOPIC])
        print("Unpublished draft saved:", draft_path)
        '''),
        _cell("markdown", """
        ## Results

        In Drive: `BrainBloom-training/brainbloom-qwen15-v1/full/` contains the adapter,
        run diagnostics and `previews.json` with base/tuned comparison drafts.
        `drafts/` contains questions from your inputs. Review those comparisons;
        lower loss is not proof that the tuned model is better. Keep the adapter
        private. Hosting in the app is a separate integration, not provided by a
        temporary training notebook. Disconnect the runtime when finished.
        """),
    ]
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": {
        "colab": {"name": "BrainBloom-Free-Training.ipynb", "provenance": []},
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}, "accelerator": "GPU",
    }, "cells": [{**cell, "id": f"brainbloom-{i:02d}"} for i, cell in enumerate(cells)]}


def build(root: Path, corpus: Path, out: Path, revision: str) -> dict:
    import re

    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("immutable model revision required")
    if out.exists():
        raise ValueError("bundle output exists; choose a new directory")
    data = load_corpus(corpus)
    paths = [root / "src/spie/__init__.py", root / "tools/forge_train/requirements-gpu.txt"]
    paths += sorted((root / "src/spie/forge").glob("*.py"))
    paths += sorted((root / "tools/forge_train").glob("*.py"))
    payload = {p.relative_to(root).as_posix(): p.read_bytes() for p in paths}
    payload["training/brainbloom/corpus.json"] = corpus.read_bytes()
    manifest = {"version": 1, "model": COLAB_MODEL, "revision": revision,
                "corpus_sha256": digest(data), "splits": data["manifest"]["splits"],
                "files": {k: hashlib.sha256(v).hexdigest() for k, v in payload.items()}}
    payload["bundle-manifest.json"] = compact(manifest).encode("utf-8")
    out.mkdir(parents=True)
    bundle = out / "brainbloom-training.zip"
    with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw)
    bundle_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
    doc = notebook(bundle_hash, revision)
    (out / "BrainBloom-Free-Training.ipynb").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {**manifest, "bundle_sha256": bundle_hash, "bundle_bytes": bundle.stat().st_size,
               "status": "prepared locally; not uploaded or trained"}
    (out / "package-report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def notebook_for_bundle(bundle: Path, out: Path) -> dict:
    """Repair notebook setup without changing the user's ZIP or checkpoint code hashes."""
    import re

    if out.exists():
        raise ValueError("notebook output exists; choose a new filename")
    raw = bundle.read_bytes()
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("bundle-manifest.json"))
        names = archive.namelist()
        if (len(names) != len(set(names))
                or set(names) != set(manifest["files"]) | {"bundle-manifest.json"}):
            raise ValueError("bundle member list differs from manifest")
        for name, expected in manifest["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError(f"bundle integrity failure: {name}")
        if (manifest["model"] != COLAB_MODEL
                or not re.fullmatch(r"[0-9a-f]{40}", manifest["revision"])):
            raise ValueError("unsupported model or unpinned revision")
    bundle_hash = hashlib.sha256(raw).hexdigest()
    doc = notebook(bundle_hash, manifest["revision"])
    doc["metadata"]["colab"]["name"] = out.name
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(doc, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return {"notebook": str(out), "unchanged_bundle_sha256": bundle_hash,
            "status": "notebook repaired locally; training not run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--corpus", type=Path)
    inputs.add_argument("--reuse-bundle", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--revision")
    args = parser.parse_args()
    if args.reuse_bundle:
        if args.revision:
            parser.error("--reuse-bundle takes its pinned revision from the bundle")
        print(json.dumps(notebook_for_bundle(args.reuse_bundle, args.out), indent=2))
        return
    if not args.revision:
        parser.error("--corpus requires --revision")
    report = build(Path(__file__).resolve().parents[2], args.corpus, args.out, args.revision)
    print(json.dumps({k: report[k] for k in ("status", "splits", "bundle_bytes", "bundle_sha256")},
                     indent=2))


if __name__ == "__main__":
    main()
