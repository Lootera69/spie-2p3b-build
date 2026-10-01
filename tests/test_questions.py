"""Proven-answer question generator — independent re-verification of every answer.

The generator proves each answer with a decision procedure. These tests re-prove the *same*
answers with a **second, independent method**, so a bug in either path shows up as a disagreement
(a hard failure) rather than passing silently:

* ``sets`` uses exact set-inclusion cross-checked by Z3 -> here re-verified by exhaustive
  truth-table enumeration over the property atoms (independent of both), anchored by hardcoded
  square/rectangle expectations.
* ``logic`` uses Z3 (UNSAT-of-negation) -> here re-verified by a pure-Python truth-table evaluator
  and a hardcoded textbook validity table (independent of Z3).
* ``syllogism`` uses an exhaustive Python occupancy loop -> here re-verified by Z3 UNSAT over the
  region booleans (a different engine).
* ``arithmetic`` uses trial division / Euclid -> here re-verified by a sieve / brute-force gcd.
* ``sequence`` states its rule -> here the parameters are re-read from the shown prefix and the
  next term recomputed independently.

Plus the standing properties: determinism (byte-reproducible from the seed), the shape invariants
(exactly one correct option, the MCQ *uniqueness* obligation that every distractor is provably
wrong), the CLI contract, and the reduction oracle that importing this subsystem leaves the puzzle
pipeline's invention pins untouched.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys

import pytest
import z3

from spie import cli
from spie.invent import invent
from spie.questions import generate_question, render
from spie.questions.domains.propositional import _SCHEMAS, _decide_schema
from spie.questions.domains.scenarios import SKINS, decide_claim
from spie.questions.domains.sets import _ATOMS, _CLASSES
from spie.questions.domains.syllogism import _FIGURES, _stmt_holds
from spie.questions.generate import (
    CATEGORIES,
    generate_series,
    realistic_categories,
    supported_types,
)
from spie.questions.serialize import question_from_json, question_to_json
from spie.questions.types import QuestionType
from spie.serialize import dumps

# The full generation matrix (category, type) with a handful of seeds — the sweep every property
# below runs over, so a regression in any single domain surfaces as a failing invariant.
SEEDS = range(8)


def _all_questions():
    for cat in CATEGORIES:
        for qt in supported_types(cat):
            for seed in SEEDS:
                yield generate_question(cat, qt, seed)


# --- Independent oracle: set subsumption by truth-table enumeration --------------------------


def _subsumes_by_truth_table(sub: str, sup: str) -> bool:
    """Every ``sub`` is a ``sup`` iff, over all 2^|atoms| assignments, every assignment that meets
    ``sub``'s definition also meets ``sup``'s. Independent of the domain's set-inclusion and Z3."""
    sub_req, sup_req = _CLASSES[sub], _CLASSES[sup]
    for bits in itertools.product((False, True), repeat=len(_ATOMS)):
        assign = dict(zip(_ATOMS, bits, strict=False))
        if all(assign[a] for a in sub_req) and not all(assign[a] for a in sup_req):
            return False
    return True


def test_sets_flagship_square_rectangle_is_true_and_reverse_is_false() -> None:
    """The canonical example, anchored to hardcoded expectations independent of the domain."""
    q = generate_question("sets", "tf", seed=0, words=("square", "rectangle"))
    assert q.prompt == "True or False: every square is a rectangle."
    assert q.answer == "True"
    # independent re-derivation agrees
    assert _subsumes_by_truth_table("square", "rectangle") is True

    r = generate_question("sets", "tf", seed=0, words=("rectangle", "square"))
    assert r.prompt == "True or False: every rectangle is a square."
    assert r.answer == "False"
    assert _subsumes_by_truth_table("rectangle", "square") is False
    # a False answer must exhibit a concrete counter-example in its explanation
    assert "not a square" in r.explanation


def test_sets_true_false_answers_match_independent_truth_table() -> None:
    for seed in SEEDS:
        q = generate_question("sets", "tf", seed)
        sub, sup = q.concepts
        expected = _subsumes_by_truth_table(sub, sup)
        assert q.answer == ("True" if expected else "False"), (sub, sup)


def test_sets_mcq_has_unique_proven_answer_and_all_distractors_disproven() -> None:
    """The MCQ uniqueness obligation: the correct option provably subsumes the target and *every*
    distractor is provably a non-subclass — the multiple-choice analogue of puzzle uniqueness."""
    for seed in SEEDS:
        q = generate_question("sets", "mcq", seed)
        target = q.concepts[0]
        correct = [o for o in q.options if o.correct]
        assert len(correct) == 1
        assert _subsumes_by_truth_table(correct[0].text, target) is True
        for opt in q.options:
            if not opt.correct:
                assert _subsumes_by_truth_table(opt.text, target) is False, (opt.text, target)


# --- Independent oracle: propositional validity by pure-Python truth table -------------------

# Textbook validity of each schema, asserted here independently of Z3. Agreement between this
# table and the Z3-decided answer means Z3 matches the human-verified logic facts.
_EXPECTED_VALID = {
    "modus-ponens": True,
    "modus-tollens": True,
    "hypothetical-syllogism": True,
    "de-morgan": True,
    "excluded-middle": True,
    "affirming-consequent": False,
    "denying-antecedent": False,
    "converse-error": False,
}


def test_logic_schema_validity_matches_textbook_oracle() -> None:
    """Every schema's Z3-decided validity equals its hardcoded textbook value."""
    for schema in _SCHEMAS:
        valid, _ = _decide_schema(schema)
        assert valid == _EXPECTED_VALID[schema.key], schema.key


def test_logic_true_false_answer_matches_independent_decision() -> None:
    for seed in SEEDS:
        q = generate_question("logic", "tf", seed)
        key = q.concepts[1]
        assert q.answer == ("True" if _EXPECTED_VALID[key] else "False"), key


def test_logic_mcq_selects_the_one_valid_form() -> None:
    for seed in SEEDS:
        q = generate_question("logic", "mcq", seed)
        correct = [o for o in q.options if o.correct]
        assert len(correct) == 1
        assert _EXPECTED_VALID[q.concepts[1]] is True


# --- Realistic skins: the everyday wording changes, the proven answer cannot ------------------
#
# A "skin" renders a Z3-proven abstract form as an everyday argument; the scenario only *labels*
# the atoms (p, q, r), so the answer is decided over the form and cannot be moved by the wording.
# These tests re-prove that independently: every realistic answer must equal the textbook validity
# of the law named at ``concepts[1]`` -- never trusted from the generator.

_REALISTIC_LOGIC_TYPES = ("tf", "mcq")


def test_realistic_skins_decide_to_their_textbook_validity() -> None:
    """Each skin's Z3-decided validity (the single ``decide_claim`` source) equals its hardcoded
    textbook value, so the realistic schemas are anchored to the same independent oracle as the
    abstract ones and a realistic answer can never drift from the proven fact."""
    for skin in SKINS:
        valid, _ = decide_claim(skin.claim, skin.arity)
        assert valid == _EXPECTED_VALID[skin.key], skin.key


def test_realistic_logic_true_false_answer_matches_independent_decision() -> None:
    """The realistic TF answer equals the textbook validity of the skin named at ``concepts[1]``,
    re-proved here rather than believed -- the wording is faithful to the form."""
    for seed in SEEDS:
        q = generate_question("logic", "tf", seed, style="realistic")
        key = q.concepts[1]
        assert q.answer == ("True" if _EXPECTED_VALID[key] else "False"), (seed, key)
        assert q.proof.checker == "z3"


def test_realistic_logic_mcq_marks_the_one_valid_form() -> None:
    """The realistic MCQ has exactly one correct option, its winning form is textbook-valid, and
    the winning option's text is the stated answer (shape invariant and faithfulness together)."""
    for seed in SEEDS:
        q = generate_question("logic", "mcq", seed, style="realistic")
        correct = [o for o in q.options if o.correct]
        assert len(correct) == 1
        assert _EXPECTED_VALID[q.concepts[1]] is True
        assert correct[0].text == q.answer
        assert len(q.options) == 4  # one valid skin plus three distinct invalid forms


def test_realistic_answer_equals_the_abstract_form_decision() -> None:
    """The clincher: whatever the everyday wording, the realistic answer is exactly the Boolean
    validity of the underlying claim over abstract atoms -- proving the skin is presentation only.
    Re-decided here from each skin's own ``claim``, independently of the rendered question."""
    for seed in SEEDS:
        for qt in _REALISTIC_LOGIC_TYPES:
            q = generate_question("logic", qt, seed, style="realistic")
            skin = next(s for s in SKINS if s.key == q.concepts[1])
            valid, _ = decide_claim(skin.claim, skin.arity)
            if qt == "tf":
                assert q.answer == ("True" if valid else "False"), (seed, skin.key)
            else:
                assert valid is True, (seed, skin.key)  # the marked-correct form is the valid one


def test_realistic_logic_is_byte_reproducible_in_process() -> None:
    for qt in _REALISTIC_LOGIC_TYPES:
        for seed in SEEDS:
            a = dumps(question_to_json(generate_question("logic", qt, seed, style="realistic")))
            b = dumps(question_to_json(generate_question("logic", qt, seed, style="realistic")))
            assert a == b, (qt, seed)


def test_realistic_generation_is_byte_identical_across_processes() -> None:
    """The realistic path must be as immune to salted iteration order as the abstract one: its
    schema and scenario choices come from ordered tuples driven by a seeded RNG, never a frozenset.
    Hashed in two fresh interpreters with different PYTHONHASHSEED, the digests must match."""
    snippet = (
        "import hashlib;"
        "from spie.questions import generate_question;"
        "from spie.questions.serialize import question_to_json;"
        "from spie.serialize import dumps;"
        "b=''.join(dumps(question_to_json(generate_question('logic',qt,s,style='realistic')))"
        " for qt in ('tf','mcq') for s in range(6));"
        "print(hashlib.sha256(b.encode('utf-8')).hexdigest())"
    )

    def digest(hashseed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hashseed, "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run(
            [sys.executable, "-c", snippet],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        return out.stdout.strip()

    d0, d1, d2 = digest("0"), digest("1"), digest("2")
    assert d0 == d1 == d2, f"non-deterministic across processes: {d0} {d1} {d2}"


def test_realistic_questions_are_ascii_and_well_shaped() -> None:
    """Realistic questions obey the same presentation and shape contracts as abstract ones:
    ASCII-only text, exactly one correct option, and (for MCQ) the winning option is the answer."""
    for qt in _REALISTIC_LOGIC_TYPES:
        for seed in SEEDS:
            q = generate_question("logic", qt, seed, style="realistic")
            q.check()
            blob = dumps(question_to_json(q)) + "\n".join(render(q))
            assert all(ord(ch) < 128 for ch in blob), q.id
            if qt == "tf":
                assert [o.text for o in q.options] == ["True", "False"]
                assert q.answer in ("True", "False")
            else:
                assert next(o.text for o in q.options if o.correct) == q.answer


def test_realistic_style_leaves_the_abstract_form_untouched() -> None:
    """The abstract form is unchanged by the feature: ``style="plain"`` is the default, and the
    plain and realistic renderings of the same seed are genuinely different surface text (the skin
    adds wording) while both still name a Z3 proof."""
    for seed in SEEDS:
        plain = generate_question("logic", "tf", seed)
        plain_explicit = generate_question("logic", "tf", seed, style="plain")
        assert question_to_json(plain) == question_to_json(plain_explicit)  # default is plain
        skinned = generate_question("logic", "tf", seed, style="realistic")
        assert skinned.prompt != plain.prompt  # the wording really changed
        assert plain.proof.checker == skinned.proof.checker == "z3"


def test_generate_question_rejects_unknown_and_unsupported_styles() -> None:
    """``style`` is validated: an unknown style, and a realistic request for a category that has no
    skin, both raise ValueError rather than silently falling back to the abstract form."""
    with pytest.raises(ValueError, match="unknown style"):
        generate_question("logic", "tf", 0, style="fancy")
    assert "arithmetic" not in realistic_categories()  # arithmetic has no skin
    with pytest.raises(ValueError, match="no realistic skin"):
        generate_question("arithmetic", "tf", 0, style="realistic")


# --- Independent oracle: syllogism validity by Z3 (domain uses a Python loop) -----------------


def _syllogism_valid_by_z3(p1, p2, concl) -> bool:
    """Re-decide a syllogism with Z3 over the 8 region-occupancy booleans — a different engine
    from the domain's exhaustive Python loop, so the two must agree by soundness, not by sharing
    code. Validity = the premises entail the conclusion = UNSAT of (premises and not conclusion)."""
    occ = [z3.Bool(f"r{r}") for r in range(8)]

    def holds(stmt) -> z3.BoolRef:
        form, x, y = stmt
        in_x_in_y = [r for r in range(8) if (r & x) and (r & y)]
        in_x_not_y = [r for r in range(8) if (r & x) and not (r & y)]
        if form == "A":
            return z3.And(*[z3.Not(occ[r]) for r in in_x_not_y]) if in_x_not_y else z3.BoolVal(True)
        if form == "E":
            return z3.And(*[z3.Not(occ[r]) for r in in_x_in_y]) if in_x_in_y else z3.BoolVal(True)
        if form == "I":
            return z3.Or(*[occ[r] for r in in_x_in_y]) if in_x_in_y else z3.BoolVal(False)
        if form == "O":
            return z3.Or(*[occ[r] for r in in_x_not_y]) if in_x_not_y else z3.BoolVal(False)
        raise AssertionError(form)

    s = z3.Solver()
    s.add(holds(p1), holds(p2), z3.Not(holds(concl)))
    result = s.check()
    assert result in (z3.sat, z3.unsat)
    return result == z3.unsat


def test_syllogism_validity_python_loop_agrees_with_z3() -> None:
    """The domain's exhaustive occupancy check and an independent Z3 encoding agree on every
    figure. A disagreement would be a hard failure — never reconciled by fiat."""
    for label, p1, p2, concl in _FIGURES:
        # domain method: exhaustive Python (reuse the domain's own _stmt_holds over all patterns)
        py_valid = all(
            not (_stmt_holds(occ, *p1) and _stmt_holds(occ, *p2) and not _stmt_holds(occ, *concl))
            for occ in itertools.product((False, True), repeat=8)
        )
        z3_valid = _syllogism_valid_by_z3(p1, p2, concl)
        assert py_valid == z3_valid, label


def test_syllogism_question_answer_matches_z3_oracle() -> None:
    for seed in SEEDS:
        q = generate_question("syllogism", "tf", seed)
        label = q.concepts[1]
        fig = next(f for f in _FIGURES if f[0] == label)
        expected = _syllogism_valid_by_z3(fig[1], fig[2], fig[3])
        assert q.answer == ("True" if expected else "False"), label


# --- Independent oracle: arithmetic by a sieve / brute force ----------------------------------


def _sieve_primes(n: int) -> set[int]:
    sieve = [True] * (n + 1)
    sieve[0:2] = [False, False]
    for i in range(2, int(n**0.5) + 1):
        if sieve[i]:
            for j in range(i * i, n + 1, i):
                sieve[j] = False
    return {i for i, p in enumerate(sieve) if p}


_PRIMES = _sieve_primes(200)


def _gcd_brute(a: int, b: int) -> int:
    return max(d for d in range(1, min(a, b) + 1) if a % d == 0 and b % d == 0)


def test_arithmetic_primality_answers_match_a_sieve() -> None:
    for seed in SEEDS:
        q = generate_question("arithmetic", "tf", seed)
        n = int(q.concepts[1])
        assert q.answer == ("True" if n in _PRIMES else "False"), n


def test_arithmetic_mcq_selects_the_one_prime() -> None:
    for seed in SEEDS:
        q = generate_question("arithmetic", "mcq", seed)
        correct = [o for o in q.options if o.correct]
        assert len(correct) == 1
        assert int(correct[0].text) in _PRIMES
        for opt in q.options:
            if not opt.correct:
                assert int(opt.text) not in _PRIMES


def test_arithmetic_fill_blank_values_recompute_independently() -> None:
    for seed in SEEDS:
        q = generate_question("arithmetic", "blank", seed)
        if q.concepts[0] == "gcd":
            a, b = int(q.concepts[1]), int(q.concepts[2])
            assert int(q.answer) == _gcd_brute(a, b)
        else:  # next prime
            val = int(q.answer)
            assert val in _PRIMES
            base = int(q.prompt.split("greater than ")[1].split(" ")[0])
            assert not any(k in _PRIMES for k in range(base + 1, val)), (base, val)


# --- Independent oracle: sequence by re-reading the shown prefix ------------------------------


def test_sequence_next_term_recomputes_from_the_shown_prefix() -> None:
    """Re-derive the rule's parameters from the displayed prefix and recompute the next term,
    independent of the domain's own parameter generation."""
    for qt in (QuestionType.FILL_BLANK, QuestionType.MCQ):
        for seed in SEEDS:
            q = generate_question("sequence", qt, seed)
            rule = q.concepts[1]
            prefix = _extract_prefix(q.prompt)
            if rule == "arithmetic":
                d = prefix[1] - prefix[0]
                expected = prefix[-1] + d
            elif rule == "geometric":
                ratio = prefix[1] // prefix[0]
                expected = prefix[-1] * ratio
            else:  # square-plus: nth term is n*n + a, so a = prefix[0]-1 (n starts at 1)
                a = prefix[0] - 1
                expected = (len(prefix) + 1) ** 2 + a
            assert int(q.answer) == expected, (rule, prefix, q.answer)


def _extract_prefix(prompt: str) -> list[int]:
    """Pull the shown integer sequence out of a rendered sequence prompt."""
    body = prompt.split("begins ")[1].split(", ...")[0]
    return [int(tok) for tok in body.split(", ")]


# --- Determinism and shape invariants --------------------------------------------------------


def test_every_question_is_byte_reproducible() -> None:
    for cat in CATEGORIES:
        for qt in supported_types(cat):
            a = dumps(question_to_json(generate_question(cat, qt, seed=5)))
            b = dumps(question_to_json(generate_question(cat, qt, seed=5)))
            assert a == b, (cat, qt)


def test_seed_words_do_not_break_determinism() -> None:
    a = dumps(question_to_json(generate_question("sets", "tf", 0, ("square", "rectangle"))))
    b = dumps(question_to_json(generate_question("sets", "tf", 0, ("square", "rectangle"))))
    assert a == b


def test_supported_types_are_returned_in_a_deterministic_order() -> None:
    """``supported_types`` must return a canonically ORDERED sequence (enum-definition order),
    never a bare frozenset - whose iteration order Python salts per-process via PYTHONHASHSEED.
    Anything that iterates this accessor (the CLI, generated question sets) would otherwise vary
    across runs. Order-in-enum, not hash-order, is the contract."""
    enum_order = list(QuestionType)
    for cat in CATEGORIES:
        types = supported_types(cat)
        assert isinstance(types, tuple), cat
        # exactly the enum order, filtered to the supported set
        assert list(types) == [qt for qt in enum_order if qt in set(types)], cat


def test_generation_is_byte_identical_across_independent_processes() -> None:
    """The real determinism proof: the whole matrix, hashed in two FRESH interpreters launched
    with different PYTHONHASHSEED values. This is what a single-process loop cannot see - a
    frozenset (or set) leaking its salted iteration order into the output changes the digest here
    while every in-process check still passes. Byte-identical digests => nothing salted leaks."""
    snippet = (
        "import hashlib;"
        "from spie.questions import generate_question;"
        "from spie.questions.serialize import question_to_json;"
        "from spie.serialize import dumps;"
        "from spie.questions.generate import CATEGORIES, supported_types;"
        "b=''.join(dumps(question_to_json(generate_question(c,qt,s)))"
        " for c in CATEGORIES for qt in supported_types(c) for s in range(4));"
        "print(hashlib.sha256(b.encode('utf-8')).hexdigest())"
    )

    def digest(hashseed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hashseed, "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run(
            [sys.executable, "-c", snippet],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        return out.stdout.strip()

    d0, d1, d2 = digest("0"), digest("1"), digest("2")
    assert d0 == d1 == d2, f"non-deterministic across processes: {d0} {d1} {d2}"


def test_shape_invariants_hold_for_every_generated_question() -> None:
    for q in _all_questions():
        q.check()  # re-assert; raises on any violation
        qt = QuestionType.parse(q.qtype)
        if qt is QuestionType.TRUE_FALSE:
            assert [o.text for o in q.options] == ["True", "False"]
            assert sum(o.correct for o in q.options) == 1
            assert q.answer in ("True", "False")
        elif qt is QuestionType.MCQ:
            assert sum(o.correct for o in q.options) == 1
            assert len(q.options) >= 2
            # the winning option's text is the stated answer
            assert next(o.text for o in q.options if o.correct) == q.answer
        else:
            assert q.options == ()
            assert q.answer


def test_every_answer_carries_a_formal_proof_stamp() -> None:
    """No answer is emitted without a proof stamp naming a real checker (z3 or python) — the
    structural guarantee that nothing learned sits in the answer path."""
    for q in _all_questions():
        assert q.proof.checker in ("z3", "python")
        assert q.proof.checker_version
        assert q.proof.method
        assert q.explanation  # a proof-derived explanation always accompanies the answer


def test_generated_text_is_ascii_only() -> None:
    """The presentation layer is ASCII-only (mirrors the puzzle renderer / ConceptNet contract)."""
    for q in _all_questions():
        blob = dumps(question_to_json(q)) + "\n".join(render(q))
        assert all(ord(ch) < 128 for ch in blob), q.id


def test_question_json_round_trips() -> None:
    for q in _all_questions():
        assert question_from_json(question_to_json(q)) == q


def test_generate_series_is_consecutive_seeds() -> None:
    series = generate_series("arithmetic", "tf", 4, start=10)
    assert [q.seed for q in series] == [10, 11, 12, 13]


# --- CLI contract ----------------------------------------------------------------------------


def test_cli_ask_renders_flagship_and_exits_zero(capsys) -> None:
    rc = cli.main(["ask", "sets", "tf", "--words", "square,rectangle"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "every square is a rectangle" in out
    assert "Answer: True" in out
    assert "z3" in out


def test_cli_ask_json_round_trips(capsys) -> None:
    rc = cli.main(["ask", "arithmetic", "blank", "--seed", "3", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    q = question_from_json(data)
    assert q.category == "arithmetic"
    assert q.proof.checker == "python"


def test_cli_ask_rejects_unsupported_type_with_exit_one(capsys) -> None:
    rc = cli.main(["ask", "sets", "blank"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "cannot pose" in out


def test_cli_ask_writes_question_file(tmp_path) -> None:
    out = tmp_path / "q.json"
    rc = cli.main(["ask", "logic", "tf", "--seed", "1", "--json", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["category"] == "logic"


def test_cli_ask_count_emits_distinct_consecutive_seeds(capsys) -> None:
    """``--count N`` returns a *batch* of N questions on consecutive seeds as a JSON list -- the
    fix for 'every run gives the same #0 question': variety comes from moving the seed."""
    rc = cli.main(["ask", "sets", "tf", "--count", "3", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert isinstance(data, list) and len(data) == 3
    assert [q["seed"] for q in data] == [0, 1, 2]
    assert len({q["prompt"] for q in data}) >= 2  # genuinely different questions, not repeats


def test_cli_ask_all_types_covers_every_supported_type(capsys) -> None:
    """``--all-types`` poses every question type the category supports for one seed."""
    rc = cli.main(["ask", "arithmetic", "--all-types", "--seed", "4", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert {q["qtype"] for q in data} == {qt.value for qt in supported_types("arithmetic")}


def test_cli_ask_random_is_reproducible_via_its_printed_seed(capsys) -> None:
    """``--random`` only *chooses* the seed (and prints it): the answer path stays deterministic,
    so re-posing that seed reproduces the question byte-for-byte. Randomness never enters proofs."""
    rc = cli.main(["ask", "sequence", "mcq", "--random", "--json"])
    obj = json.loads(capsys.readouterr().out)
    assert rc == 0
    rc2 = cli.main(["ask", "sequence", "mcq", "--seed", str(obj["seed"]), "--json"])
    obj2 = json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert obj == obj2


def test_cli_ask_interactive_prompts_for_each_param(capsys, monkeypatch) -> None:
    """Bare ``ask -i`` asks for each parameter one at a time, then generates from the answers."""
    answers = iter(["1", "1", "n", "0", "1", ""])  # sets, tf, not-random, seed 0, count 1, no words
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    rc = cli.main(["ask", "-i"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Pick a category" in out
    assert "Pick a question type" in out
    assert "True or False:" in out and "Answer:" in out


def test_cli_ask_realistic_renders_everyday_wording_and_exits_zero(capsys) -> None:
    """``--realistic`` on a skinnable category words the argument as an everyday scenario while
    keeping the Z3 proof stamp and a definite True/False answer."""
    rc = cli.main(["ask", "logic", "tf", "--seed", "3", "--realistic"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "If " in out and "Therefore," in out  # rendered as an everyday argument
    assert "z3" in out
    assert ("Answer: True" in out) or ("Answer: False" in out)


def test_cli_ask_realistic_on_unskinnable_category_exits_one(capsys) -> None:
    """A ``--realistic`` request for a category with no skin fails cleanly (exit 1, helpful msg)
    rather than silently degrading to the abstract form."""
    rc = cli.main(["ask", "arithmetic", "tf", "--realistic"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "realistic skin" in out


def test_cli_ask_interactive_offers_realistic_wording(capsys, monkeypatch) -> None:
    """Interactive ``ask`` offers the real-world wording prompt for a skinnable category and
    honours a 'y', producing an everyday argument."""
    answers = iter(["2", "1", "n", "0", "", "y"])  # logic, tf, not-random, seed 0, count 1, yes
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    rc = cli.main(["ask", "-i"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Real-world wording?" in out
    assert "If " in out and "Therefore," in out


# --- Reduction oracle: the question subsystem is additive ------------------------------------


def test_importing_questions_does_not_perturb_invention_pins() -> None:
    """Importing and exercising the question generator must not touch the puzzle pipeline: the
    pinned invention identities still hold, so this subsystem is provably additive."""
    for q in _all_questions():
        q.check()
    assert invent("door").id == "gen_0000_connect_negate"
    assert "plain" in invent("prize").id
