"""State-changing plans enter the existing versioned BrainBloom question contract."""

import copy
import json

import pytest

from spie.forge.corpus import digest
from spie.questions.brainbloom import Request
from spie.questions.brainbloom.brief import Brief, configuration, prepare
from spie.questions.brainbloom.catalog import configuration as catalog_configuration
from spie.questions.brainbloom.contract import issues
from spie.questions.brainbloom.feedback import feedback_for
from spie.questions.brainbloom.lexicon import Dictionary
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.workshop import candidate

FORMATS = ("multiple-choice", "true-false", "type-answer", "riddle")
LEVELS = {"easy": 4, "medium": 5, "hard": 6}


def test_state_planning_is_an_explicit_activity_for_all_four_answer_formats():
    activity = configuration()["activities"]["state-planning"]
    assert activity["label"] == "Plan with energy and switches"
    assert activity["uses_topics"] is True
    assert activity["types"] == FORMATS
    assert catalog_configuration()["variations"]["activities"]["state-planning"] == activity[
        "label"]
    assert Request().engine_revision == 17


@pytest.mark.parametrize("revision", range(1, 18))
def test_all_saved_engine_revisions_remain_supported(revision):
    assert Request(engine_revision=revision).engine_revision == revision


@pytest.mark.parametrize("revision", [0, 18, True, 17.0, "17"])
def test_engine_revision_must_be_a_supported_integer(revision):
    with pytest.raises(ValueError, match="Unsupported engine revision"):
        Request(engine_revision=revision)


@pytest.mark.parametrize("revision", range(1, 7))
def test_state_planning_cannot_be_requested_under_an_older_revision(revision):
    with pytest.raises(ValueError, match="requires engine revision 7"):
        Request("activities", variation="state-planning", engine_revision=revision)


@pytest.mark.parametrize("kind", ["crossword", "wonder"])
def test_state_planning_rejects_formats_without_an_action_answer(kind):
    report = prepare(Brief(activity="state-planning", qtype=kind, subject="animals"), Dictionary())
    assert not report["ready"] and report["request"] is None
    with pytest.raises(ValueError):
        Request("activities", kind, variation="state-planning")


def test_written_activity_label_routes_to_the_same_state_planning_request():
    report = prepare(Brief(activity="custom", subject="animals, space", instructions=(
        "Plan with energy and switches. About animals, space. Hard. Multiple choice."
    )), Dictionary())
    assert report["ready"], report["message"]
    request = Request(**report["request"])
    assert request.topic == "activities" and request.variation == "state-planning"
    assert request.engine_revision == 17
    assert request.qtype == "multiple-choice" and request.difficulty == "hard"


def test_topic_capacity_matches_four_five_and_six_location_plans():
    subject = "animals, space, ocean, plants, science, logic"
    dictionary = Dictionary()
    for difficulty in ("easy", "medium"):
        report = prepare(Brief(activity="state-planning", subject=subject,
                               difficulty=difficulty), dictionary)
        assert not report["ready"] and report["request"] is None
        assert f"{LEVELS[difficulty]} words" in report["message"]
        assert [option["available"] for option in report["difficulty_options"]] == [
            False, False, True]
    report = prepare(Brief(activity="state-planning", subject=subject,
                           difficulty="hard"), dictionary)
    assert report["ready"], report["message"]


@pytest.mark.parametrize("category,expected", [
    ("logic", "deduction"), ("riddles", "deduction"), ("science", "deduction"),
    ("puzzles", "deduction"), ("wonders", "deduction"),
])
def test_experimental_state_planning_stays_out_of_automatic_core_selection(category, expected):
    report = prepare(Brief(category=category, subject="space, ocean"), Dictionary())
    assert report["ready"], report["message"]
    assert report["selected_activity"] == expected


@pytest.mark.parametrize("variation", [
    "auto", "pattern", "contradiction", "most-likely", "best-move", "resource-plan",
])
@pytest.mark.parametrize("revision", [7, 8])
def test_existing_activity_candidates_do_not_change_after_revision_six(variation, revision):
    options = {"variation": variation, "subject": "space, ocean"}
    assert candidate(Request("activities", engine_revision=6, **options), 7) == candidate(
        Request("activities", engine_revision=revision, **options), 7)


@pytest.mark.parametrize("revision", range(1, 8))
def test_preexisting_activity_bundles_still_replay_at_their_saved_revision(revision):
    bundle = Generator().build(Request("activities", variation="pattern", subject="animals",
                                       engine_revision=revision, seed=7))
    assert bundle["request"]["engine_revision"] == revision
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1


@pytest.mark.parametrize("difficulty", LEVELS)
@pytest.mark.parametrize("kind", FORMATS)
def test_generated_state_plans_preserve_topics_answer_formats_and_exact_saved_replay(
    difficulty, kind,
):
    from spie.questions.brainbloom import state_planning

    engine = Generator()
    report = prepare(Brief(activity="state-planning", subject="space, ocean",
                           difficulty=difficulty, qtype=kind, seed=7), engine.dictionary)
    assert report["ready"], report["message"]
    request = Request(**report["request"])
    bundle = engine.build(request)
    assert bundle["version"] == 8 and bundle["generator"] == "brainbloom-activities-v8"
    assert bundle["request"]["engine_revision"] == 17 and bundle["summary"]["complete"]
    assert bundle["proofs"][0]["model"]["experience_version"] == "planning-experience-v5"
    assert bundle["proofs"][0]["experience"]["version"] == "planning-experience-core-bfs-v5"
    assert bundle["proofs"][0]["episode"]["version"] == "planning-episode-v4"
    item, proof = bundle["items"][0], bundle["proofs"][0]
    assert issues(item) == []
    assert len(proof["word_bank"]) == LEVELS[difficulty]
    assert all(word in item["question"] for word in proof["word_bank"])
    assert {topic["term"] for topic in proof["topic_coverage"]} == {"space", "ocean"}
    assert all(topic["used_words"] for topic in proof["topic_coverage"])
    assert "energy" in item["lessonContent"] and "switch" in item["lessonContent"]
    draft = state_planning.render(proof["model"])
    if kind == "true-false":
        assert proof["claim_holds"] is (proof["claim"] == draft["answer"])
        assert item["correctAnswer"] == str(proof["claim_holds"])
        assert item["choices"] == ["True", "False"]
    else:
        assert item["correctAnswer"] == draft["answer"]
        if kind == "multiple-choice":
            assert set(item["choices"]) == {draft["answer"], *draft["distractors"]}
        else:
            assert item["correctAnswer"] in item["acceptedAnswers"]
            if kind == "riddle":
                assert item["hintText"] == "\n".join(draft["hints"])
    answers = item["choices"] if item["choices"] else item["acceptedAnswers"]
    for answer in answers:
        feedback = feedback_for(item, proof, answer)
        assert feedback["supported"] is True
        assert feedback["correct"] is (
            answer == item["correctAnswer"] or answer in item.get("acceptedAnswers", []))
        assert "1. " not in feedback["message"]  # Coach without dumping the plan.
    assert feedback_for(item, proof, "invented action")["supported"] is False
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1


@pytest.mark.parametrize("kind", FORMATS)
def test_explicit_revision12_keeps_its_generator_certificate_and_saved_replay(kind):
    request = Request("activities", kind, "easy", variation="state-planning",
                      subject="space, ocean", seed=1701, engine_revision=12)
    bundle = Generator().build(request)
    assert bundle["request"]["engine_revision"] == 12 and bundle["summary"]["complete"]
    proof = bundle["proofs"][0]
    assert proof["model"]["experience_version"] == "planning-experience-v2"
    assert proof["experience"]["version"] == "planning-experience-core-bfs-v2"
    assert proof["episode"]["version"] == "planning-episode-v2"
    assert issues(bundle["items"][0]) == []
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1


# Captured using the frozen revision-14 baseline source before integration.
@pytest.mark.parametrize("kind,fingerprint", [
    ("multiple-choice", "05a8c8ac9bd00d9bb33c48258ab07f87fdc976b3e7c1a1d82c38be8a639c2d12"),
    ("true-false", "10b021e4e0f3ef846eb8a3692b5fddaee8016f7929d5dff9f279e59519a8fa60"),
    ("type-answer", "e46b057f0c9c1aa88bd3d31a87755512791c1b765f290dd83cca92ab75e9c508"),
    ("riddle", "6c86b0daaffca094298755a1989899f12b5ecf22916a788e1efebd7d461315ae"),
])
def test_explicit_revision13_preserves_frozen_bundles_and_exact_saved_replay(kind, fingerprint):
    request = Request("activities", kind, "easy", variation="state-planning",
                      subject="space, ocean", seed=1701, engine_revision=13)
    bundle = Generator().build(request)
    assert digest(bundle) == fingerprint
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1


@pytest.fixture(scope="module")
def saved_state_plans():
    return Generator().build(Request("activities", variation="state-planning",
                                     difficulty="hard", subject="animals, space",
                                     count=2, seed=19, engine_revision=7))


def test_state_planning_batches_are_deterministic_and_structurally_distinct(saved_state_plans):
    assert saved_state_plans == Generator().build(Request(**saved_state_plans["request"]))
    assert len({proof["structural_key"] for proof in saved_state_plans["proofs"]}) == 2
    # This seed exhausts an inner proposal search; the next candidate is still
    # eligible, and saved seeds retain enough information for exact replay.
    assert saved_state_plans["provenance"]["search_candidates_exhausted"] >= 1
    assert verify_bundle(json.loads(json.dumps(saved_state_plans))) == 2


def test_exhausted_candidate_searches_stop_at_the_batch_budget(monkeypatch):
    from spie.questions.brainbloom import state_planning

    attempts = []

    def exhausted(*args):
        attempts.append(1)
        raise state_planning.ProposalExhausted("No candidate met the gates")

    monkeypatch.setattr(state_planning, "propose", exhausted)
    with pytest.raises(ValueError, match="30 candidate searches.*No partial batch exported"):
        Generator().build(Request("activities", variation="state-planning", seed=7,
                                 engine_revision=7))
    assert len(attempts) == 30


def test_certification_failure_aborts_instead_of_trying_another_candidate(monkeypatch):
    from spie.questions.brainbloom import state_planning

    attempts = []

    def disagree(*args):
        attempts.append(1)
        raise RuntimeError("Independent solvers disagreed")

    monkeypatch.setattr(state_planning, "_smt_check", disagree)
    with pytest.raises(RuntimeError, match="Independent solvers disagreed"):
        Generator().build(Request("activities", variation="state-planning", seed=7,
                                 engine_revision=7))
    assert len(attempts) == 1


@pytest.mark.parametrize("field", ["model", "answer", "revision"])
def test_saved_state_plan_model_answers_and_revision_cannot_be_tampered_with(
    saved_state_plans, field,
):
    changed = copy.deepcopy(saved_state_plans)
    if field == "model":
        changed["proofs"][0]["model"]["names"][0] += " altered"
    elif field == "answer":
        changed["items"][0]["correctAnswer"] = "forged action"
    else:
        changed["request"]["engine_revision"] = 6
    with pytest.raises(ValueError):
        verify_bundle(changed)
