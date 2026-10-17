"""Saved drafts are replayed before display or proof-based answer coaching."""

import copy
import json
from contextlib import contextmanager
from http.client import HTTPConnection
from threading import Thread

import pytest

from spie.questions.brainbloom import web
from spie.questions.brainbloom.catalog import Request
from spie.questions.brainbloom.service import Generator


@contextmanager
def running_server(**kwargs):
    server = web.LocalHTTPServer(("127.0.0.1", 0), web.handler_for(Generator(), **kwargs))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def http_server():
    with running_server() as server:
        yield server


@pytest.fixture(scope="module")
def bundle():
    return Generator().build(Request(
        "activities", "multiple-choice", variation="best-move",
        subject="space, ocean", count=2, seed=7,
    ))


def http_call(server, method, path, body=None, headers=None):
    connection = HTTPConnection(*server.server_address, timeout=30)
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def post(server, path, data, headers=None):
    body = json.dumps(data).encode("utf-8")
    status, response_headers, raw = http_call(server, "POST", path, body, {
        "Content-Type": "application/json", **(headers or {}),
    })
    return status, response_headers, json.loads(raw)


def test_saved_bundle_replays_and_answer_feedback_uses_the_selected_item(http_server, bundle):
    before = copy.deepcopy(bundle)
    status, headers, result = post(http_server, "/api/verify-saved", {"bundle": bundle})
    assert status == 200 and result == {"ok": True, "count": 2}
    assert headers["Cache-Control"] == "no-store"
    item = bundle["items"][1]
    status, _, feedback = post(http_server, "/api/check-answer", {
        "bundle": bundle, "index": 1, "answer": item["correctAnswer"],
    })
    assert status == 200
    assert feedback["correct"] is True and feedback["supported"] is True
    assert feedback["message"]
    wrong = next(option for option in item["choices"] if option != item["correctAnswer"])
    status, _, feedback = post(http_server, "/api/check-answer", {
        "bundle": bundle, "index": 1, "answer": wrong,
    })
    assert status == 200
    assert feedback["correct"] is False and feedback["supported"] is True
    assert feedback["message"]
    assert bundle == before


@pytest.mark.parametrize("path", web.SAVED_PATHS)
@pytest.mark.parametrize("tamper", ["item", "proof"])
def test_tampered_full_bundle_is_rejected_before_feedback(
    http_server, bundle, monkeypatch, path, tamper,
):
    changed = copy.deepcopy(bundle)
    # Corrupt a different item from the selected one: every draft must replay.
    if tamper == "item":
        changed["items"][1]["correctAnswer"] = "forged answer"
    else:
        changed["proofs"][1]["item_sha256"] = "forged proof"

    def unexpected_feedback(*args):
        pytest.fail("Unverified proofs must never reach answer coaching")

    monkeypatch.setattr(web, "feedback_for", unexpected_feedback)
    monkeypatch.setattr(web, "grid_feedback", unexpected_feedback)
    payload = {"bundle": changed}
    if path == "/api/check-answer":
        payload.update(index=0, answer=bundle["items"][0]["correctAnswer"])
    elif path == "/api/check-grid":
        payload.update(index=0, entries=[])
    elif path == "/api/play-episode":
        payload.update(index=0, actions=[], hint_level=0)
    status, _, result = post(http_server, path, payload)
    assert status == 400 and "freshly checked" in result["error"]
    assert "correct" not in result


@pytest.mark.parametrize("index", [True, False, -1, 2, 1.5, "0", None])
def test_answer_check_requires_a_valid_integer_index(http_server, bundle, index):
    status, _, result = post(http_server, "/api/check-answer", {
        "bundle": bundle, "index": index, "answer": "A",
    })
    assert status == 400 and "Index" in result["error"]


@pytest.mark.parametrize("answer", [None, False, 42, [], {}, "", " \n ", "x" * 2001])
def test_answer_check_requires_bounded_nonempty_text(http_server, bundle, answer):
    status, _, result = post(http_server, "/api/check-answer", {
        "bundle": bundle, "index": 0, "answer": answer,
    })
    assert status == 400 and "Answer" in result["error"]


@pytest.mark.parametrize("path,payload", [
    ("/api/verify-saved", {}),
    ("/api/verify-saved", {"bundle": None}),
    ("/api/verify-saved", {"bundle": {}}),
    ("/api/verify-saved", {"bundle": {}, "proof": {}}),
    ("/api/check-answer", {"bundle": {}, "index": 0}),
    ("/api/check-answer", {"bundle": {}, "index": 0, "answer": "A", "proof": {}}),
])
def test_saved_endpoints_reject_missing_fields_and_separate_proofs(http_server, path, payload):
    status, _, result = post(http_server, path, payload)
    assert status == 400 and set(result) == {"error"}


@pytest.mark.parametrize("path", web.SAVED_PATHS)
@pytest.mark.parametrize("headers", [
    {"Origin": "https://other.example"}, {"Host": "other.example"},
])
def test_saved_endpoints_keep_same_origin_protection(http_server, bundle, path, headers):
    payload = {"bundle": bundle}
    if path == "/api/check-answer":
        payload.update(index=0, answer="A")
    status, _, result = post(http_server, path, payload, headers)
    assert status == 403 and "same-origin" in result["error"]


def test_saved_bundle_body_allowance_is_larger_but_still_bounded(http_server, bundle):
    body = json.dumps({"bundle": bundle}).encode("utf-8")
    body += b" " * max(0, web.MAX_BODY + 1 - len(body))
    assert web.MAX_BODY < len(body) <= web.MAX_SAVED_BODY
    status, _, raw = http_call(http_server, "POST", "/api/verify-saved", body, {
        "Content-Type": "application/json",
    })
    assert status == 200 and json.loads(raw)["count"] == 2
    for path, limit in (("/api/generate", web.MAX_BODY),
                        ("/api/verify-saved", web.MAX_SAVED_BODY),
                        ("/api/check-answer", web.MAX_SAVED_BODY),
                        ("/api/check-grid", web.MAX_SAVED_BODY)):
        # Reject from framing alone, without transmitting an oversized body.
        status, _, raw = http_call(http_server, "POST", path, headers={
            "Content-Type": "application/json", "Content-Length": str(limit + 1),
        })
        assert status == 400 and str(limit) in json.loads(raw)["error"]


@pytest.mark.parametrize("path", web.SAVED_PATHS)
def test_saved_endpoints_require_json_and_bounded_framing(http_server, path):
    for body, headers in (
        (b"{}", {"Content-Type": "text/plain"}),
        (b"not-json", {"Content-Type": "application/json"}),
        (b"[]", {"Content-Type": "application/json"}),
        (None, {"Content-Type": "application/json", "Transfer-Encoding": "chunked"}),
    ):
        status, _, raw = http_call(http_server, "POST", path, body, headers)
        assert status == 400 and set(json.loads(raw)) == {"error"}


def test_saved_endpoints_share_the_existing_client_rate_limit(bundle):
    with running_server(rate_limit=2) as server:
        assert post(server, "/api/verify-saved", {"bundle": bundle})[0] == 200
        assert post(server, "/api/check-answer", {
            "bundle": bundle, "index": 0, "answer": bundle["items"][0]["correctAnswer"],
        })[0] == 200
        status, _, result = post(server, "/api/verify-saved", {"bundle": bundle})
        assert status == 429 and "Too many requests" in result["error"]


def test_verification_failure_never_returns_feedback(bundle, monkeypatch):
    def failed_verifier(value):
        raise RuntimeError("internal verifier detail")

    monkeypatch.setattr(web, "verify_bundle", failed_verifier)
    with running_server() as server:
        status, _, result = post(server, "/api/check-answer", {
            "bundle": bundle, "index": 0, "answer": "A",
        })
    assert status == 500 and set(result) == {"error"}
    assert "internal verifier detail" not in result["error"]


@pytest.mark.parametrize("script", ["library.js", "player.js", "episode.js", "workspace.js"])
def test_library_script_is_served_with_the_same_static_security_headers(http_server, script):
    status, headers, body = http_call(http_server, "GET", "/" + script)
    assert status == 200 and body
    assert headers["Content-Type"] == "text/javascript; charset=utf-8"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert http_call(http_server, "GET", "/../" + script)[0] == 404


@pytest.fixture(scope="module")
def grid_bundle():
    return Generator().build(Request("logic-grid", "multiple-choice", category="logic", grid={
        "groups": "Animal: Tiger, Lion, Owl",
        "rules": "Tiger is before Lion.\nOwl cannot be next to Tiger.",
        "complete": False, "target": "Owl", "answer_group": "Position",
    }))


def test_grid_endpoint_reports_conflicts_and_checks_complete_entries(http_server, grid_bundle):
    for entries, expected in ((["", "", ""], "consistent"),
                              (["Tiger", "Lion", "Owl"], "correct")):
        status, _, result = post(http_server, "/api/check-grid", {
            "bundle": grid_bundle, "index": 0, "entries": entries,
        })
        assert status == 200 and result[expected] is True
        assert result["conflicts"] == []
    status, _, result = post(http_server, "/api/check-grid", {
        "bundle": grid_bundle, "index": 0, "entries": ["Tiger", "Tiger", ""],
    })
    assert status == 200 and result["consistent"] is False
    assert result["conflicts"][0]["cells"] == [0, 1]
    assert result["conflicts"][0]["kind"] == "duplicate"


@pytest.mark.parametrize("entries", [None, {}, [1], [""], ["Lion", "Tiger", "unknown"],
                                     [""] * 13, ["x" * 101, "", ""]])
def test_grid_endpoint_rejects_invalid_entries(http_server, grid_bundle, entries):
    status, _, result = post(http_server, "/api/check-grid", {
        "bundle": grid_bundle, "index": 0, "entries": entries,
    })
    assert status == 400 and set(result) == {"error"}


@pytest.mark.parametrize("index", [True, False, -1, 1, 1.5, "0", None])
def test_grid_endpoint_rejects_invalid_indices(http_server, grid_bundle, index):
    status, _, result = post(http_server, "/api/check-grid", {
        "bundle": grid_bundle, "index": index, "entries": ["", "", ""],
    })
    assert status == 400 and "Index" in result["error"]
