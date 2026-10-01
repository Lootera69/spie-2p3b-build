"""Emit the frozen artifact ``src/spie/decision_model.py`` from fitted decision-model weights.

Emission has the same two constraints as the ConceptNet emitter:

* **The artifact lives inside ``src``**, so it is *shipped* and must pass ``ruff check src tests`` —
  every line <= 100 columns. A per-operator weight matrix is a 7x7 block of floats, far too wide for
  one line, so ``A_MAT`` / ``B_VEC`` are written by a recursive pretty-printer (:func:`render_value`)
  that breaks any list or dict that would overflow, guaranteeing the column bound.
* **The content hash must not depend on the formatting.** ``ARTIFACT_HASH`` is ``"sha256:" +
  sha256(repr(_canonical(a_mat, b_vec)))`` — over a *canonical, sorted-key* view of the runtime
  weights, not the emitted text — so the pretty-printer's line breaks are irrelevant to it, and the
  dict iteration order cannot perturb it. ``tests/test_decision_model.py`` recomputes exactly this.

The module header is a fixed template held here verbatim, so only the fitted values vary between
builds: ``CORPUS_SHA256``, ``BUILD_PARAMS``, ``DIM`` / ``ALPHA`` / ``RIDGE``, ``A_MAT`` / ``B_VEC``
and the derived ``ARTIFACT_HASH``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

_MAX_COLS = 100

MODEL_VERSION = "1"


def _flat(value: object) -> str:
    """The compact single-line rendering of an artifact value (floats, ints, ASCII strings, and
    lists/tuples/dicts thereof)."""
    if isinstance(value, bool):  # guard: bool is an int subclass, render it as a keyword
        return "True" if value else "False"
    if isinstance(value, str):
        return '"' + value + '"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, tuple):
        if len(value) == 1:
            return "(" + _flat(value[0]) + ",)"
        return "(" + ", ".join(_flat(item) for item in value) + ")"
    if isinstance(value, list):
        return "[" + ", ".join(_flat(item) for item in value) + "]"
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{k!r}: {_flat(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"non-artifact value {value!r}")


def render_value(value: object, indent: int, *, width: int = _MAX_COLS) -> str:
    """A ``<=width`` rendering of ``value``; the first line is unindented, the rest indented.

    Reserves one column for a trailing comma at every level. Only containers (list/tuple/dict) can
    be broken; a leaf too long to fit is emitted whole (our floats never approach the limit)."""
    flat = _flat(value)
    if indent + len(flat) + 1 <= width:
        return flat
    inner = indent + 4
    if isinstance(value, Mapping):
        lines = ["{"]
        for key, item in value.items():
            prefix = " " * inner + f"{key!r}: "
            lines.append(prefix + render_value(item, len(prefix), width=width) + ",")
        lines.append(" " * indent + "}")
        return "\n".join(lines)
    if isinstance(value, list | tuple):
        open_b, close_b = ("[", "]") if isinstance(value, list) else ("(", ")")
        lines = [open_b]
        for item in value:
            lines.append(" " * inner + render_value(item, inner, width=width) + ",")
        lines.append(" " * indent + close_b)
        return "\n".join(lines)
    return flat  # unbreakable leaf longer than width (never happens for our data)


def _render_build_params(params: Mapping[str, object]) -> str:
    """``BUILD_PARAMS`` as a stable, one-key-per-line dict literal (keys sorted), each value laid out
    by :func:`render_value` so even a long grid stays within the column bound."""
    if not params:
        return "{}"
    lines = ["{"]
    for key in sorted(params):
        prefix = f"    {key!r}: "
        lines.append(prefix + render_value(params[key], len(prefix)) + ",")
    lines.append("}")
    return "\n".join(lines)


def _canonical(
    a_mat: Mapping[str, list[list[float]]], b_vec: Mapping[str, list[float]]
) -> tuple:
    """A sorted-key, tuple-of-tuples view of the weights — the structure the hash is taken over, so
    the artifact hash depends only on the values, never on dict insertion order or formatting."""
    return tuple(
        (name, tuple(tuple(row) for row in a_mat[name]), tuple(b_vec[name]))
        for name in sorted(a_mat)
    )


def compute_artifact_hash(
    a_mat: Mapping[str, list[list[float]]], b_vec: Mapping[str, list[float]]
) -> str:
    """``ARTIFACT_HASH`` for ``(a_mat, b_vec)`` — the identical recipe the shipped module carries."""
    return "sha256:" + hashlib.sha256(repr(_canonical(a_mat, b_vec)).encode("utf-8")).hexdigest()


_HEADER = '''\
"""Item 3, Phase C3 — the generated SPIE decision model (offline, frozen, **never hand-edited**).

GENERATED FILE — produced by ``tools/policy_train`` from a corpus SPIE harvests from its own search,
and checked in as a frozen artifact. Regenerate it with the recipe in :data:`BUILD_PARAMS`; never
edit it by hand: :data:`ARTIFACT_HASH` pins the exact weights the offline fit produced, and
``tests/test_decision_model.py`` recomputes that hash.

What this is, and why it is thesis-safe:

* **A propose-only decision model.** The values below are the per-operator ridge stats of a disjoint
  LinUCB bandit (Li et al. 2010): for each mutation operator, ``A_MAT[op] = ridge*I + Σ x·xᵀ`` and
  ``B_VEC[op] = Σ survived·x`` over the training triples, where ``x`` is the parent elite's
  :func:`spie.mapelites._context_features` vector and ``survived`` is the child's outcome under the
  unchanged ``validate -> verify -> certify`` gate. :class:`spie.decision.FrozenProposer` loads them
  and proposes ``argmax_op predict(op, context)`` — it only chooses *what operator to try*.
* **The solvers remain the sole judge.** Every child the proposer suggests still clears the formal
  gate before it can occupy a cell; the fitted weights never touch acceptance, and at runtime the
  model never learns online (``FrozenProposer.reward`` credits nothing back to these weights).
* **Plain primitives, no ``spie`` import.** The weights are ``float`` / ``list`` / ``dict`` only, so
  this module imports nothing from :mod:`spie`: there is no import cycle, and the artifact is a pure
  data literal whose content hash the shipped tests re-derive.
* **Offline and reproducible.** The corpus is generated once, deterministically, from the pinned
  grid in :data:`BUILD_PARAMS`; importing this module touches no network, no API and no model, so
  the engine's LLM-free, byte-reproducible thesis is untouched.
"""

from __future__ import annotations

import hashlib

MODEL_VERSION = "{model_version}"
"""The trainer revision that produced these weights."""

CORPUS_SHA256 = "{corpus_sha256}"
"""sha256 of the canonical training corpus — provenance. Empty only while the artifact is empty
(no corpus has been fitted yet)."""

BUILD_PARAMS: dict[str, object] = {build_params}
"""The exact grid and hyper-parameters the fit ran with, so the artifact can be regenerated.
Empty only while the artifact is empty."""

DIM = {dim}
"""The context-vector width (:data:`spie.mapelites._CONTEXT_DIM`); each weight row/vector is DIM
long. The features are defined solely by ``spie.mapelites._context_features``, shared by train and
inference so there is no feature skew."""

ALPHA = {alpha}
"""The LinUCB exploration weight the model was fitted under (reported; the frozen proposer exploits
the mean and does not add an exploration bonus)."""

RIDGE = {ridge}
"""The ridge prior ``A0 = ridge*I`` — keeps every per-operator matrix symmetric positive-definite
(hence invertible) and every untried operator tied at the prior."""

A_MAT: dict[str, list[list[float]]] = {a_mat}
"""Per-operator ridge matrix ``A = ridge*I + Σ x·xᵀ`` (6-dp-rounded), keyed by operator
``__name__``, in sorted-key order."""

B_VEC: dict[str, list[float]] = {b_vec}
"""Per-operator ridge vector ``b = Σ survived·x`` (6-dp-rounded), keyed by operator ``__name__``,
in sorted-key order."""

ARTIFACT_HASH = "{artifact_hash}"
"""The content hash the trainer emitted for the weights — a *pinned literal*, not a recomputation,
so any later hand edit is caught by the test that recomputes it. Hashed over a canonical sorted-key
view of ``(A_MAT, B_VEC)`` rather than the file bytes, so reformatting cannot break it."""


def _canonical(
    a_mat: dict[str, list[list[float]]] = A_MAT, b_vec: dict[str, list[float]] = B_VEC
) -> tuple:
    """A sorted-key, tuple-of-tuples view of the weights — the structure the hash is taken over."""
    return tuple(
        (name, tuple(tuple(row) for row in a_mat[name]), tuple(b_vec[name]))
        for name in sorted(a_mat)
    )


def compute_artifact_hash(
    a_mat: dict[str, list[list[float]]] = A_MAT, b_vec: dict[str, list[float]] = B_VEC
) -> str:
    """The canonical content hash of the weights — the recipe :data:`ARTIFACT_HASH` pins.

    A pure function of the data structure (via ``repr`` of :func:`_canonical`), shared by the
    offline trainer and the test that verifies the shipped artifact is exactly what the fit
    produced."""
    return "sha256:" + hashlib.sha256(repr(_canonical(a_mat, b_vec)).encode("utf-8")).hexdigest()


__all__ = [
    "MODEL_VERSION",
    "CORPUS_SHA256",
    "BUILD_PARAMS",
    "DIM",
    "ALPHA",
    "RIDGE",
    "A_MAT",
    "B_VEC",
    "ARTIFACT_HASH",
    "compute_artifact_hash",
]
'''


def render_module(
    a_mat: Mapping[str, list[list[float]]],
    b_vec: Mapping[str, list[float]],
    *,
    dim: int,
    alpha: float,
    ridge: float,
    corpus_sha256: str,
    build_params: Mapping[str, object],
) -> str:
    """The full text of ``decision_model.py`` for the given weights and build provenance."""
    return _HEADER.format(
        model_version=MODEL_VERSION,
        corpus_sha256=corpus_sha256,
        build_params=_render_build_params(build_params),
        dim=dim,
        alpha=repr(alpha),
        ridge=repr(ridge),
        a_mat=render_value(dict(a_mat), 0),
        b_vec=render_value(dict(b_vec), 0),
        artifact_hash=compute_artifact_hash(a_mat, b_vec),
    )


def write_artifact(
    path: str,
    a_mat: Mapping[str, list[list[float]]],
    b_vec: Mapping[str, list[float]],
    *,
    dim: int,
    alpha: float,
    ridge: float,
    corpus_sha256: str,
    build_params: Mapping[str, object],
) -> str:
    """Write the artifact module and return its ``ARTIFACT_HASH`` (for the build's own logging)."""
    text = render_module(
        a_mat, b_vec, dim=dim, alpha=alpha, ridge=ridge,
        corpus_sha256=corpus_sha256, build_params=build_params,
    )
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return compute_artifact_hash(a_mat, b_vec)


__all__ = [
    "MODEL_VERSION",
    "render_value",
    "compute_artifact_hash",
    "render_module",
    "write_artifact",
]
