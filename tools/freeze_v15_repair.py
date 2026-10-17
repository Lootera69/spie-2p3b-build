"""Explicit candidate freeze after development checks, before fixed evaluation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'artifacts/engine-capability-v15/2026-10-17'
destination = HERE / 'candidate'
assert not destination.exists()
assert json.loads((HERE / 'selection-adapter-development.json').read_text())['summary']['passed'] == 3
for folder in ('src', 'tests'):
    shutil.copytree(ROOT / folder, destination / folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
source = hashes(destination / 'src')
assert source == hashes(ROOT / 'src')
for name, value in [('source-sha256.json', source), ('test-sha256.json', hashes(destination / 'tests')),
                    ('audit-helper-sha256.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(HERE.glob('*.py'))})]:
    (destination / name).write_text(json.dumps(value, indent=2), encoding='utf-8')
(destination / 'freeze.json').write_text(json.dumps(dict(
    frozen_utc=datetime.now(timezone.utc).isoformat(), revision=15, explicit_root_freeze=True,
    source_sha256=source, development='120 paired cases, seeds1501–1510; 3 independent selection reconstructions; 26 generator/editorial checks.',
    evaluation='No fixed evaluation outcomes generated or used before this freeze.'), indent=2), encoding='utf-8')
(HERE / 'release').mkdir(exist_ok=True)
print(f'Explicit source freeze: {len(source)} files.')
