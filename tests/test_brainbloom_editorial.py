"""Current reasoning stays publishable while old rendered bundles still replay."""

import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.catalog import CATEGORIES, Request
from spie.questions.brainbloom.service import Generator, verify_bundle

FORMATS = ("multiple-choice", "true-false", "type-answer", "riddle")
VERIFIER = Path(__file__).resolve().parents[3] / "BrainBloom/lib/forge/verify.ts"


@pytest.mark.parametrize("style", ("deduction", "bayesian", "planning", "contradiction"))
@pytest.mark.parametrize("qtype", FORMATS)
def test_concise_rendering_retains_logical_model_answers_and_revision_three_replay(style, qtype):
    request = Request("activities" if style == "contradiction" else "reasoning", qtype,
                      "hard", subject="machine learning, renewable energy, robotics",
                      topic_mode="combined", variation=style, seed=7)
    engine = Generator()
    old = engine.build(replace(request, engine_revision=3))
    current = engine.build(request)
    old_item, item = old["items"][0], current["items"][0]
    assert current["request"]["engine_revision"] == 4
    assert 2 <= len(re.findall(r"[a-z0-9]+", item["title"].lower())) <= 4
    assert len(re.findall(r"[a-z0-9]+", item["question"].lower())) <= 120
    assert old_item["question"] != item["question"]
    assert {k: v for k, v in old_item.items() if k not in ("title", "question")} == {
        k: v for k, v in item.items() if k not in ("title", "question")
    }
    assert {k: v for k, v in old["proofs"][0].items() if k != "item_sha256"} == {
        k: v for k, v in current["proofs"][0].items() if k != "item_sha256"
    }
    assert verify_bundle(old) == verify_bundle(current) == 1
    current["request"]["engine_revision"] = 3
    with pytest.raises(ValueError, match="does not match"):
        verify_bundle(current)


@pytest.mark.skipif(not VERIFIER.is_file() or not shutil.which("node"),
                    reason="Optional sibling Studio verifier and Node are not installed")
@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("qtype", FORMATS)
def test_default_hard_drafts_pass_actual_studio_editorial_checks(category, qtype):
    engine = Generator(verifier=VERIFIER)
    plan = prepare(Brief(category=category, qtype=qtype,
                         subject="machine learning, robotics"), engine.dictionary)
    assert plan["ready"]
    bundle = engine.build(Request(**plan["request"]))
    assert bundle["summary"]["complete"], bundle["rejected"]
    assert verify_bundle(bundle) == 1


@pytest.mark.skipif(not VERIFIER.is_file() or not shutil.which("node"),
                    reason="Optional sibling Studio verifier and Node are not installed")
@pytest.mark.parametrize("style", ("bayesian", "contradiction", "pattern", "best-move"))
@pytest.mark.parametrize("qtype", FORMATS)
def test_explicit_hard_activities_pass_actual_studio_editorial_checks(style, qtype):
    engine = Generator(verifier=VERIFIER)
    request = Request("reasoning" if style == "bayesian" else "activities", qtype,
                      "hard", subject="space, ocean", topic_mode="combined",
                      variation=style, seed=7)
    bundle = engine.build(request)
    assert bundle["summary"]["complete"], bundle["rejected"]
    assert verify_bundle(bundle) == 1
