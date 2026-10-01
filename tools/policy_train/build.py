"""CLI orchestration for the SPIE decision-model trainer: ``python -m tools.policy_train``.

Three subcommands, mirroring the ``calibrate`` command's "fit an artifact, report, never touch the
live path" discipline and the ConceptNet build's "regenerate and diff" reproducibility proof:

* ``build``  — collect the corpus over the pinned grid, fit the per-operator ridge weights, and emit
  ``src/spie/decision_model.py``.
* ``check``  — regenerate the weights in memory and assert the emitted module is **byte-identical**
  to the checked-in artifact (the reproducibility proof; no network needed).
* ``report`` — print the frozen model's in-sample calibration on the corpus (Brier skill, ECE) —
  reported, never a gate.

The grid and hyper-parameters below are the pinned build configuration; they are also written into
the artifact's ``BUILD_PARAMS`` so anyone can reproduce it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

from spie.context_policy import _ALPHA, _RIDGE, ContextualBandit, calibration_report
from spie.mapelites import _CONTEXT_DIM
from spie.operators import OPERATORS

from .collect import Triple, build_corpus
from .emit import compute_artifact_hash, render_module, write_artifact
from .fit import fit

# --- the pinned build configuration --------------------------------------------------------------

# Diverse starting populations (hand-authored example puzzles) crossed with a few integer seeds: a
# uniform-random explorer over each fills niches from a distinct starting point, so the harvested
# contexts span the quality space and the operators get balanced survival labels.
_SEED_POPULATIONS: tuple[tuple[str, ...], ...] = (
    ("move", "which_door", "combination_lock"),
    ("hidden", "lockkey", "pressure"),
    ("two_agents", "push_block", "synchronize"),
    ("transform", "resource", "irreversible"),
)
_INTEGER_SEEDS: tuple[int, ...] = (0, 1, 2)
_ITERATIONS: int = 50

_DEFAULT_ARTIFACT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "spie", "decision_model.py")
)


def _log(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


def _grid() -> list[tuple[tuple[str, ...], int, int]]:
    """The pinned grid of ``(seed population, integer seed, iterations)`` runs."""
    return [(pop, s, _ITERATIONS) for pop in _SEED_POPULATIONS for s in _INTEGER_SEEDS]


def _corpus_hash(corpus: list[Triple]) -> str:
    """A provenance hash of the canonical (sorted) corpus — records where the weights came from."""
    return "sha256:" + hashlib.sha256(repr(tuple(sorted(corpus))).encode("utf-8")).hexdigest()


def _build_params(corpus: list[Triple]) -> dict[str, object]:
    """The exact selection parameters, written into the artifact so it can be regenerated."""
    rows = len(corpus)
    return {
        "seed_populations": [list(pop) for pop in _SEED_POPULATIONS],
        "integer_seeds": list(_INTEGER_SEEDS),
        "iterations": _ITERATIONS,
        "alpha": _ALPHA,
        "ridge": _RIDGE,
        "dim": _CONTEXT_DIM,
        "context_features": "spie.mapelites._context_features",
        "operators": sorted(op.__name__ for op in OPERATORS),
        "corpus_rows": rows,
        "size_min": rows,
        "size_max": rows,
    }


def _collect_and_fit() -> tuple[
    dict[str, list[list[float]]], dict[str, list[float]], list[Triple]
]:
    """Run the pinned grid, harvest the corpus and fit the weights. Deterministic end to end."""
    corpus = build_corpus(_grid())
    a_mat, b_vec = fit(corpus, dim=_CONTEXT_DIM, alpha=_ALPHA, ridge=_RIDGE)
    return a_mat, b_vec, corpus


def _cmd_build(path: str) -> int:
    a_mat, b_vec, corpus = _collect_and_fit()
    survived = sum(1 for _, _, s in corpus if s == 1.0)
    _log(f"corpus: {len(corpus)} triples ({survived} survived), {len(a_mat)} operator(s)")
    artifact_hash = write_artifact(
        path, a_mat, b_vec, dim=_CONTEXT_DIM, alpha=_ALPHA, ridge=_RIDGE,
        corpus_sha256=_corpus_hash(corpus), build_params=_build_params(corpus),
    )
    _log(f"wrote {path}")
    _log(f"ARTIFACT_HASH = {artifact_hash}")
    return 0


def _cmd_check(path: str) -> int:
    a_mat, b_vec, corpus = _collect_and_fit()
    regenerated = render_module(
        a_mat, b_vec, dim=_CONTEXT_DIM, alpha=_ALPHA, ridge=_RIDGE,
        corpus_sha256=_corpus_hash(corpus), build_params=_build_params(corpus),
    )
    if not os.path.exists(path):
        _log(f"check: FAIL — {path} does not exist (run 'build' first)")
        return 1
    with open(path, encoding="utf-8") as fh:
        checked_in = fh.read()
    if regenerated == checked_in:
        _log(f"check: OK — {path} is byte-identical to a fresh regeneration")
        _log(f"ARTIFACT_HASH = {compute_artifact_hash(a_mat, b_vec)}")
        return 0
    _log(f"check: FAIL — {path} differs from a fresh regeneration (weights or format drifted)")
    return 1


def _cmd_report(path: str) -> int:
    a_mat, b_vec, corpus = _collect_and_fit()
    frozen = ContextualBandit(alpha=_ALPHA, ridge=_RIDGE, dim=_CONTEXT_DIM, a_mat=a_mat, b_vec=b_vec)
    log = [(frozen.predict(op, ctx), survived) for ctx, op, survived in corpus]
    report = calibration_report(log)
    _log(
        f"in-sample calibration on {report.n} triples (reported, never a gate): "
        f"base_rate={report.base_rate} brier={report.brier} skill={report.skill} ece={report.ece}"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.policy_train",
        description="Offline trainer for the frozen SPIE decision model (Item 3, Phase C3).",
    )
    parser.add_argument(
        "command", nargs="?", default="build", choices=("build", "check", "report"),
        help="build (default): fit + emit; check: regenerate and diff; report: in-sample calibration",
    )
    parser.add_argument(
        "--out", default=_DEFAULT_ARTIFACT, help="artifact path (default: src/spie/decision_model.py)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        return _cmd_build(args.out)
    if args.command == "check":
        return _cmd_check(args.out)
    return _cmd_report(args.out)


__all__ = ["main"]
