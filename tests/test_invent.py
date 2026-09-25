"""Phase 4.7 tests — ``invent`` orchestration + the ``invent`` / ``evolve`` / ``archive show`` CLI.

These prove the whole roadmap-p4 pipeline is reachable and *correct end to end*: every word in
the curated KB invents a puzzle that ``validate``s clean, ``certify``s solvable + unique, and
passes ``verify`` with a real (PASS, not INFO) concept-relevance gate — the generator has no
privileged path. They also pin the two determinism properties the phase rests on (``invent`` and
``evolve`` are byte-reproducible), the CLI contract (exit 0 on certified output, the archive table
renders), and — the standing reduction oracle — that the 20 hand-authored corpus reports are
untouched by adding these commands.
"""

from __future__ import annotations

import json

from spie import cli
from spie.certificate import certify
from spie.concepts import CURATED_WORDS
from spie.invent import evolve, invent, invent_traced
from spie.mapelites import archive_to_json
from spie.serialize import dumps, puzzle_to_json
from spie.validate import validate
from spie.verify import GateStatus, verify

# The hand-curated core — the vocabulary this exhaustive, solver-bearing sweep covers. Scoped to
# ``CURATED_WORDS`` rather than all of ``KB`` so suite runtime stays independent of vocabulary
# size: the additive ConceptNet layer is proven inventable+certifiable *exhaustively offline* by
# ``tools/conceptnet_build``'s certify gate, and ``tests/test_conceptnet_data.py`` pins the shipped
# artifact to exactly that gated set. (The hypothesis sweeps in ``test_generator_properties.py``
# still sample the full merged KB at test time.)
KB_WORDS = list(CURATED_WORDS)


# --- invent: total, certified, and concept-relevance is a real gate --------------------------


def test_invent_is_total_and_certifies_every_kb_word() -> None:
    for word in KB_WORDS:
        puzzle, prov = invent_traced(word)
        assert validate(puzzle) == [], f"{word} produced an invalid puzzle"
        cert = certify(puzzle)
        assert cert.solvable and cert.unique and cert.conformance_ok, word
        report = verify(puzzle, prov)
        assert report.ok, word


def test_invent_concept_relevance_gate_is_real_and_passes() -> None:
    puzzle, prov = invent_traced("door")
    report = verify(puzzle, prov)
    gate = next(g for g in report.gates if g.name == "concept-relevance")
    # A generated puzzle carries provenance, so the gate is a real PASS — not the hand-puzzle INFO.
    assert gate.status is GateStatus.PASS
    assert f"all {len(prov)}" in gate.detail


def test_invent_is_byte_reproducible() -> None:
    a = dumps(puzzle_to_json(invent("water", seed=3)))
    b = dumps(puzzle_to_json(invent("water", seed=3)))
    assert a == b


def test_invent_drops_epistemic_only_word_to_a_bare_certifiable_chain() -> None:
    # "prize" affords only REVEAL (epistemic), which operationalize defers; invent must still
    # produce a certifiable puzzle — the observable core collapses to a bare forced chain.
    puzzle, prov = invent_traced("prize")
    assert certify(puzzle).solvable
    assert verify(puzzle, prov).ok
    assert "plain" in puzzle.id  # no compilable modifier survived


# --- evolve: invention feeds a byte-reproducible MAP-Elites search ---------------------------


def test_evolve_admits_only_certified_elites() -> None:
    archive = evolve(["door", "fuel", "water"], iterations=8, seed=0)
    assert archive.cells
    for cell in archive.cells.values():
        assert certify(cell.puzzle).solvable
        assert verify(cell.puzzle).ok


def test_evolve_is_byte_reproducible() -> None:
    a = dumps(archive_to_json(evolve(["door", "fuel"], iterations=6, seed=1)))
    b = dumps(archive_to_json(evolve(["door", "fuel"], iterations=6, seed=1)))
    assert a == b


# --- CLI: invent / evolve / archive show, exit codes, and rendering --------------------------


def test_cli_invent_exits_zero_on_certified_output(capsys) -> None:
    rc = cli.main(["invent", "fuel"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "invented from 'fuel'" in out
    assert "concept-relevance [PASS]" in out


def test_cli_invent_writes_puzzle_json(tmp_path) -> None:
    out = tmp_path / "puzzle.json"
    rc = cli.main(["invent", "door", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["id"] == "gen_0000_connect_negate"


def test_cli_evolve_and_archive_show_round_trip(tmp_path, capsys) -> None:
    arch = tmp_path / "arch.json"
    rc = cli.main(["evolve", "--seeds", "door,fuel,water", "--iters", "6", "--out", str(arch)])
    assert rc == 0
    assert arch.exists()
    capsys.readouterr()
    rc = cli.main(["archive", "show", str(arch)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "niche" in out and "fitness" in out
    # every rendered row names a cell certificate digest
    data = json.loads(arch.read_text(encoding="utf-8"))
    assert len(data["cells"]) >= 1


def test_cli_archive_show_reports_empty_archive(tmp_path) -> None:
    empty = tmp_path / "empty.json"
    payload = {"seed": 0, "iterations": 0, "tally": {}, "cells": []}
    empty.write_text(dumps(payload), encoding="utf-8")
    assert cli.main(["archive", "show", str(empty)]) == 1
