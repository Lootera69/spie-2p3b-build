"""Run existing browser/API regression scripts against the frozen preview."""
import json
from pathlib import Path
import subprocess
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'artifacts/engine-capability-v15/2026-10-17/release'
JSDOM = ROOT / 'artifacts/state-planning-variety/2026-10-13/dom-runtime/node_modules/jsdom'
rows = []
for name in ('flow', 'player', 'sharing', 'library', 'episode', 'episode_navigation'):
    start = perf_counter()
    result = subprocess.run(['node', str(ROOT / f'tests/brainbloom_{name}.cjs'),
                             str(JSDOM), 'http://127.0.0.1:8768'], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8')
    row = dict(script=name, exit_code=result.returncode, seconds=perf_counter()-start,
               stdout=result.stdout, stderr=result.stderr)
    rows.append(row)
    print(json.dumps(row), flush=True)
out = HERE / 'browser-checks.json'
assert not out.exists()
out.write_text(json.dumps(dict(passed=sum(r['exit_code']==0 for r in rows), results=rows), indent=2), encoding='utf-8')
raise SystemExit(any(r['exit_code'] for r in rows))
