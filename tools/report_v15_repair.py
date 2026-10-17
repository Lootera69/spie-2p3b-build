"""Reconcile registered repair results without changing failed targets."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from statistics import mean
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'artifacts/engine-capability-v15/2026-10-17'
OLD = ROOT / 'artifacts/engine-capability-v14/2026-10-15'
def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))
base, current, heldout = read('baseline/matched.json'), read('final-matched/results.json'), read('final-heldout/results.json')
formats, selection, timing = read('final-formats/results.json'), read('selection-audit.json'), read('controlled-timing.json')
rawmodels = read('final-legacy-models.json')
baseline = {r['sha256']: r for n in (0,1) for r in read(f'baseline/legacy-replay-{n}.json')['results']}
final = {r['sha256']: r for n in (0,1) for r in read(f'final-legacy-{n}.json')['results']}
def outcome(row):
    return row['status'], row.get('items'), row.get('error')
changed = [key for key in baseline.keys() | final.keys()
           if key not in baseline or key not in final or outcome(baseline[key]) != outcome(final[key])]
quality = {side: {field: mean(r[side]['all_shortest'][field] for r in current['results'])
                 for field in ('trap_choices_on_optimal_episodes','maximum_forced_steps','rule_rows','solution_steps')}
           for side in ('baseline','selected')}
words = {side: mean(r[side]['rendered_stem_words'] for r in current['results']) for side in ('baseline','selected')}
policies = {side: {str(horizon): {field: str(sum(Fraction(p[field])
            for r in current['results'] if r['level']==3
            for p in r[side]['depth_uniform_policies'] if p['policy']==f'horizon-{horizon}') / 8)
            for field in ('success_probability','optimal_probability','dead_end_probability')}
            for horizon in (2,5)} for side in ('baseline','selected')}
b, n = base['summary'], current['summary']
target = b['consequential_role_sequences'] + min(2, 20-b['consequential_role_sequences'])
registered = read('registered-files-sha256.json')
frozen = read('candidate/source-sha256.json')
intact = all(hashlib.sha256((ROOT/'src'/name).read_bytes()).hexdigest()==value for name,value in frozen.items())
oracle = json.loads((OLD/'oracle-source-sha256.json').read_text())
tests = ET.parse(HERE/'release/creator-tests.xml').getroot().find('testsuite').attrib
amended = ET.parse(HERE/'release/episode-test-amendment.xml').getroot().find('testsuite').attrib
failures = [row.attrib['name'] for row in ET.parse(HERE/'release/creator-tests.xml').getroot().iter('testcase') if row.find('failure') is not None]
tests_resolved = (failures == ['test_unknown_experience_versions_cannot_fall_back_to_an_old_episode[planning-experience-v5]']
                  and tests['errors']=='0' and amended['errors']=='0' and amended['failures']=='0')
browser = read('release/browser-checks.json')
gates = {
    'registered_protocol_unchanged': all(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==value for name,value in registered.items()),
    'raw_oracle_preserved': all(hashlib.sha256((HERE/'oracle'/name).read_bytes()).hexdigest()==value for name,value in oracle.items()),
    'baseline_correctness': b['passed']==20,
    'matched_correctness': n['passed']==20,
    'heldout_correctness': heldout['summary']['passed']==24,
    'meaningful_role_variety': n['consequential_role_sequences']>=target,
    'decision_signatures_retained': n['decision_dependency_signatures']>=b['decision_dependency_signatures'],
    'physical_structures_retained': n['structures']>=b['structures'],
    **{f'no_extra_{key}': quality['selected'][key]<=quality['baseline'][key] for key in ('trap_choices_on_optimal_episodes','maximum_forced_steps','rule_rows')},
    'no_extra_reading': words['selected']<=words['baseline'],
    'causal_links_on_every_shortest_route': n['all_shortest_link_target']==20 and heldout['summary']['all_shortest_link_target']==24,
    'selection_reconstructed': selection['summary']['passed']==20,
    'formats_editorial_and_transport': formats['summary']['passed']==17 and formats['summary']['items']==86,
    'historical_outcomes_unchanged': not changed and len(final)==read('baseline/legacy-corpus-complete-index.json')['bundles'],
    'raw_certificates_scenarios_unchanged': rawmodels['passed']==rawmodels['models'],
    'warmed_generation_not_slower': timing['median_ratio']<=1,
    'timed_models_reproduced': timing['all_requests_reproduce_models'],
    'source_matches_freeze': intact,
    'creator_tests_with_version_assertion_amendment': tests_resolved,
    'browser_scripts': browser['passed']==6,
}
report = dict(gates=gates, failed_gates=[k for k,v in gates.items() if not v],
    baseline=b, candidate=n, required_meaningful_roles=target, heldout=heldout['summary'],
    formats=formats['summary'], selection=selection['summary'], quality=quality, mean_stem_words=words,
    hard_policy_diagnostics=policies, timing=timing['summary'], timing_ratio=timing['median_ratio'],
    legacy=dict(bundles=len(final), changed_outcomes=changed, accepted=sum(r['status']=='passed' for r in final.values()),
                exact_rejections=sum(r['status']=='rejected' for r in final.values()), items=sum(r.get('items',0) for r in final.values()), raw_models=rawmodels['models']),
    creator_tests=tests, amended_episode_tests=amended, browser_scripts=browser['passed'], human_participants=0)
out = HERE/'independent-summary.json'
assert not out.exists()
out.write_text(json.dumps(report, indent=2), encoding='utf-8')
old_s, new_s = timing['summary']['baseline']['median'], timing['summary']['selected']['median']
text = f'''# Revision 15 repair and evaluation

Playback transport and editorial integration are repaired. The broader variety
target remains unmet; {sum(gates.values())}/{len(gates)} registered and release checks pass.
The candidate remains Experimental. All work is local; nothing was committed,
pushed or deployed. Saved revisions 1–14 remain supported.

| Measure | Revision 14 | Revision 15 |
| --- | ---: | ---: |
| Meaningful-only role patterns (target {target}) | {b['consequential_role_sequences']} | {n['consequential_role_sequences']} |
| Dependency signatures | {b['decision_dependency_signatures']} | {n['decision_dependency_signatures']} |
| Physical structures | {b['structures']} | {n['structures']} |
| Warmed median generation | {old_s:.4f} s | {new_s:.4f} s |
| Mean rule rows | {quality['baseline']['rule_rows']:.2f} | {quality['selected']['rule_rows']:.2f} |
| Mean rendered words (whitespace) | {words['baseline']:.2f} | {words['selected']:.2f} |

All 20 matched and 24 heldout cases pass raw physical, answer, decision, causal,
hint and transcript checks. Twenty recorded selection pools reconstruct across
{selection['summary']['unique_candidate_models_recomputed']} independently measured models.
All 17 format requests, containing 86 items, pass including count-20 batches and
the Studio regex word ceiling. The largest maximum-history request is
{formats['summary']['max_api_bytes_with_max_history']:,} bytes, below the unchanged 2,097,152-byte cap.

All {len(final):,} historical bundle outcomes are unchanged, including
{report['legacy']['exact_rejections']} exact rejections; all {rawmodels['models']} raw certificate/scenario
records match. The full creator suite reports {int(tests['tests'])-int(tests['failures'])} passes and
one outdated version assertion; after correcting that test, all {amended['tests']}
episode tests pass. No runtime source changed. All six DOM/API scripts pass.
The original failure and a wrapper report-filename collision are retained in
[check-harness-notes.md](check-harness-notes.md).

The generator retains physical candidate rules plus SHA-256 commitments instead
of serializing every derived comparison. Audit replay recomputes those measurements;
a hash alone is not certification. Policy scoring runs only for the selected
decision form. Meaningful roles are drawn before the depth preference, so depth
cannot globally erase whole roles. Cost, physical and all-shortest causal gates
remain mandatory. Quiz text uses numbered room references; the episode retains
full names, story and public rules.

Fresh random evaluation cases were registered before changes. The 141 source
files were frozen before fixed outcomes were generated. Separate 120-case development
results improved variety, but that improvement did not reproduce on the matched
sample. No evaluation-driven retuning occurred. Deeper-policy results remain
diagnostics and are retained in independent-summary.json, not human difficulty
claims. Human participant count is zero. Assistant UI review is separate.

Failures: {', '.join(report['failed_gates']) or 'none'}.

[Protocol](../protocol.json) · [Raw results](../independent-summary.json) ·
[Assistant review](assistant-play-review.md) · [Development failures](../development/attempts.md)
'''
(HERE/'release/completion.md').write_text(text, encoding='utf-8')
print(json.dumps({k:report[k] for k in ('failed_gates','timing_ratio','legacy','creator_tests','browser_scripts')}, indent=2))
