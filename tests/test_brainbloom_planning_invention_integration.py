"""New planning strategies are versioned without rewriting saved physical plans."""

import copy
import json
from http.client import HTTPConnection
from threading import Thread

import pytest

from spie.forge.corpus import digest
from spie.questions.brainbloom import Request, state_planning, web
from spie.questions.brainbloom.brief import Brief, prepare
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.workshop import candidate

# Captured before revision eight was implemented. The physical state-planning-v1
# schema stays valid, while revision seven must retain its exact search/RNG path.
REVISION_SEVEN = {
    "multiple-choice": (
        "7aa7a9e686a8c111f2aba60f46baf0cf6c04c4fa044049e617895b16bdf05ea8",
        "256dfb8bc6094836288e9004a816f6ffa3deb32a65cd7cd96c0b092c700d8380",
    ),
    "true-false": (
        "6cae42ff2f4bff24ec301b4061d8bcc0909a5b971ed34a1cded78b5d73917716",
        "2d89ae64e14f9cf83e661ce8a44d1d6e6a773b53ea9afe8f42d23818e7571421",
    ),
    "type-answer": (
        "b74ee22c3cf5f6432b5742e234e0bcf64ecbabcc148ac0d93a8d9d1d0627bc80",
        "d447d49eb04078a19e00fa38da146e0e3353022be1b27f90ee1656c6f29d5eb3",
    ),
    "riddle": (
        "a73364c28a19584e9636fde1786ff7e0845e977ba61c3975905748c32b822660",
        "537559a8d914ce7bfca7905f8294a9b5a1841073627cf3d405364749aac27e58",
    ),
}


@pytest.mark.parametrize("kind", REVISION_SEVEN)
def test_revision_seven_keeps_exact_item_and_proof_digests_and_saved_replay(kind):
    request = Request("activities", kind, "hard", variation="state-planning",
                      subject="space, ocean", engine_revision=7, seed=7)
    item, proof = candidate(request, 7)
    assert (digest(item), digest(proof)) == REVISION_SEVEN[kind]
    assert "design_version" not in proof["model"] and "strategy" not in proof
    bundle = Generator().build(request)
    assert verify_bundle(json.loads(json.dumps(bundle))) == 1


@pytest.fixture(scope="module")
def invented_bundle():
    engine = Generator()
    report = prepare(Brief(activity="state-planning", subject="space, ocean",
                           difficulty="hard", qtype="multiple-choice", seed=7),
                     engine.dictionary)
    assert report["ready"], report["message"]
    assert report["request"]["engine_revision"] == 8
    return engine.build(Request(**report["request"]))


def test_creator_default_generates_a_certified_strategy_and_replays_it(invented_bundle):
    assert invented_bundle["summary"]["complete"]
    proof = invented_bundle["proofs"][0]
    assert proof["model"]["version"] == "state-planning-v1"
    assert proof["model"]["design_version"] == "planning-invention-v1"
    assert proof["model"]["strategy"] == "invest-energy"
    assert isinstance(proof["strategy"], dict) and proof["strategy"]
    assert state_planning.check(proof["model"])["strategy"] == proof["strategy"]
    assert verify_bundle(json.loads(json.dumps(invented_bundle))) == 1


@pytest.mark.parametrize("field", ["design_version", "strategy", "certificate", "revision"])
def test_saved_strategy_claims_and_revision_cannot_be_forged(invented_bundle, field):
    changed = copy.deepcopy(invented_bundle)
    if field == "certificate":
        changed["proofs"][0]["strategy"] = {}
    elif field == "revision":
        changed["request"]["engine_revision"] = 7
    else:
        changed["proofs"][0]["model"][field] = "forged"
    with pytest.raises(ValueError):
        verify_bundle(changed)


def test_exhausted_invention_search_cannot_export_a_partial_batch(monkeypatch):
    from spie.questions.brainbloom import planning_invention

    original = planning_invention.propose
    attempts = []

    def one_then_exhausted(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return original(*args, **kwargs)
        return original(*args, **{**kwargs, "budget": 0})

    monkeypatch.setattr(planning_invention, "propose", one_then_exhausted)
    with pytest.raises(ValueError, match="59 candidate searches.*No partial batch exported"):
        Generator().build(Request("activities", variation="state-planning", seed=7, count=2,
                                 difficulty="hard", subject="space, ocean"))
    assert len(attempts) == 60


def test_invention_verification_failure_aborts_instead_of_spending_another_budget(monkeypatch):
    attempts = []

    def disagree(*args):
        attempts.append(1)
        raise RuntimeError("Independent solvers disagreed")

    monkeypatch.setattr(state_planning, "_smt_check", disagree)
    with pytest.raises(RuntimeError, match="Independent solvers disagreed"):
        Generator().build(Request("activities", variation="state-planning", seed=7,
                                 difficulty="hard", subject="space, ocean"))
    assert len(attempts) == 1


@pytest.fixture(scope="module")
def api_server():
    server = web.LocalHTTPServer(("127.0.0.1", 0), web.handler_for(Generator()))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(server, path, payload):
    connection = HTTPConnection(*server.server_address, timeout=30)
    try:
        connection.request("POST", path, json.dumps(payload), {"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_api_prepares_generates_replays_and_coaches_the_new_strategy(api_server):
    status, report = post(api_server, "/api/prepare", {
        "activity": "state-planning", "subject": "animals, space", "difficulty": "easy",
        "qtype": "multiple-choice", "seed": 7,
    })
    assert status == 200 and report["ready"]
    assert report["request"]["engine_revision"] == 8
    status, bundle = post(api_server, "/api/generate", report["request"])
    assert status == 200 and bundle["summary"]["complete"]
    assert bundle["proofs"][0]["model"]["strategy"] == "invest-energy"
    assert bundle["proofs"][0]["strategy"]
    status, report = post(api_server, "/api/verify-saved", {"bundle": bundle})
    assert status == 200 and report == {"ok": True, "count": 1}
    item = bundle["items"][0]
    for answer in item["choices"]:
        status, report = post(api_server, "/api/check-answer", {
            "bundle": bundle, "index": 0, "answer": answer,
        })
        assert status == 200 and report["supported"]
        assert report["correct"] is (answer == item["correctAnswer"])
        assert report["message"]
