"""Phase C3 tests — the frozen SPIE decision model is *provably* the artifact the offline fit
produced, and its runtime proposer is *provably* propose-only and thesis-safe.

The heavy work — harvesting a corpus from SPIE's own search and fitting the per-operator LinUCB
weights — happens **offline** in ``tools/policy_train``; the shipped engine only *loads* the frozen
result. That offline fit transfers to run time only if the checked-in artifact is exactly what was
fitted, which :func:`test_artifact_content_hash_is_stable` establishes (the same rigor bridge as
``tests/test_conceptnet_data.py``). The rest of the module proves the runtime contract the whole
thesis rests on: the proposer only chooses *what to try* (deterministically, RNG-free), never learns
online, and cannot admit a puzzle the ``validate -> verify -> certify`` gate has not certified.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

from spie.certificate import certify
from spie.concepts import normalize
from spie.context_policy import _ALPHA, _RIDGE
from spie.decision import FrozenProposer, load_decision_model
from spie.decision_model import (
    A_MAT,
    ALPHA,
    ARTIFACT_HASH,
    B_VEC,
    BUILD_PARAMS,
    CORPUS_SHA256,
    DIM,
    MODEL_VERSION,
    RIDGE,
    _canonical,
    compute_artifact_hash,
)
from spie.invent import evolve, invent
from spie.mapelites import _CONTEXT_DIM, archive_to_json
from spie.mapelites import evolve as mapelites_evolve
from spie.operators import OPERATORS
from spie.serialize import dumps
from spie.validate import validate
from spie.verify import verify

# A representative in-range parent context (all features already normalized to [0, 1]).
_CONTEXT = (1.0, 0.5, 0.3, 0.4, 0.6, 2 / 7, 1 / 7)
_ALL_OPERATORS = tuple(sorted(op.__name__ for op in OPERATORS))

# --- The rigor bridge: the shipped weights are what the offline fit produced -----------------


def test_artifact_content_hash_is_stable() -> None:
    """``ARTIFACT_HASH`` is a *pinned literal* the trainer emitted alongside the weights it had just
    fitted. Recomputing it from ``repr(_canonical(A_MAT, B_VEC))`` — the canonical data structure,
    so reformatting the generated source is irrelevant — proves the shipped weights are
    byte-identical to the fitted ones. Any later hand edit to the weights breaks this test."""
    blob = repr(_canonical(A_MAT, B_VEC)).encode("utf-8")
    recomputed = "sha256:" + hashlib.sha256(blob).hexdigest()
    assert recomputed == ARTIFACT_HASH, "the artifact was edited after the fit produced it"
    # The module's own published recipe must agree with the recomputation above.
    assert compute_artifact_hash() == ARTIFACT_HASH


def test_declared_provenance_is_consistent_with_the_weights() -> None:
    """Provenance and weights never drift: an unfitted artifact carries no weights, and a fitted one
    pins its corpus, records how to regenerate it, and lands inside its own declared size band with
    the shared context dimension. So neither emptying the weights nor widening the grid past the
    approved scope can pass silently."""
    assert MODEL_VERSION == "1"
    if not A_MAT:
        assert not B_VEC, "weights half-populated"
        return
    assert CORPUS_SHA256.startswith("sha256:") and len(CORPUS_SHA256) == 71
    assert BUILD_PARAMS, "a fitted artifact must record how to regenerate it"
    assert DIM == _CONTEXT_DIM == 7, "artifact dimension must match the shared context features"
    assert (ALPHA, RIDGE) == (_ALPHA, _RIDGE), "artifact hyper-parameters drifted from the source"
    rows = BUILD_PARAMS["corpus_rows"]
    lo, hi = BUILD_PARAMS["size_min"], BUILD_PARAMS["size_max"]
    assert lo <= rows <= hi, f"{rows} outside [{lo}, {hi}]"
    assert set(A_MAT) == set(B_VEC), "operator keys differ between A_MAT and B_VEC"
    assert set(A_MAT) <= set(BUILD_PARAMS["operators"]), "a weight key is not a known operator"
    assert list(A_MAT) == sorted(A_MAT), "A_MAT is not in sorted-operator order"
    for name, mat in A_MAT.items():
        assert len(mat) == DIM and all(len(row) == DIM for row in mat), f"{name} matrix not DIMxDIM"
        assert len(B_VEC[name]) == DIM, f"{name} vector not length DIM"


# --- The runtime contract: propose-only, deterministic, never the correctness path -----------


def test_loader_mirrors_the_artifact_verbatim() -> None:
    """:func:`load_decision_model` reproduces the frozen weights value-for-value (copied, not
    aliased), so the runtime bandit is exactly the fitted model."""
    bandit = load_decision_model()
    assert (bandit.dim, bandit.alpha, bandit.ridge) == (DIM, ALPHA, RIDGE)
    assert bandit.a_mat == A_MAT and bandit.b_vec == B_VEC
    assert bandit.a_mat is not A_MAT, "loader aliased the module-level literal"


def test_frozen_proposer_is_deterministic_and_propose_only() -> None:
    """The operator pick is a deterministic, RNG-free ``argmax`` of the frozen calibrated survival
    estimate (identical across calls and across fresh instances), and ``reward`` is propose-only: it
    credits the online niche bandit but leaves the frozen operator weights byte-unchanged, so a run
    can never perturb the shipped artifact."""
    proposer = FrozenProposer()
    first = proposer.choose_operator(_ALL_OPERATORS, _CONTEXT)
    assert first in _ALL_OPERATORS
    assert proposer.choose_operator(_ALL_OPERATORS, _CONTEXT) == first, "not deterministic per call"
    assert FrozenProposer().choose_operator(_ALL_OPERATORS, _CONTEXT) == first, "instance-dependent"
    before_a = {k: [list(r) for r in v] for k, v in proposer.operators.a_mat.items()}
    before_b = {k: list(v) for k, v in proposer.operators.b_vec.items()}
    proposer.reward(("1", "0", "0", "0"), first, 1.0, _CONTEXT)
    proposer.reward(("1", "0", "0", "0"), first, 0.0, _CONTEXT)
    assert proposer.operators.a_mat == before_a, "reward mutated the frozen operator matrix"
    assert proposer.operators.b_vec == before_b, "reward mutated the frozen operator vector"
    assert proposer.niches.stats, "reward must still credit the online niche bandit"


def test_frozen_proposer_admits_only_certified_puzzles() -> None:
    """A ``FrozenProposer``-driven search occupies niches, and every elite it admits still cleared
    the unchanged ``validate -> verify -> certify`` gate — the proposer proposes, the solvers
    judge."""
    archive = evolve(["move"], 12, 0, policy=FrozenProposer())
    assert archive.cells, "the trained proposer occupied no niche"
    for cell in archive.cells.values():
        assert not validate(cell.puzzle), "an admitted puzzle has validation findings"
        assert verify(cell.puzzle).ok, "an admitted puzzle failed a verification gate"
        assert certify(cell.puzzle).solvable, "an admitted puzzle is not certifiably solvable"


def test_trained_policy_driven_evolve_is_byte_reproducible() -> None:
    """Two runs with a fresh ``FrozenProposer`` and the same ``(seeds, iterations, seed)`` serialize
    identically: the operator model is frozen, the niche bandit is RNG-free, so nothing perturbs the
    single seeded stream."""
    a1 = evolve(["move"], 12, 0, policy=FrozenProposer())
    a2 = evolve(["move"], 12, 0, policy=FrozenProposer())
    assert dumps(archive_to_json(a1)) == dumps(archive_to_json(a2))


def test_default_none_path_is_the_uniform_search() -> None:
    """Threading the new ``policy`` argument left the default untouched: ``policy=None`` is the
    historical uniform search, byte-for-byte, and ``invent.evolve``'s default is a pure pass-through
    to :func:`spie.mapelites.evolve` with no policy — so the wiring cannot silently steer the
    baseline."""
    seeds = ["move"]
    default = evolve(seeds, 10, 0)
    explicit = evolve(seeds, 10, 0, policy=None)
    assert dumps(archive_to_json(default)) == dumps(archive_to_json(explicit))
    puzzles = [replace(invent(w, seed=0), id=f"inv_{normalize(w)}") for w in seeds]
    direct = mapelites_evolve(puzzles, 10, 0)
    assert dumps(archive_to_json(default)) == dumps(archive_to_json(direct)), "policy=None drifted"
