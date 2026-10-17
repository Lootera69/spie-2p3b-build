"""Real HTTP episode replay, bundle-cache trust and transcript isolation."""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from http.client import HTTPConnection
from threading import Thread

import pytest
from tools.benchmark_state_planning import initial, oracle, shortest

from spie.questions.brainbloom import planning_episode, web
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.service import Generator


@contextmanager
def running_server():
    server = web.LocalHTTPServer(("127.0.0.1", 0), web.handler_for(Generator()))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(server, data, path="/api/play-episode"):
    connection = HTTPConnection(*server.server_address, timeout=30)
    try:
        connection.request("POST", path, json.dumps(data).encode(),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read())
    finally:
        connection.close()


def payload(bundle, actions=None, hint_level=0):
    return {"bundle": bundle, "index": 0, "actions": [] if actions is None else actions,
            "hint_level": hint_level}


@pytest.fixture(scope="module", params=(11, 12, 13, 14, 15))
def bundle(request):
    # Exercise all playable revisions. API regression seeds are separate from
    # the predefined held-out profile/scenario evaluation cases.
    result = Generator().build(Request(
        "activities", "multiple-choice", variation="state-planning",
        subject="space, ocean", count=1, seed=1701, engine_revision=request.param,
    ))
    assert result["summary"]["complete"]
    assert result["proofs"][0]["model"]["experience_version"] == {
        11: "planning-experience-v1", 12: "planning-experience-v2", 13: "planning-experience-v3",
        14: "planning-experience-v4",
        15: "planning-experience-v5",
    }[request.param]
    assert result["proofs"][0]["episode"]["version"] == {
        11: planning_episode.VERSION, 12: "planning-episode-v2", 13: "planning-episode-v2",
        14: "planning-episode-v3",
        15: "planning-episode-v4",
    }[request.param]
    return result


@pytest.mark.parametrize("difficulty", ("easy", "medium", "hard"))
def test_twenty_item_revision15_batches_play_inside_original_body_limit(http_server, difficulty):
    batch = Generator().build(Request(
        "activities", "multiple-choice", difficulty, variation="state-planning",
        subject="space, ocean", count=20, seed=1506, engine_revision=15))
    assert batch["summary"]["complete"] and len(batch["items"]) == 20
    request = {"bundle": batch, "index": 19, "actions": [], "hint_level": 0}
    assert len(json.dumps({**request, "actions": ["x" * 40] * 128}).encode()) < web.MAX_SAVED_BODY
    status, _, view = post(http_server, request)
    assert status == 200 and view["status"] == "in_progress"
    request["actions"] = batch["proofs"][19]["model"]["solution"]
    status, _, view = post(http_server, request)
    assert status == 200 and view["status"] == "complete"


@pytest.fixture(scope="module")
def http_server():
    with running_server() as server:
        yield server


def _state(view):
    state = view["state"]
    return (state["location"], state["energy"], *state["gates"], int(state["recharged"]))


def test_real_server_replays_each_move_and_accepts_complete_and_slower_routes(http_server, bundle):
    model = bundle["proofs"][0]["model"]
    expected = oracle(model)
    actions = []
    for state in expected["solution_states"]:
        status, headers, view = post(http_server, payload(bundle, actions))
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert _state(view) == tuple(state)
        assert view["actions"] == actions
        assert set(view["legal_actions"]) == set(expected["graph"][tuple(state)])
        assert view["hint"] is None
        if len(actions) < len(expected["solution"]):
            actions = [*actions, expected["solution"][len(actions)]]
    assert view["status"] == "complete" and view["resolution"]
    assert not view["can_append"] and not view["local_actions"]
    alternative = next(action for action, cost in expected["first_costs"].items()
                       if cost is not None and cost > expected["best_steps"])
    target = expected["graph"][initial(model)][alternative]
    _, _, suffix = shortest(model, expected["graph"], target)
    slower = [alternative, *suffix]
    status, _, slower_view = post(http_server, payload(bundle, slower))
    assert status == 200 and slower_view["goal_reached"]
    assert slower_view["state"]["steps"] > view["state"]["steps"]
    assert slower_view["resolution"]["text"] == view["resolution"]["text"]
    if bundle["request"]["engine_revision"] == 11:
        assert slower_view["resolution"]["dialogue"] == view["resolution"]["dialogue"]
    else:
        assert slower_view["scenario"]["resolution"] == view["scenario"]["resolution"]


@pytest.mark.parametrize("field,value", [
    ("index", True), ("index", -1), ("index", 1), ("index", "0"),
    ("actions", None), ("actions", "recharge"), ("actions", [True]),
    ("actions", [""]), ("actions", ["a" * 41]), ("actions", ["switch_0"] * 129),
    ("hint_level", True), ("hint_level", 1.0), ("hint_level", -1),
    ("hint_level", 4), ("hint_level", "2"), ("hint_level", None),
])
def test_episode_http_rejects_malformed_fields(http_server, bundle, field, value):
    request = payload(bundle)
    request[field] = value
    status, _, result = post(http_server, request)
    assert status == 400 and set(result) == {"error"}


@pytest.mark.parametrize("field", ["bundle", "index", "actions", "hint_level"])
def test_episode_http_requires_every_field(http_server, bundle, field):
    request = payload(bundle)
    del request[field]
    status, _, result = post(http_server, request)
    assert status == 400 and "Expected" in result["error"]


@pytest.mark.parametrize("extra", ["state", "scenario", "proof", "goal_reached"])
def test_episode_http_refuses_separate_caller_state_or_evidence(http_server, bundle, extra):
    request = {**payload(bundle), extra: {"location": 4, "energy": 8}}
    status, _, result = post(http_server, request)
    assert status == 400 and "Expected" in result["error"]


def test_bundle_cache_only_reuses_verification_of_exact_content(bundle, monkeypatch):
    verifier, replay = web.verify_bundle, planning_episode.replay
    verified, transcripts = [], []

    def counted_verifier(value):
        verified.append(copy.deepcopy(value))
        return verifier(value)

    def counted_replay(model, scenario, actions, *, hint_level=0):
        transcripts.append(list(actions))
        return replay(model, scenario, actions, hint_level=hint_level)

    monkeypatch.setattr(web, "verify_bundle", counted_verifier)
    monkeypatch.setattr(planning_episode, "replay", counted_replay)
    expected = oracle(bundle["proofs"][0]["model"])
    first = expected["solution"][:1]
    with running_server() as server:
        assert post(server, {"bundle": bundle}, "/api/verify-saved")[0] == 200
        assert len(verified) == 1
        empty = post(server, payload(bundle))[2]
        advanced = post(server, payload(bundle, first))[2]
        restored = post(server, payload(bundle))[2]
        status, _, rejected = post(server, payload(bundle, ["teleport"]))
        assert status == 400 and "unknown or illegal" in rejected["error"]
        assert transcripts == [[], first, [], ["teleport"]]
        assert restored == empty and advanced["state"] != empty["state"]
        assert len(verified) == 1
        # Key insertion order is not a content change.
        reordered = dict(reversed(list(bundle.items())))
        assert post(server, payload(reordered))[0] == 200
        assert len(verified) == 1
        # Even non-authoritative extra metadata must earn its own verification.
        decorated = {**bundle, "caller_note": "cache test"}
        assert post(server, payload(decorated))[0] == 200
        assert len(verified) == 2


@pytest.mark.parametrize("tamper", ["scenario", "model", "certificate", "item"])
def test_tamper_after_cache_priming_cannot_reach_episode_runtime(bundle, monkeypatch, tamper):
    verifier, verified = web.verify_bundle, []

    def counted(value):
        verified.append(value)
        return verifier(value)

    monkeypatch.setattr(web, "verify_bundle", counted)
    with running_server() as server:
        assert post(server, payload(bundle))[0] == 200
        assert len(verified) == 1
        changed = copy.deepcopy(bundle)
        if tamper == "scenario":
            changed["proofs"][0]["episode"]["title"] += " Emergency"
        elif tamper == "model":
            changed["proofs"][0]["model"]["initial_energy"] += 1
        elif tamper == "certificate":
            changed["proofs"][0]["experience"]["forged"] = True
        else:
            changed["items"][0]["correctAnswer"] = "forged answer"

        def unexpected_replay(*args, **kwargs):
            pytest.fail("Unverified content reached the runtime")

        monkeypatch.setattr(planning_episode, "replay", unexpected_replay)
        for _ in range(2):
            status, _, result = post(server, payload(changed))
            assert status == 400 and "freshly checked" in result["error"]
        # Failed verification is not cached either.
        assert len(verified) == 3


def test_http_rejects_an_action_after_goal_and_hints_only_reveal_explicit_help(http_server, bundle):
    solution = oracle(bundle["proofs"][0]["model"])["solution"]
    status, _, result = post(http_server, payload(bundle, [*solution, solution[0]]))
    assert status == 400 and "already completed" in result["error"]
    for level in (0, 1, 2, 3):
        status, _, view = post(http_server, payload(bundle, hint_level=level))
        assert status == 200
        if level == 0:
            assert view["hint"] is None
        elif level < 3:
            assert "action" not in view["hint"]
            assert "hint.next" not in {fact["id"] for fact in view["facts"]}
        else:
            assert view["hint"]["action"] == solution[0]
        assert "solution" not in view and "first_costs" not in view


def test_old_verified_bundle_has_no_playable_episode(http_server):
    old = Generator().build(Request(
        "activities", "multiple-choice", variation="state-planning", subject="space, ocean",
        count=1, seed=1701, engine_revision=10,
    ))
    assert old["summary"]["complete"]
    assert "episode" not in old["proofs"][0]
    assert post(http_server, {"bundle": old}, "/api/verify-saved")[0] == 200
    status, _, result = post(http_server, payload(old))
    assert status == 400 and "does not contain a playable episode" in result["error"]


def test_episode_script_is_served_with_existing_security_headers(http_server):
    connection = HTTPConnection(*http_server.server_address, timeout=30)
    try:
        connection.request("GET", "/episode.js")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/javascript; charset=utf-8"
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert "script-src 'self'" in response.getheader("Content-Security-Policy")
        assert response.read()
    finally:
        connection.close()
