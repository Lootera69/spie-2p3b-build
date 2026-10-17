"""Compact evidence, deferred policy selection and revision-15 rules."""
from copy import deepcopy
from random import Random
import re

import pytest
from tools.benchmark_state_planning import oracle
from spie.questions.brainbloom import planning_experience_v5 as experience
from spie.questions.brainbloom import state_planning_variety as variety


@pytest.mark.parametrize('level', (1, 2, 3))
@pytest.mark.parametrize('profile', variety.PROFILES)
def test_reconstruction_raw_answer_and_concise_complete_rules(level, profile):
    model = experience.propose(list('ABCDEF')[:level + 3], level, Random(1501), requested_profile=profile)
    assert model['solution'] == oracle(model)['solution']
    assert experience.audit_selection(model) == model['experience_search']['selection']
    assert all(set(row) == {'attempt', 'origin', 'parent_attempt', 'physical_rules', 'evidence_sha256'}
               for row in model['experience_search']['comparisons'])
    stem = experience.quiz_stem(model)
    assert len(re.findall(r'[a-z0-9]+', stem.lower())) <= 120
    for a, b, cost, gate in model['routes']:
        assert f'{a+1}→{b+1}:{cost}' + (f'/{"AB"[gate]}' if gate >= 0 else '') in stem


def test_cache_isolation_and_tampered_evidence_rejected():
    def generate():
        return experience.propose(list('ABCDE'), 2, Random(1502))
    experience._foundation_analysis.cache_clear()
    model = generate()
    expected = deepcopy(model)
    model['routes'][0][2] = 99
    model['experience_search']['comparisons'].clear()
    assert generate() == expected
    experience._foundation_analysis.cache_clear()
    assert generate() == expected
    bad = deepcopy(expected)
    bad['experience_search']['comparisons'][0]['evidence_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='candidate evidence disagrees'):
        experience.audit_selection(bad)
    bad = deepcopy(expected)
    bad['experience_search']['selection']['selected_policy_rank'] = ['9/8']
    with pytest.raises(ValueError, match='selection disagrees'):
        experience.audit_selection(bad)


def test_policy_evaluation_is_deferred_until_selected_form(monkeypatch):
    calls = []
    original = experience.judgment.policy_metrics
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(experience.judgment, 'policy_metrics', counted)
    model = experience.propose(list('ABCDEF'), 3, Random(1503))
    assert 0 < len(calls) < len(model['experience_search']['comparisons'])
    with pytest.raises(experience.ExperienceExhausted):
        experience.propose(list('ABCD'), 1, Random(1504), budget=0)
