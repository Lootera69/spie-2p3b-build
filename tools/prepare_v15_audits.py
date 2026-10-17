"""Adapt existing raw audits for version-15 transport and selection."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'artifacts/engine-capability-v15/2026-10-17'
assert not (HERE / 'candidate').exists()
def edit(name, pairs):
    p = HERE / name
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        assert old in s, (name, old)
        s = s.replace(old, new)
    p.write_text(s, encoding='utf-8')

edit('run_audit.py', [('default="planning_experience_v4"', 'default="planning_experience_v5"'),
    ('"planning_experience_v3" if args.phase', '"planning_experience_v4" if args.phase'),
    ('"revision":13', '"revision":14')])
edit('freeze_candidate.py', [('planning_experience_v4 as engine', 'planning_experience_v5 as engine')])
edit('compare_timing.py', [('default="planning_experience_v4"', 'default="planning_experience_v5"'),
    ('"planning_experience_v3"', '"planning_experience_v4"'), ('"seed":1401', '"seed":1501')])
edit('audit_formats.py', [('engine_revision=14', 'engine_revision=15'),
    ('("bundle","items","traceback")', '("bundle","generated_bundle","items","traceback")')])
edit('audit_episode_v14.py', [('("planning-experience-v3", "planning-experience-v4")',
    '("planning-experience-v3", "planning-experience-v4", "planning-experience-v5")')])
edit('audit_selection.py', [
    ('comparisons=search["comparisons"]', 'from spie.questions.brainbloom.planning_experience_v5 import expand_comparisons\n    comparisons=expand_comparisons(model)'),
    ('    bestdepth=max(map(depth,bounded))\n    deep=[r for r in bounded if depth(r)==bestdepth]\n', ''),
    ('for r in deep', 'for r in bounded'), ('for o in deep', 'for o in bounded'),
    ('    role_signatures=sorted(', '    bestdepth=max(map(depth,candidates))\n    candidates=[r for r in candidates if depth(r)==bestdepth]\n    role_signatures=sorted('),
    ('=="planning-experience-v4"', '=="planning-experience-v5"'),
    ('1401<=r["seed"]<=1440', '1501<=r["seed"]<=1540'),
    ('data=json.loads(Path(args.development_model).read_text())', 'data=json.loads(Path(args.development_model).read_text())["results"]')])
edit('freeze_corpus.py', [
    ('engine-capability-v13/2026-10-15', 'engine-capability-v14/2026-10-15'),
    ('1 <= revision <= 13', '1 <= revision <= 14'),
    ('baseline/legacy-corpus-index.json', 'baseline/legacy-corpus-complete-index.json'),
    ('"planning-experience-v2","planning-experience-v3")', '"planning-experience-v2","planning-experience-v3","planning-experience-v4")'),
    ('revision1-13', 'revision1-14'), ('v13', 'v14')])
print('Prepared independent raw audit adapters; no evaluation cases run.')
