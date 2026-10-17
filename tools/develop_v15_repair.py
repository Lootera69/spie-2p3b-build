"""Development-only comparison; never loads registered evaluation cases."""
from collections import defaultdict
import json
from pathlib import Path
from random import Random
import re
from statistics import mean, median
from time import perf_counter
from spie.questions.brainbloom import planning_experience_v4 as old, planning_experience_v5 as new
from spie.questions.brainbloom import state_planning_variety as variety

root = Path(__file__).resolve().parents[1] / 'artifacts/engine-capability-v15/2026-10-17/development'
root.mkdir(exist_ok=True)
out = root / 'comparison-01.json'
assert not out.exists()
rows = []
for seed in range(1501, 1511):
    for level in (1, 2, 3):
        for profile in variety.PROFILES:
            for revision, engine in ((14, old), (15, new)):
                start = perf_counter()
                m = engine.propose(['Depot','Orchard','Harbour','Meadow','Tower','Summit'][:level+3], level,
                                   Random(seed), requested_profile=profile)
                elapsed = perf_counter() - start
                cert = engine.certify(m)
                rows.append(dict(seed=seed, level=level, profile=profile, revision=revision,
                                 seconds=elapsed, model=m, dimensions=cert['dimensions'],
                                 judgment=cert['decision_judgment'],
                                 words=len(re.findall(r'[a-z0-9]+', new.quiz_stem(m).lower()))))
    print(f'Development seed {seed} complete', flush=True)
summary = {}
for revision in (14, 15):
    chosen = [r for r in rows if r['revision'] == revision]
    summary[revision] = dict(cases=len(chosen), median_seconds=median(r['seconds'] for r in chosen),
        roles=len({tuple(r['model']['experience_search']['selection']['selected_meaningful_roles']) for r in chosen}),
        signatures=len({r['judgment']['decision_signature'] for r in chosen}),
        structures=len({r['model']['experience_search']['selection']['selected_structural_key'] for r in chosen}),
        max_words=max(r['words'] for r in chosen),
        mean_rules=mean(r['dimensions']['rule_rows'] for r in chosen))
out.write_text(json.dumps(dict(summary=summary, results=rows), indent=2), encoding='utf-8')
print(json.dumps(summary), flush=True)
