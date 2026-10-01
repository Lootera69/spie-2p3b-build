"""Human-style clue ordering and quality measurements for custom grids."""

from spie.questions.brainbloom import Request
from spie.questions.brainbloom.grid_quality import assess
from spie.questions.brainbloom.logic_grid import EXAMPLE, check, parse
from spie.questions.brainbloom.service import Generator, verify_bundle


def test_analysis_is_deterministic_and_exposes_checked_deductions():
    model = parse(EXAMPLE)
    solution = check(model, model["rules"])[0]
    first = assess(model, model["rules"], solution)
    second = assess(model, model["rules"], solution)
    assert first == second
    assert "score" not in first and "fair" not in first
    assert first["analysis_version"] == "grid-analysis-v2"
    assert first["deductions"] and first["explanation_steps"]
    assert first["candidate_count"] == 216
    assert first["useful_clues"] + first["redundant_clues"] == len(model["rules"])
    assert first["trace"] and first["hints"] and first["ordered_clues"]


def test_quality_detects_redundant_direct_clues_without_changing_correctness():
    model = parse({
        "groups": "Animal: Tiger, Lion, Owl",
        "rules": "Tiger is in position 1.\nTiger is in position 1.\nLion is in position 2.",
    })
    solution = check(model, model["rules"])[0]
    quality = assess(model, model["rules"], solution)
    assert quality["redundant_clues"] == 1
    assert "fair" not in quality
    assert quality["warnings"]


def test_grid_proof_contains_quality_and_replays_exactly():
    bundle = Generator().build(Request("logic-grid", grid=EXAMPLE))
    quality = bundle["proofs"][0]["quality"]
    assert "level" not in quality
    assert bundle["proofs"][0]["quality_gate"] == "structural-analysis-complete"
    assert quality["trace"]
    assert verify_bundle(bundle) == 1
