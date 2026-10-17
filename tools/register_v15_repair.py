"""Register fresh evaluation cases and preserve the pre-repair source."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import shutil

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'artifacts/engine-capability-v14/2026-10-15'
HERE = ROOT / 'artifacts/engine-capability-v15/2026-10-17'
assert not HERE.exists(), 'Registration is immutable'
HERE.mkdir(parents=True)
for folder in ('src', 'tests'):
    shutil.copytree(ROOT / folder, HERE / 'baseline' / folder,
                    ignore=shutil.ignore_patterns('__pycache__'))
manifest = {p.relative_to(HERE / 'baseline').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((HERE / 'baseline').rglob('*')) if p.is_file()}
(HERE / 'baseline/manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
shutil.copytree(OLD / 'oracle', HERE / 'oracle', ignore=shutil.ignore_patterns('__pycache__'))
for p in OLD.glob('*.py'):
    shutil.copyfile(p, HERE / p.name)
protocol = json.loads((OLD / 'protocol.json').read_text(encoding='utf-8'))
seeds = secrets.SystemRandom().sample(range(200_000_000, 900_000_000), 61)
for row, seed in zip(protocol['cases'] + protocol['heldout_cases'], seeds):
    row['seed'] = seed
protocol.update(version='planning-experience-v15-audit-v1',
                registered_utc=datetime.now(timezone.utc).isoformat(), baseline_revision=14,
                candidate_revision=15, development_seeds=list(range(1501, 1541)))
protocol['formats'] = {'engine_revision': 15, 'seeds': seeds[44:]}
protocol['targets']['legacy_replay'] = 'Zero changed replay outcomes for revisions 1–14, including exact historical rejections.'
protocol['targets']['hard_policy_depth'] = 'Diagnostic: preserve deeper-policy success where feasible without globally eliminating diverse meaningful roles. No human difficulty claim.'
protocol['targets']['transport'] = 'All four formats and count-20 batches play within the unchanged 2 MiB saved-request cap, including maximum history.'
protocol['targets']['editorial'] = 'New state-planning quiz stems satisfy the Studio 120-word regex ceiling; all physical rules remain stated.'
protocol['evidence_policy'] = 'Random evaluation identifiers registered before edits; outcomes withheld until source freeze. Single implementer, no claim of independent human blinding. Do not tune against fixed outcomes. Preserve failures.'
protocol['controlled_runtime']['warmup'] = 'One development seed1501 request per profile and level per worker.'
(HERE / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n', encoding='utf-8')
(HERE / 'registered-files-sha256.json').write_text(json.dumps({
    name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
    for name in ('protocol.json', 'baseline/manifest.json')}, indent=2), encoding='utf-8')
print(f'Registered fresh cases and preserved {len(manifest)} source/test files.')
