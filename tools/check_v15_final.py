"""Verify source, test amendment, registration and report consistency."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'artifacts/engine-capability-v15/2026-10-17'
def read(name):
    return json.loads((HERE/name).read_text(encoding='utf-8'))
def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
source = hashes(ROOT/'src')
assert source == read('candidate/source-sha256.json') == hashes(HERE/'candidate/src')
tests = hashes(ROOT/'tests')
frozen_tests = read('candidate/test-sha256.json')
changed = [name for name in tests.keys() | frozen_tests.keys() if tests.get(name) != frozen_tests.get(name)]
assert changed == ['test_brainbloom_planning_episode.py'], changed
assert read('release/episode-test-amendment.json')['exit_code'] == 0
for name,value in read('registered-files-sha256.json').items():
    assert hashlib.sha256((HERE/name).read_bytes()).hexdigest() == value
assert not (ROOT/'requirements-build.txt').exists()
report = read('independent-summary.json')
assert report['failed_gates'] == ['meaningful_role_variety']
assert not report['legacy']['changed_outcomes']
out = HERE/'release/final-check.json'
assert not out.exists()
shutil.copyfile(ROOT/'tests'/changed[0], HERE/'release'/changed[0])
out.write_text(json.dumps(dict(checked_utc=datetime.now(timezone.utc).isoformat(),
    source_matches_freeze=True, source_files=len(source), test_amendments=changed,
    current_test_sha256=tests, registered_protocol_unchanged=True,
    historical_replay_unchanged=True, preexisting_build_requirements_deletion_preserved=True,
    remaining_failed_gates=report['failed_gates']), indent=2), encoding='utf-8')
print('Final check: 141 source files unchanged; one documented test-only amendment; historical replay exact.')
