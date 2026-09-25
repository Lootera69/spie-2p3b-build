"""Phase 4.8 / 5.5 — property-based cross-validation of the *invention* layer and the
roadmap's back half (EVALUATION -> ARCHIVE -> PRESENTATION -> LEARNING).

Where :mod:`test_property` and :mod:`test_epistemic_properties` hunt for a puzzle on which the
independent *solvers* disagree, this module lifts that adversarial search to the **generator**:
``hypothesis`` searches for an invented / mutated / archived puzzle that escapes the correctness
gates. The first three properties are the strongest form of the Phase-4 thesis — *creativity from
search, correctness from the formal solvers, no privileged path*:

1. **Generator soundness (pipeline).** Every word in the curated KB, at any seed, invents a puzzle
   that is ``validate``-clean, ``certify``-solvable, and passes ``verify`` with its provenance —
   the concept→mechanic pipeline can never emit an unproven puzzle. (The example-based
   :mod:`test_invent` pins this exhaustively at ``seed=0``; here it is fuzzed over seeds.)
2. **Operator well-formedness.** Any of the sixteen invention operators, applied to any corpus
   puzzle under any rng state, returns either ``None`` (does not apply) or a ``validate``-clean
   puzzle — never a structurally-broken one. This is the invariant the MAP-Elites search leans on
   to gate mutants safely.
3. **Archive soundness + determinism.** A bounded MAP-Elites run admits *only* certified elites
   (every archived cell re-``validate``s, re-``verify``s, and re-``certify``s), and the archive is
   **byte-reproducible** for a given ``(seeds, iterations, seed)`` — the determinism discipline
   lifted to search, fuzzed over seeds and iteration budgets.

Phase 5.5 lifts the same discipline to the back-half signals, fuzzed rather than pinned:

4. **Strategy / surprise determinism.** The bounded-rational strategy read and the surprise pivot
   are pure functions of the puzzle value — recomputing them from a freshly-built puzzle is
   byte-identical, the score stays in ``[0, 1]``, and every solvable corpus puzzle is read to
   completion (no budget blow-up). No RNG lives in the evaluator.
5. **Calibration byte-reproducibility.** A whole recalibration run is reproducible for its
   ``(players, base_seed)``, the fitted train correlation *never* underperforms the default
   baseline (coordinate ascent accepts only strict improvements), and the reported held-out
   correlation is a genuine number in ``[-1, 1]`` over a disjoint held-out split.
6. **Presentation fidelity on invented puzzles.** The renderer's bijection with the formal rep and
   its hints-subset-of-the-proof invariant — proven over the hand corpus in
   :mod:`test_presentation` — hold for *every invented* puzzle too, and the render stays ASCII.
7. **Archive read-back is a true inverse.** ``archive_from_json`` reconstructs an archive whose
   re-serialization is byte-identical, preserving every cell's lineage and content address and the
   full rejection history — the round-trip LEARNING depends on to read archives back.

Any counterexample is a real defect (never a warning), minimized automatically.
"""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from spie import calibrate, fingerprint, mapelites, operators, presentation
from spie.certificate import certify
from spie.concepts import KB
from spie.examples_src import BUILDERS
from spie.invent import invent, invent_traced
from spie.serialize import dumps
from spie.strategy import strategy_of, surprise_of
from spie.validate import validate
from spie.verify import verify

# The whole vocabulary the pipeline claims to be total over, and the corpus builders by name.
KB_WORDS = sorted(KB)
BY_NAME = {b.__name__: b for b in BUILDERS}

# The 20-puzzle corpus (built once) and its shared novelty fingerprint set, for the LEARNING and
# strategy properties below -- computed once so the fuzzers do not rebuild it per example.
_CORPUS = [b() for b in BUILDERS]
_CORPUS_FP = fingerprint.corpus_fingerprints(_CORPUS)


def _block(lines: list[str], header: str) -> list[str]:
    """The indented child lines under a zero-indent ``header`` in a rules listing (the renderer
    emits no blank lines within the rules) -- the same reader :mod:`test_presentation` uses."""
    if header not in lines:
        return []
    i = lines.index(header) + 1
    out: list[str] = []
    while i < len(lines) and lines[i].startswith(" "):
        out.append(lines[i])
        i += 1
    return out


@settings(max_examples=20, deadline=None)
@given(word=st.sampled_from(KB_WORDS), seed=st.integers(min_value=0, max_value=8))
def test_invented_puzzle_is_always_sound(word: str, seed: int) -> None:
    """Pipeline soundness: no KB word, at any seed, can invent an unproven puzzle."""
    puzzle, prov = invent_traced(word, seed=seed)
    assert validate(puzzle) == [], f"{word}@{seed} invented an invalid puzzle"
    cert = certify(puzzle)
    assert cert.solvable and cert.unique and cert.conformance_ok, f"{word}@{seed}"
    assert verify(puzzle, prov).ok, f"{word}@{seed} failed a verification gate"


@settings(max_examples=120, deadline=None)
@given(
    op=st.sampled_from(operators.OPERATORS),
    name=st.sampled_from(sorted(BY_NAME)),
    rng_seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_operator_yields_valid_or_none(op: operators.Operator, name: str, rng_seed: int) -> None:
    """Operator well-formedness: every operator on every corpus puzzle is either a no-op or a
    validate-clean mutation — the guarantee that lets the search gate mutants without special
    casing."""
    result = op(BY_NAME[name](), random.Random(rng_seed))
    assert result is None or validate(result) == [], f"{op.__name__} on {name} yielded a bad puzzle"


@settings(max_examples=6, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=100),
    iterations=st.integers(min_value=0, max_value=3),
)
def test_archive_is_reproducible_and_admits_only_sound_elites(seed: int, iterations: int) -> None:
    """Archive soundness + determinism, fuzzed: a bounded run is byte-reproducible for its
    ``(seeds, iterations, seed)`` and every admitted elite independently re-certifies — the
    generator has no way to seat an unproven puzzle in the archive."""
    first = mapelites.evolve([BY_NAME["move"]()], iterations, seed)
    second = mapelites.evolve([BY_NAME["move"]()], iterations, seed)
    assert dumps(mapelites.archive_to_json(first)) == dumps(mapelites.archive_to_json(second))
    for cell in first.cells.values():
        assert validate(cell.puzzle) == []
        assert verify(cell.puzzle).ok
        assert certify(cell.puzzle).solvable


# --- Phase 5.5: the back-half signals (EVALUATION / ARCHIVE / PRESENTATION / LEARNING) --------


@settings(max_examples=20, deadline=None)
@given(name=st.sampled_from(sorted(BY_NAME)))
def test_strategy_and_surprise_are_deterministic_functions_of_the_puzzle(name: str) -> None:
    """Strategy / surprise determinism: the evaluator holds no RNG, so recomputing the read from a
    freshly-built puzzle is byte-identical; the score stays a probability and every solvable corpus
    puzzle is read to completion (never hits the effort guard)."""
    build = BY_NAME[name]
    sr_a, sr_b = strategy_of(build()), strategy_of(build())
    su_a, su_b = surprise_of(build()), surprise_of(build())
    assert sr_a == sr_b, f"{name}: strategy read is not a pure function of the puzzle"
    assert su_a == su_b, f"{name}: surprise read is not a pure function of the puzzle"
    assert sr_a.solvable and sr_a.complete, f"{name}: corpus puzzle not read to completion"
    assert sr_a.backtracks >= 0 and sr_a.steps_taken >= 0
    assert 0.0 <= su_a.score <= 1.0, f"{name}: surprise score {su_a.score} outside [0, 1]"


@settings(max_examples=3, deadline=None)
@given(
    players=st.integers(min_value=2, max_value=4),
    base_seed=st.integers(min_value=0, max_value=3),
)
def test_calibration_is_byte_reproducible_and_never_underperforms(
    players: int, base_seed: int
) -> None:
    """LEARNING reproducibility: a whole recalibration run is byte-identical for its
    ``(players, base_seed)``; coordinate ascent from the default weights can never fall below the
    baseline train correlation; the held-out correlation is a real number over a disjoint split."""
    a = calibrate.calibrate(_CORPUS, players=players, base_seed=base_seed, corpus=_CORPUS_FP)
    b = calibrate.calibrate(_CORPUS, players=players, base_seed=base_seed, corpus=_CORPUS_FP)
    assert dumps(calibrate.calibration_to_json(a)) == dumps(calibrate.calibration_to_json(b))
    assert a.train_rho >= a.baseline_train_rho
    assert -1.0 <= a.holdout_rho <= 1.0
    assert set(a.train_ids).isdisjoint(a.holdout_ids)


@settings(max_examples=6, deadline=None)
@given(word=st.sampled_from(KB_WORDS), seed=st.integers(min_value=0, max_value=8))
def test_presentation_is_faithful_for_every_invented_puzzle(word: str, seed: int) -> None:
    """Presentation fidelity, lifted from the hand corpus to generated puzzles: the rendered rules
    are a bijection with the formal rep, the hints are a subset of the proof, and the whole render
    is ASCII -- the non-negotiable invariant holds for invented puzzles too."""
    puzzle = invent(word, seed=seed)
    cert = certify(puzzle)
    rl = presentation.rules_lines(puzzle)
    locs = {ln.strip() for ln in _block(rl, "Locations:") if ln.strip() != "(none)"}
    assert locs == set(puzzle.nodes), f"{word}@{seed}: rendered locations != formal nodes"
    svars = {ln.strip().split(":", 1)[0] for ln in _block(rl, "State variables:")}
    assert svars == {v.key for v in puzzle.variables}, f"{word}@{seed}: rendered vars != formal"
    names = {
        ln.strip()[:-1]
        for ln in _block(rl, "Actions:")
        if (len(ln) - len(ln.lstrip(" "))) == 2 and ln.rstrip().endswith(":")
    }
    assert names == {a.name for a in puzzle.actions}, f"{word}@{seed}: rendered actions != formal"
    assert set(presentation.hint_actions(puzzle, cert)) <= presentation._proof_action_set(
        puzzle, cert
    ), f"{word}@{seed}: a hint discloses an action outside the proof"
    text = "\n".join(presentation.render(puzzle, cert))
    assert all(ord(c) < 128 for c in text), f"{word}@{seed}: render is not ASCII"


@settings(max_examples=5, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=100),
    iterations=st.integers(min_value=0, max_value=2),
)
def test_archive_round_trips_through_json(seed: int, iterations: int) -> None:
    """Archive read-back is a true inverse: ``archive_from_json`` reconstructs an archive whose
    re-serialization is byte-identical to the original, preserving every cell's lineage and content
    address and the full rejection history -- the inverse LEARNING relies on."""
    original = mapelites.evolve([BY_NAME["move"]()], iterations, seed)
    j = mapelites.archive_to_json(original)
    back = mapelites.archive_from_json(j)
    assert dumps(mapelites.archive_to_json(back)) == dumps(j)
    assert set(back.cells) == set(original.cells)
    for niche, cell in original.cells.items():
        parsed = back.cells[niche]
        assert parsed.puzzle_digest == cell.puzzle_digest
        assert parsed.certificate_digest == cell.certificate_digest
        assert parsed.lineage == cell.lineage
    assert [(r.puzzle_digest, r.reason) for r in back.rejections] == [
        (r.puzzle_digest, r.reason) for r in original.rejections
    ]
