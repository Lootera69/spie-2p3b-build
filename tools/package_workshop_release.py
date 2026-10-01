"""Snapshot source, build a wheel and exercise it in a clean temporary environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def run(args, cwd):
    result = subprocess.run(list(map(str, args)), cwd=cwd, text=True, capture_output=True,
                            timeout=240, check=False)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replay-bundles", type=Path, nargs="*", default=[],
                        help="Additional JSON arrays of saved bundles to replay offline")
    parser.add_argument("--wordnet", type=Path,
                        help="Installed pinned WordNet ZIP for an additional full-corpus check")
    parser.add_argument("--oewn", type=Path,
                        help="Installed pinned OEWN gzip for an additional full-corpus check")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    for path in (*args.replay_bundles, args.wordnet, args.oewn):
        if path is not None and not path.is_file():
            parser.error(f"Missing validation input: {path}")
    if bool(args.wordnet) != bool(args.oewn):
        parser.error("Supply both --wordnet and --oewn for the full-corpus check")
    out.mkdir(parents=True, exist_ok=False)
    files = [root / name for name in ("pyproject.toml", "README.md", "NOTICE",
                                      "start-brainbloom.ps1")]
    for folder in ("src/spie", "docs", "tests", "examples", "tools"):
        files.extend(p for p in (root / folder).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts
                     and p.suffix in {".py", ".md", ".html", ".css", ".js", ".cjs",
                                      ".json", ".ps1"})
    with tempfile.TemporaryDirectory(prefix="brainbloom-release-") as temporary:
        staging = Path(temporary) / "source"
        for source in sorted(files):
            target = staging / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        source_hashes = {
            source.relative_to(staging).as_posix(): hashlib.sha256(source.read_bytes()).hexdigest()
            for source in sorted(staging.rglob("*")) if source.is_file()
        }
        (out / "source-manifest.json").write_text(
            json.dumps(source_hashes, indent=2) + "\n", encoding="utf-8")
        archive_path = out / "spie-workshop-source.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in source_hashes:
                # Freeze the staged bytes and timestamps; avoid a second read of
                # a checkout that another task may still be editing.
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, (staging / name).read_bytes())
        print(f"Snapshotted {len(files)} source files.", flush=True)
        run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
             "--wheel-dir", out], staging)
        wheel = next(out.glob("*.whl"))
        wheelhouse = out / "dependencies"
        run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
             "--dest", wheelhouse, wheel], temporary)
        environment = Path(temporary) / "venv"
        run([sys.executable, "-m", "venv", environment], temporary)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        run([python, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse,
             wheel], temporary)
        replay_inputs = []
        for index, source in enumerate(args.replay_bundles):
            target = Path(temporary) / f"replay-{index}.json"
            shutil.copyfile(source, target)
            replay_inputs.append({"path": str(target), "name": source.as_posix(),
                                  "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        corpora = {}
        for name, source in (("wordnet", args.wordnet), ("oewn", args.oewn)):
            if source is not None:
                target = Path(temporary) / name / source.name
                target.parent.mkdir()
                shutil.copyfile(source, target)
                corpora[name] = str(target)
        code = '''
import json
from importlib.resources import files
from pathlib import Path
import spie
import hashlib
from unittest.mock import patch
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.coverage_sources import PACKS_SHA256, PACKS_V2_SHA256
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
root = Path(ROOT)
current = json.loads((root / 'examples/workshop-handoff-bundles.json').read_text(encoding='utf-8'))
legacy = json.loads((root / 'tests/fixtures/workshop_revision1.json').read_text(encoding='utf-8'))
replay_sets = [{'name': 'examples/workshop-handoff-bundles.json', 'bundles': current},
               {'name': 'tests/fixtures/workshop_revision1.json', 'bundles': legacy}]
for source in EXTRA_BUNDLES:
    replay_sets.append({**source,
                       'bundles': json.loads(Path(source['path']).read_text(encoding='utf-8'))})
replay_results = []
with patch.object(Dictionary, '__init__', side_effect=AssertionError('Replay loaded dictionary')), \
     patch('socket.socket', side_effect=AssertionError('Replay opened network')):
    for saved in replay_sets:
        count = sum(verify_bundle(bundle) for bundle in saved['bundles'])
        assert count == sum(len(bundle['items']) for bundle in saved['bundles'])
        replay_results.append({'name': saved['name'], 'bundles': len(saved['bundles']),
                               'items_replayed': count, 'sha256': saved.get('sha256')})
profiles = []
corpora = {name: Path(path) for name, path in CORPORA.items()}
with patch('socket.socket', side_effect=AssertionError('Generation opened network')):
    engines = [('packs-only', Generator(history=None))]
    if corpora:
        engines.append(('both-pinned-corpora', Generator(**corpora, history=None)))
    for name, engine in engines:
        generated = 0
        for activity in ('pattern', 'best-move', 'contradiction'):
            for level in ('easy', 'medium', 'hard'):
                bundle = engine.build(Request('activities', variation=activity, difficulty=level,
                                              subject='space, ocean', seed=31))
                generated += verify_bundle(bundle)
        coverage = []
        for subject in ('machine learning', 'cybersecurity', 'renewable energy', 'robotics',
                        'plate tectonics', 'genetics', 'cricket', 'neuroscience'):
            for category in ('logic', 'puzzles'):
                plan = prepare(Brief(subject=subject, category=category), engine.dictionary)
                assert plan['ready'], plan['message']
                assert plan['request']['meanings'][subject].startswith('coverage-v2:')
                assert plan['request']['difficulty'] == 'hard'
                bundle = engine.build(Request(**plan['request']))
                assert bundle['summary']['complete']
                generated += verify_bundle(bundle)
                coverage.append({'topic': subject, 'category': category,
                                 'sense': plan['request']['meanings'][subject],
                                 'difficulty': plan['request']['difficulty']})
        versions = []
        for version, expected_hash in (('v1', PACKS_SHA256), ('v2', PACKS_V2_SHA256)):
            bundle = engine.build(Request('dictionary', 'type-answer', seed=31,
                subject='machine learning', topic_mode='combined',
                meanings={'machine learning': f'coverage-{version}:machine-learning'}))
            generated += verify_bundle(bundle)
            source = bundle['dictionary']['sources'][0]
            authored_count = 10 if version == 'v2' else 0
            assert source['snapshot_sha256'] == expected_hash
            assert source['entry_origin_counts'] == {'oewn2024': 12, 'authored-v2': authored_count}
            versions.append({'version': version, 'snapshot_sha256': expected_hash,
                             'entry_origin_counts': source['entry_origin_counts']})
        profiles.append({'name': name, 'generated_and_replayed': generated,
                         'default_hard_coverage_topics': coverage, 'retained_versions': versions,
                         'configuration': engine.dictionary.configuration()})
data = files('spie.questions.brainbloom').joinpath('data')
snapshots = {name: hashlib.sha256(data.joinpath(name).read_bytes()).hexdigest()
             for name in ('coverage-packs-v1.json', 'coverage-packs-v2.json')}
assert snapshots == {'coverage-packs-v1.json': PACKS_SHA256,
                     'coverage-packs-v2.json': PACKS_V2_SHA256}
assert files('spie.questions.brainbloom').joinpath('static/index.html').is_file()
assert 'site-packages' in spie.__file__
print(json.dumps({'imported_from': spie.__file__,
                  'saved_drafts_replayed': sum(row['items_replayed'] for row in replay_results),
                  'replay_sets': replay_results,
                  'replay_without_dictionary_or_network': True,
                  'generation_without_network': True,
                  'new_drafts_generated_and_replayed': sum(
                      row['generated_and_replayed'] for row in profiles),
                  'static_assets': True, 'generation_profiles': profiles,
                  'snapshot_sha256': snapshots,
                  'corpus_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for name, path in corpora.items()}}))
'''.replace("ROOT", repr(str(staging))).replace(
            "EXTRA_BUNDLES", repr(replay_inputs)).replace("CORPORA", repr(corpora))
        validation = json.loads(run([python, "-I", "-B", "-c", code], temporary))
        validation["dependencies"] = run([python, "-m", "pip", "freeze"], temporary).splitlines()
        (out / "clean-install-check.json").write_text(json.dumps(validation, indent=2),
                                                       encoding="utf-8")
        print(json.dumps({key: value for key, value in validation.items()
                          if key != "generation_profiles"}, indent=2), flush=True)
    hashes = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(out.rglob("*")) if p.is_file()}
    (out / "SHA256SUMS.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
