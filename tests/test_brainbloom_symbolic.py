"""Production draft generation: mathematical truth, schema, scope, and safe export."""

from __future__ import annotations

import copy
import importlib
import json
import os
import socket
import subprocess
import sys
import threading
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path

import pytest

from spie.forge.contract import issues
from spie.forge.corpus import compact, digest
from spie.questions import prover
from spie.questions.brainbloom.__main__ import main
from spie.questions.brainbloom.generate import (
    DIFFICULTIES,
    THEMES,
    TYPES,
    Request,
    candidate,
    generate,
)
from spie.questions.brainbloom.logic import Literal, Problem, Rule, analyze, holds, worlds
from spie.questions.brainbloom.service import Generator, verify_bundle
from spie.questions.brainbloom.web import LocalHTTPServer, handler_for

generate_mod = importlib.import_module("spie.questions.brainbloom.generate")
web_module = importlib.import_module("spie.questions.brainbloom.web")


def problem_from(proof):
    value = proof["problem"]
    return Problem(
        tuple(value["attributes"]),
        tuple(Rule(Literal(**r["before"]), Literal(**r["after"])) for r in value["rules"]),
        tuple(Literal(**f) for f in value["facts"]),
    )


@pytest.mark.parametrize("topic", THEMES)
@pytest.mark.parametrize("qtype", TYPES)
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_all_supported_inputs_generate_checked_app_contracts(topic, qtype, difficulty):
    for seed in range(6):
        result = generate(Request(topic, qtype, difficulty, seed=seed))
        item, proof = result["items"][0], result["proofs"][0]
        assert issues(item) == []
        assert item["difficulty"] == difficulty
        assert item["type"] == qtype
        assert proof["minimal_required_rules"] == DIFFICULTIES[difficulty]
        assert proof["agree"] and proof["consistent"]
        assert digest(item) == proof["item_sha256"]
        assert "acceptedAnswers" not in item
        assert not result["intendedImport"]["published"]
        assert result["intendedImport"]["reviewStatus"] == "draft"
        assert not result["provenance"]["learned_model_used"]
        problem = problem_from(proof)
        assert all(attribute not in item["title"].lower() for attribute in problem.attributes)
        rows = worlds(problem)
        verdicts = []
        for verdict in proof["candidates"]:
            literal = Literal(**verdict["literal"])
            value = all(holds(literal, row) for row in rows)
            assert value == verdict["entailed"] == verdict["truth_table_entailed"]
            verdicts.append(value)
            if value:
                assert verdict["counterexample"] is None
            else:
                counter = tuple(verdict["counterexample"])
                assert counter in rows and not holds(literal, counter)
        if qtype == "multiple-choice":
            assert len(item["choices"]) == 4 and sum(verdicts) == 1
            assert item["choices"][verdicts.index(True)] == item["correctAnswer"]
        else:
            assert item["choices"] == ["True", "False"]
            assert item["correctAnswer"] == str(verdicts[0])


@pytest.mark.parametrize("changes", [
    {"topic": "conditional reasoning in a warehouse"}, {"topic": "space travel"},
    {"category": "science"}, {"qtype": "riddle"}, {"qtype": "type-answer"},
    {"difficulty": "expert"}, {"count": 0}, {"count": 21}, {"count": True},
    {"count": 1.5}, {"seed": -1}, {"seed": True}, {"seed": 2**32},
])
def test_unsupported_inputs_are_not_silently_ignored(changes):
    with pytest.raises(ValueError):
        replace(Request(), **changes)


def test_both_truth_labels_and_reasoning_directions_are_exercised():
    results = [generate(Request(qtype="true-false", seed=i)) for i in range(12)]
    assert {r["items"][0]["correctAnswer"] for r in results} == {"True", "False"}
    assert {r["proofs"][0]["reasoning_direction"] for r in results} == {
        "forward", "contraposition",
    }


def test_same_inputs_reproduce_identical_bytes_across_processes():
    code = (
        "from spie.questions.brainbloom.generate import Request,generate; "
        "from spie.forge.corpus import compact; print(compact(generate(Request(seed=71))))"
    )
    outputs = [subprocess.check_output(
        [sys.executable, "-B", "-c", code], env={**os.environ, "PYTHONHASHSEED": salt},
    ) for salt in ("1", "321")]
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0]) == json.loads(compact(generate(Request(seed=71))))


def test_export_reproves_and_rejects_tampered_question_answer_or_evidence():
    original = json.loads(compact(Generator().build(Request(difficulty="hard"))))
    assert verify_bundle(original) == 1
    for field in ("question", "correctAnswer", "difficulty", "choices", "correctExplanation"):
        changed = copy.deepcopy(original)
        changed["items"][0][field] = "tampered"
        changed["proofs"][0]["item_sha256"] = digest(changed["items"][0])
        with pytest.raises(ValueError, match="freshly checked"):
            verify_bundle(changed)
    changed = copy.deepcopy(original)
    changed["proofs"][0]["agree"] = False
    with pytest.raises(ValueError, match="freshly checked"):
        verify_bundle(changed)
    changed = copy.deepcopy(original)
    changed["intendedImport"]["published"] = True
    with pytest.raises(ValueError, match="unpublished"):
        verify_bundle(changed)


def test_solver_disagreement_blocks_generation(monkeypatch):
    decide = prover.decide
    monkeypatch.setattr(prover, "decide", lambda formula: (not decide(formula)[0], None))
    with pytest.raises(RuntimeError, match="entailment disagreement"):
        generate(Request())


def test_satisfiability_disagreement_blocks_generation(monkeypatch):
    monkeypatch.setattr(prover, "satisfiable", lambda formula: (False, None))
    with pytest.raises(RuntimeError, match="satisfiability disagreement"):
        generate(Request())


def test_unknown_is_not_treated_as_proof(monkeypatch):
    import z3

    class Unknown:
        def add(self, *args):
            pass

        def check(self):
            return z3.unknown

    monkeypatch.setattr(prover.z3, "Solver", Unknown)
    with pytest.raises(RuntimeError, match="satisfiability"):
        generate(Request())


def test_contradiction_cannot_make_every_answer_vacuously_true():
    p = Literal(0)
    problem = Problem(("sealed", "tagged"), (Rule(p, Literal(1)),), (p, p.opposite()))
    with pytest.raises(ValueError, match="Contradictory"):
        analyze(problem, (Literal(1),))


def test_difficulty_measurement_is_load_bearing(monkeypatch):
    monkeypatch.setattr(generate_mod, "minimum_rules", lambda *args: 0)
    with pytest.raises(RuntimeError, match="Difficulty mismatch"):
        generate(Request())


def test_bank_duplicates_skipped_without_changing_bank():
    request = Request(seed=17)
    existing = (generate(request)["items"][0],)
    before = compact(existing)
    result = generate(request, existing)
    assert result["provenance"]["bank_items_compared"] == 1
    assert result["provenance"]["duplicate_candidates_skipped"] >= 1
    assert result["items"][0]["question"] != existing[0]["question"]
    assert compact(existing) == before


def test_batch_varies_content_and_never_hides_exhaustion(monkeypatch):
    request = Request(count=3, seed=42)
    result = generate(request)
    assert len({i["question"] for i in result["items"]}) == 3
    assert len({i["correctAnswer"] for i in result["items"]}) == 3
    fixed = candidate(request, 42)
    monkeypatch.setattr(generate_mod, "candidate", lambda *args: fixed)
    with pytest.raises(ValueError, match="No partial batch"):
        generate(request)


def test_platform_rejection_removes_matching_proof_and_reports_incomplete(monkeypatch):
    from spie.questions.brainbloom import service

    def reject(result, path):
        result["rejected"].append({"item": result["items"].pop(0), "issues": ["dup-near"]})
        return result

    engine = Generator()
    engine.verifier = Path("unused.ts")
    monkeypatch.setattr(service, "check_platform", reject)
    result = engine.build(Request(count=2))
    assert result["summary"] == {
        "requested": 2, "accepted": 1, "rejected": 1, "complete": False, "published": False,
    }
    assert len(result["proofs"]) == 1
    assert result["proofs"][0]["item_sha256"] == digest(result["items"][0])


def test_cli_export_replay_and_no_overwrite(tmp_path):
    out = tmp_path / "draft.json"
    args = ["generate", "--topic", "warehouse", "--difficulty", "hard", "--out", str(out)]
    assert main(args) == 0
    before = out.read_bytes()
    assert main(["check", str(out)]) == 0
    assert main(args) == 2
    assert out.read_bytes() == before


@pytest.fixture
def http_server():
    server = LocalHTTPServer(("127.0.0.1", 0), handler_for(Generator()))
    server.connection_timeout = 0.2
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def http_call(server, method, path, data=None, headers=None):
    connection = HTTPConnection(*server.server_address, timeout=20)
    try:
        connection.request(method, path, data, headers or {})
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        connection.close()


def test_local_form_assets_and_generation(http_server):
    for path in ("/", "/app.js", "/style.css", "/api/config"):
        status, headers, body = http_call(http_server, "GET", path)
        assert status == 200 and body
        assert dict(headers)["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in dict(headers)["Content-Security-Policy"]
    status, _, body = http_call(http_server, "POST", "/api/generate", '{"seed":7}', {
        "Content-Type": "application/json",
    })
    assert status == 200
    result = json.loads(body)
    assert result["summary"]["accepted"] == 1 and verify_bundle(result) == 1


@pytest.mark.parametrize("path", ["/api/publish", "/api/import", "/../pyproject.toml", "/.env"])
def test_no_publish_import_or_filesystem_endpoint(http_server, path):
    assert http_call(http_server, "GET", path)[0] == 404
    assert http_call(http_server, "POST", path)[0] == 404


def test_cross_origin_dns_rebinding_and_bad_inputs_rejected(http_server):
    for headers in ({"Origin": "https://example.org"}, {"Host": "evil.example"}):
        assert http_call(http_server, "GET", "/api/config", headers=headers)[0] == 403
        assert http_call(http_server, "POST", "/api/generate", "{}", headers)[0] == 403
    for data in ('{"count":true}', '{"topic":"unrelated"}', '[]', '{"publish":true}', 'x'):
        status, _, _ = http_call(http_server, "POST", "/api/generate", data, {
            "Content-Type": "application/json",
        })
        assert status == 400
    assert http_call(http_server, "POST", "/api/generate", "{}", {
        "Content-Type": "text/plain",
    })[0] == 400


def test_server_fails_closed_if_formal_gate_disagrees(http_server, monkeypatch):
    monkeypatch.setattr(prover, "satisfiable", lambda _: (False, None))
    status, _, body = http_call(http_server, "POST", "/api/generate", "{}", {
        "Content-Type": "application/json",
    })
    assert status == 500
    assert "items" not in json.loads(body)


def test_idle_browser_connection_does_not_block_the_workshop(http_server):
    with socket.create_connection(http_server.server_address, timeout=2):
        assert http_call(http_server, "GET", "/api/config")[0] == 200


def test_truncated_request_body_is_rejected(http_server):
    with socket.create_connection(http_server.server_address, timeout=2) as connection:
        port = http_server.server_address[1]
        connection.sendall((
            f"POST /api/generate HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\nContent-Length: 10\r\n\r\n{}"
        ).encode())
        connection.shutdown(socket.SHUT_WR)
        assert b"400 Bad Request" in connection.recv(4096)


@pytest.mark.parametrize("value", [None, [], "draft", 1, {}, {"version": True}])
def test_cli_handles_malformed_bundle_without_a_traceback(tmp_path, value):
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert main(["check", str(path)]) == 2


@pytest.mark.parametrize("field,value", [
    ("request", []), ("request", {"unknown": True}), ("proofs", [None]),
    ("items", [None]), ("summary", {"complete": True}), ("rejected", [{}]),
])
def test_replay_rejects_malformed_nested_data_and_misleading_counts(field, value):
    bundle = Generator().build(Request())
    bundle[field] = value
    with pytest.raises(ValueError):
        verify_bundle(bundle)


def test_replay_rejects_an_incomplete_batch_claiming_completion():
    bundle = Generator().build(Request(count=2))
    bundle["items"].pop()
    bundle["proofs"].pop()
    with pytest.raises(ValueError, match="count"):
        verify_bundle(bundle)


def test_cli_reads_a_windows_bom_bundle(tmp_path):
    path = tmp_path / "windows.json"
    path.write_text(compact(Generator().build(Request())), encoding="utf-8-sig")
    assert main(["check", str(path)]) == 0


def test_serve_open_flag_reaches_the_local_server(monkeypatch):
    from spie.questions.brainbloom import web

    calls = []
    monkeypatch.setattr(web, "serve", lambda engine, port, **kw: calls.append((port, kw)))
    for name in ("PORT", "BRAINBLOOM_HOST", "BRAINBLOOM_PUBLIC_ORIGIN"):
        monkeypatch.delenv(name, raising=False)
    assert main(["serve", "--port", "8768", "--open"]) == 0
    assert calls == [
        (8768, {"open_browser": True, "host": "127.0.0.1", "public_origin": None})
    ]


def test_serve_defaults_to_loopback_but_reads_the_hosted_environment(monkeypatch):
    from spie.questions.brainbloom import web

    calls = []
    monkeypatch.setattr(web, "serve", lambda engine, port, **kw: calls.append((port, kw)))
    monkeypatch.delenv("BRAINBLOOM_HOST", raising=False)
    monkeypatch.delenv("BRAINBLOOM_PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("PORT", "10000")
    assert main(["serve"]) == 0
    assert calls == [(10000, {"open_browser": False, "host": "127.0.0.1", "public_origin": None})]

    calls.clear()
    monkeypatch.setenv("BRAINBLOOM_HOST", "0.0.0.0")
    monkeypatch.setenv("BRAINBLOOM_PUBLIC_ORIGIN", "https://demo.example")
    assert main(["serve"]) == 0
    assert calls == [
        (10000, {"open_browser": False, "host": "0.0.0.0",
                 "public_origin": "https://demo.example"})
    ]

    calls.clear()
    monkeypatch.setenv("PORT", "not-a-port")
    assert main(["serve"]) == 2
    assert calls == []


def test_public_origin_must_be_a_bare_scheme_and_host():
    assert web_module.parse_public_origin("HTTPS://Demo.Example/") == (
        "demo.example", "https://demo.example"
    )
    assert web_module.parse_public_origin("http://box:8080") == (
        "box:8080", "http://box:8080"
    )
    for bad in ("demo.example", "ftp://demo.example", "https://", "https://demo.example/app"):
        with pytest.raises(ValueError):
            web_module.parse_public_origin(bad)


def test_public_origin_widens_the_allowlist_without_opening_other_hosts():
    server = LocalHTTPServer(("127.0.0.1", 0), handler_for(
        Generator(), public_origin="https://demo.example"
    ))
    server.connection_timeout = 0.2
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        # The deployed host is reachable, and only under its own https origin.
        assert http_call(server, "GET", "/api/config", headers={
            "Host": "demo.example", "Origin": "https://demo.example"})[0] == 200
        assert http_call(server, "GET", "/api/config", headers={
            "Host": "demo.example", "Origin": "http://demo.example"})[0] == 403
        # Loopback keeps working, and still only over http.
        assert http_call(server, "GET", "/api/config", headers={
            "Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}"})[0] == 200
        assert http_call(server, "GET", "/api/config", headers={
            "Host": f"127.0.0.1:{port}", "Origin": "https://demo.example"})[0] == 403
        # Naming one public origin opens no other host.
        assert http_call(server, "GET", "/api/config", headers={"Host": "evil.example"})[0] == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_healthz_answers_before_the_origin_check_and_never_generates(http_server):
    status, _, body = http_call(http_server, "GET", "/healthz", headers={"Host": "probe.internal"})
    assert status == 200 and json.loads(body) == {"status": "ok"}
    assert http_call(http_server, "POST", "/healthz", "{}", {"Host": "probe.internal"})[0] == 403


def test_rate_limit_caps_one_client_without_touching_a_loopback_run():
    limiter = web_module.RateLimiter(2, window=10.0)
    assert limiter.allow("a", now=0.0) and limiter.allow("a", now=1.0)
    assert not limiter.allow("a", now=2.0)  # Third call inside the window.
    assert limiter.allow("b", now=2.0)  # A different client is unaffected.
    assert limiter.allow("a", now=11.0)  # The window has rolled over.
    # Loopback serving passes limit 0, which must never reject.
    unlimited = web_module.RateLimiter(0)
    assert all(unlimited.allow("a") for _ in range(100))
