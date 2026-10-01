"""Local, non-LLM regression measurements; not a human or frontier-model benchmark."""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter

from .catalog import DIFFICULTIES, Request
from .reasoning import STYLES
from .service import Generator, verify_bundle


def run(engine: Generator, subject: str, seeds: int = 3, sense: str = "") -> dict:
    if type(seeds) is not int or not 1 <= seeds <= 30:
        raise ValueError("Benchmark seeds must be an integer from 1 to 30")
    results, structures = [], defaultdict(set)
    for style in STYLES:
        for difficulty in DIFFICULTIES:
            for seed in range(seeds):
                request = Request("reasoning", difficulty=difficulty, seed=seed,
                                  subject=subject, sense=sense, variation=style)
                start = perf_counter()
                try:
                    bundle = engine.build(request)
                except ValueError as exc:
                    results.append({"style": style, "difficulty": difficulty, "seed": seed,
                                    "status": "rejected", "reason": str(exc)})
                    continue
                if not bundle["items"]:
                    results.append({"style": style, "difficulty": difficulty, "seed": seed,
                                    "status": "rejected", "reason": "Editorial gate rejected"})
                    continue
                elapsed = perf_counter() - start
                verify_bundle(bundle)  # A checker failure stops the benchmark, not a passing row.
                proof = bundle["proofs"][0]
                search = proof["search"]
                if search["selected_score"] < search["first_qualified_score"]:
                    raise RuntimeError("Candidate ranking regressed against its first valid draft")
                structures[style].add(proof["structural_key"])
                results.append({
                    "style": style, "difficulty": difficulty, "seed": seed, "status": "verified",
                    "generation_seconds": round(elapsed, 4), "quality": proof["quality"],
                    "candidate_acceptance": search["qualified"] / search["budget"],
                    "heuristic_score_gain": (
                        search["selected_score"] - search["first_qualified_score"]
                    ),
                    "structural_key": proof["structural_key"], "item_sha256": proof["item_sha256"],
                })
    verified = [row for row in results if row["status"] == "verified"]
    return {
        "benchmark": "brainbloom-reasoning-regression-v1", "subject": subject, "sense": sense,
        "seeds_per_style_and_difficulty": seeds,
        "scope": "bounded synthetic tasks; no human ratings or frontier-model comparison",
        "learned_model_used": False,
        "summary": {
            "requested": len(results), "verified": len(verified),
            "rejected": len(results) - len(verified),
            "mean_generation_seconds": round(
                sum(row["generation_seconds"] for row in verified) / max(1, len(verified)), 4
            ),
            "improved_over_first_qualified": sum(
                row["heuristic_score_gain"] > 0 for row in verified
            ),
            "unique_structures_per_style": {style: len(structures[style]) for style in STYLES},
        },
        "results": results,
    }
