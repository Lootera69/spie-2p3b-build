"""Exercise the actual inline workflow without network calls or real sleeps."""

import subprocess
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/keepalive.yml"


@pytest.fixture
def workflow():
    # The workflow has one inline Python step and needs no checkout or installed package.
    source = dedent(WORKFLOW.read_text(encoding="utf-8").split("        run: |\n", 1)[1])
    namespace = {"__name__": "keepalive_test"}
    exec(compile(source, str(WORKFLOW), "exec"), namespace)
    return namespace


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def use_curl(workflow, run):
    workflow["subprocess"] = SimpleNamespace(
        run=run, TimeoutExpired=subprocess.TimeoutExpired,
    )


def response(status=200, body=b'{"status":"ok"}', returncode=0):
    return SimpleNamespace(stdout=body + f"\n{status}".encode(), returncode=returncode)


def test_retries_fast_errors_and_loading_pages_until_application_starts(workflow, capsys):
    clock = Clock()
    workflow["time"] = clock
    replies = ([response(502, b"Bad gateway")] * 4
               + [response(200, b"<html>Starting service</html>")] * 3
               + [response()])
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return replies.pop(0)

    use_curl(workflow, run)
    assert workflow["warm"]() == 0
    assert len(calls) == 8
    assert clock.now == 70
    assert "warm (application health confirmed)" in capsys.readouterr().out


def test_persistent_fast_failure_uses_budget_then_fails_visibly(workflow, capsys):
    clock = Clock()
    workflow["time"] = clock
    attempts = []

    def run(command, **kwargs):
        attempts.append(kwargs["timeout"])
        assert kwargs["timeout"] <= 420 - clock.now
        return response(502, b"Bad gateway")

    use_curl(workflow, run)
    assert workflow["warm"]() == 1
    assert clock.now == 420
    assert len(attempts) == 42
    output = capsys.readouterr().out
    assert "::error::" in output
    assert "after 42 attempts over 420.0s" in output
    assert "warm (application health confirmed)" not in output


def test_repeated_timeouts_bound_last_request_to_remaining_budget(workflow, capsys):
    clock = Clock()
    workflow["time"] = clock
    timeouts = []

    def run(command, **kwargs):
        timeout = kwargs["timeout"]
        timeouts.append(timeout)
        assert float(command[command.index("--max-time") + 1]) == timeout
        assert float(command[command.index("--connect-timeout") + 1]) <= timeout
        clock.now += timeout
        raise subprocess.TimeoutExpired(command, timeout)

    use_curl(workflow, run)
    assert workflow["warm"]() == 1
    assert timeouts == [100, 100, 100, 90]
    assert clock.now == 420
    assert "request timed out after 90.0s" in capsys.readouterr().out


def test_transient_timeout_recovers(workflow):
    clock = Clock()
    workflow["time"] = clock
    attempts = []

    def run(command, **kwargs):
        attempts.append(kwargs["timeout"])
        if len(attempts) == 1:
            clock.now += kwargs["timeout"]
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return response()

    use_curl(workflow, run)
    assert workflow["warm"]() == 0
    assert len(attempts) == 2
    assert clock.now == 110


@pytest.mark.parametrize(("status", "body", "returncode", "expected"), [
    (200, b'{"status":"ok"}', 0, True),
    (200, b'  { "status": "ok" }\n', 0, True),
    (200, b'{"status":"starting"}', 0, False),
    (200, b'{"status":"ok","other":true}', 0, False),
    (200, b'"ok"', 0, False),
    (200, b'<html>Starting service</html>', 0, False),
    (200, b'\xff', 0, False),
    (502, b'{"status":"ok"}', 0, False),
    (200, b'{"status":"ok"}', 28, False),
    (200, b'{"status":"ok"}', 63, False),
    (200, b' ' * 4096 + b'{"status":"ok"}', 0, False),
])
def test_only_successful_exact_health_object_confirms_readiness(
    workflow, status, body, returncode, expected,
):
    def run(command, **kwargs):
        assert command[command.index("--header") + 1] == "Accept: application/json"
        assert command[command.index("--max-filesize") + 1] == "4096"
        assert kwargs["timeout"] == 37
        return response(status, body, returncode)

    use_curl(workflow, run)
    healthy, _ = workflow["probe"](37)
    assert healthy is expected
