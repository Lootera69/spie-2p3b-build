"""Phase 5.3 tests — the deterministic PRESENTATION renderer.

The renderer is proven to honor the non-negotiable invariant (**no gameplay logic absent from the
formal representation**) by three checked properties over the whole corpus:

* **Rules are a bijection with the formal rep** — the set of locations, state variables, and
  action templates named in the rendered rules is *exactly* the set the puzzle declares (nothing
  invented, nothing hidden).
* **Hints are a subset of the proof** — every action the hint ladder discloses is one the
  certified solution itself prescribes.
* **The answer's replay is a faithful re-derivation** — a fully-observable answer replays the
  certificate's own action trace; a hidden answer reaches the goal on every world of B0.

Plus the standing disciplines: output is strictly ASCII (Windows cp1252-safe), the render is
deterministic, and the corpus stays byte-identical (the renderer is a pure new consumer that
writes nothing and mutates nothing).
"""

from __future__ import annotations

import glob
import os

import pytest

from spie import presentation, search
from spie.certificate import certify
from spie.conformance import check_plan_conformance
from spie.serialize import dumps, load_puzzle, puzzle_to_json

_EXAMPLES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "examples"))
_PATHS = sorted(glob.glob(os.path.join(_EXAMPLES, "*.json")))


def _block(lines: list[str], header: str) -> list[str]:
    """The indented child lines under a zero-indent ``header`` in a rules listing, up to the next
    zero-indent line (the renderer emits no blank lines within the rules)."""
    if header not in lines:
        return []
    i = lines.index(header) + 1
    out: list[str] = []
    while i < len(lines) and lines[i].startswith(" "):
        out.append(lines[i])
        i += 1
    return out


@pytest.fixture(params=_PATHS, ids=lambda p: os.path.basename(p), scope="module")
def case(request):
    """Each corpus puzzle certified once (module-scoped): (path, puzzle, certificate)."""
    path = request.param
    puzzle = load_puzzle(path)
    return path, puzzle, certify(puzzle)


def test_rules_are_a_bijection_with_the_formal_rep(case) -> None:
    _path, puzzle, _cert = case
    rl = presentation.rules_lines(puzzle)
    locs = {ln.strip() for ln in _block(rl, "Locations:") if ln.strip() != "(none)"}
    assert locs == set(puzzle.nodes)
    svars = {ln.strip().split(":", 1)[0] for ln in _block(rl, "State variables:")}
    assert svars == {v.key for v in puzzle.variables}
    names = {
        ln.strip()[:-1]
        for ln in _block(rl, "Actions:")
        if (len(ln) - len(ln.lstrip(" "))) == 2 and ln.rstrip().endswith(":")
    }
    assert names == {a.name for a in puzzle.actions}


def test_hint_actions_are_a_subset_of_the_proof(case) -> None:
    _path, puzzle, cert = case
    disclosed = set(presentation.hint_actions(puzzle, cert))
    assert disclosed <= presentation._proof_action_set(puzzle, cert)


def test_answer_replay_is_a_faithful_rederivation(case) -> None:
    _path, puzzle, cert = case
    if cert.plan is not None:
        conf = check_plan_conformance(puzzle, cert.plan)
        assert conf.world_replays
        assert all(wr.reached_goal and wr.ok for wr in conf.world_replays)
    else:
        sol = search.canonical_solution(puzzle)
        assert [s.action for s in cert.solution] == list(sol.trace)


def test_render_is_ascii_only(case) -> None:
    _path, puzzle, cert = case
    text = "\n".join(presentation.render(puzzle, cert))
    assert all(ord(c) < 128 for c in text), "presentation must be cp1252-safe ASCII"


def test_render_is_deterministic(case) -> None:
    path, puzzle, cert = case
    reloaded = load_puzzle(path)
    assert presentation.render(puzzle, cert) == presentation.render(reloaded, certify(reloaded))


def test_presentation_does_not_perturb_the_corpus(case) -> None:
    # The renderer is a pure consumer: exercising it must not change the on-disk puzzle bytes.
    path, puzzle, cert = case
    with open(path, encoding="utf-8") as fh:
        on_disk = fh.read()
    presentation.render(puzzle, cert)
    assert dumps(puzzle_to_json(load_puzzle(path))) == on_disk
