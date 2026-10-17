"""Reuse hash-verified historical outcomes, evaluate additions, replay a shard."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'artifacts/engine-capability-v15/2026-10-17'
OLD = ROOT / 'artifacts/engine-capability-v14/2026-10-15'
shard = int(sys.argv[1])
sys.path.insert(0, str(HERE / 'baseline/src'))
sys.path.insert(0, str(HERE))
from audit_support import fingerprint, write
from spie.questions.brainbloom.service import verify_bundle

old_manifest = json.loads((OLD / 'candidate/source-sha256.json').read_text())
assert all(hashlib.sha256((HERE / 'baseline/src' / name).read_bytes()).hexdigest() == value
           for name, value in old_manifest.items())
expected = {r['sha256']: r for n in (0, 1)
            for r in json.loads((OLD / f'final-legacy-{n}.json').read_text())['results']}
index = json.loads((HERE / 'baseline/legacy-corpus-complete-index.json').read_text())
rows = []
for i, entry in enumerate(index['results']):
    if i % 2 != shard:
        continue
    key = entry['sha256']
    if key in expected:
        row = {**expected[key], 'origin': 'hash-verified revision14 final replay'}
    else:
        bundle = json.loads((HERE / entry['frozen_file']).read_text(encoding='utf-8'))
        assert fingerprint(bundle) == key
        row = {'sha256': key, 'revision': entry['revision'], 'origin': 'revision14 baseline additions'}
        try:
            row.update(status='passed', items=verify_bundle(bundle))
        except Exception as exc:
            row.update(status='rejected', error=f'{type(exc).__name__}: {exc}')
    rows.append(row)
write(HERE / f'baseline/legacy-replay-{shard}.json', {'results': rows, 'source_hashes_verified': True})
subprocess.run([sys.executable, '-B', str(HERE / 'replay_legacy.py'), '--shard', str(shard),
                '--shards', '2', '--out', str(HERE / f'final-legacy-{shard}.json')], check=True)
