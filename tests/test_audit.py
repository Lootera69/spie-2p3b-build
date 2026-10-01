"""Path B auditor tests: independent cross-checks that the deterministic recognizer and the formal
solvers behind it are correct, and that the auditor *abstains* (never silently passes) on anything
it does not fully parse.

The load-bearing guarantees checked here:

* ``decide_categorical`` (the audit's occupancy engine) agrees with the *independently written*
  enumerator in :mod:`spie.questions.domains.syllogism` on all ten reference figures -- any
  disagreement is a hard failure, not a warning.
* ``decide_problem`` for propositional arguments agrees with a brute-force truth-table oracle.
* the recognizer fires only on completely-parsed formal arguments and returns ``None`` otherwise --
  an UNRECOGNIZED record is never counted as AGREE.
* a wrong authored answer is caught as DISAGREE (the auditor is not a rubber stamp).
* the rendered report is byte-reproducible across runs.
"""

from __future__ import annotations

import json
from itertools import product

from spie.audit import (
    CatStmt,
    Problem,
    audit_bank,
    audit_record,
    decide_categorical,
    decide_problem,
    recognize,
    render_json,
)
from spie.audit.bank import BankRecord
from spie.audit.recognize import classify_polarity
from spie.questions.domains import syllogism as _syl


def _rec(question: str, answer: str, *, rec_type: str = "multiple-choice",
         category: str = "logic", uid: str = "t.json#0") -> BankRecord:
    """A minimal BankRecord for recognizer tests; only the fields the recognizer reads matter."""
    return BankRecord(
        uid=uid, file="t.json", index=0, rec_type=rec_type, category=category,
        difficulty="easy", title="t", question=question, choices=(),
        correct_answer=answer, encoding="utf-8",
    )


# --- authored-answer polarity classification ---------------------------------------------------

def test_classify_polarity():
    for yes in ("Yes", "true", "Correct.", "Valid"):
        assert classify_polarity(yes) is True, yes
    for no in ("No", "false", "Incorrect", "invalid"):
        assert classify_polarity(no) is False, no
    for prose in ("The match is off", "Mia asks questions", ""):
        assert classify_polarity(prose) is None, prose


# --- recognizer: polarity frame (authored answer is a bare Yes/No) -----------------------------

def test_recognize_affirming_consequent_is_invalid_no():
    r = _rec("If it rains, the ground is wet. The ground is wet. "
             "Does it follow that it rains?", "No")
    prob = recognize(r)
    assert prob is not None and prob.family == "propositional"
    assert prob.answer_polarity is False
    assert decide_problem(prob).valid is False            # affirming the consequent is invalid
    v = audit_record(r)
    assert v is not None and v.status == "AGREE"           # invalid + author says "No" -> agree


def test_recognize_modus_ponens_is_valid_yes():
    r = _rec("If the switch is on, the light glows. The switch is on. "
             "Does it follow that the light glows?", "Yes", rec_type="true-false")
    prob = recognize(r)
    assert prob is not None and prob.family == "propositional"
    assert prob.answer_polarity is True
    assert decide_problem(prob).valid is True
    assert audit_record(r).status == "AGREE"


def test_recognize_e_conversion_is_valid():
    r = _rec('No cats are dogs. Does "No dogs are cats" follow?', "Yes")
    prob = recognize(r)
    assert prob is not None and prob.family == "categorical"
    assert decide_problem(prob).valid is True
    assert audit_record(r).status == "AGREE"


def test_wrong_authored_answer_is_flagged_disagree():
    # affirming the consequent, but the author answers "Yes" -> the auditor must DISAGREE.
    r = _rec("If it rains, the ground is wet. The ground is wet. "
             "Does it follow that it rains?", "Yes")
    v = audit_record(r)
    assert v is not None and v.status == "DISAGREE"
    assert v.formal_valid is False and v.answer_polarity is True


# --- recognizer: select-conclusion frame (the authored answer *is* the conclusion) ------------

def test_recognize_select_conclusion_barbara():
    r = _rec("All cats are mammals. All mammals are animals. What follows?",
             "All cats are animals.")
    prob = recognize(r)
    assert prob is not None and prob.family == "categorical"
    assert prob.frame == "categorical/select" and prob.answer_polarity is True
    assert decide_problem(prob).valid is True
    assert audit_record(r).status == "AGREE"


def test_select_conclusion_abstains_on_unparsed_quantified_premise():
    # A quantifier-bearing premise the parser cannot read must force abstention in strict mode,
    # never be silently dropped -- dropping a premise could flip validity and manufacture a verdict.
    r = _rec("All birds are singers. Every good melody lingers on. What follows?",
             "All birds are singers.")
    assert recognize(r) is None


# --- abstention: UNRECOGNIZED is never a silent pass -------------------------------------------

def test_open_world_prose_abstains():
    r = _rec("A man lives on the 10th floor and takes the elevator down every day. Why?",
             "He is too short to reach the button.")
    assert recognize(r) is None
    assert audit_record(r) is None                         # abstain -> not counted, never AGREE


def test_non_logic_category_abstains():
    r = _rec('No cats are dogs. Does "No dogs are cats" follow?', "Yes", category="trivia")
    assert recognize(r) is None


def test_abstain_cue_forces_abstention():
    r = _rec('No cats are dogs. Which is the odd one out?', "Yes")
    assert recognize(r) is None


# --- independent cross-check: decide_categorical vs the syllogism enumerator -------------------

_BIT_NAME = {_syl._S: "s", _syl._M: "m", _syl._P: "p"}


def _fig_to_cat(stmt: tuple) -> CatStmt:
    form, x, y = stmt
    return CatStmt(form, _BIT_NAME[x], _BIT_NAME[y])


def test_decide_categorical_agrees_with_syllogism_on_all_figures():
    # Two independently-written exhaustive occupancy enumerators must return the same verdict on
    # every reference figure. A disagreement is a hard failure (a broken correctness path).
    for name, p1, p2, concl in _syl._FIGURES:
        want, _ = _syl._validity(p1, p2, concl)
        got = decide_categorical(
            ("s", "m", "p"), (_fig_to_cat(p1), _fig_to_cat(p2)), _fig_to_cat(concl)
        ).valid
        assert got == want, f"{name}: occupancy={got} syllogism={want}"


def test_immediate_inference_conversions():
    x, y = "x", "y"
    # Boolean reading: E and I convert; A and O do not.
    assert decide_categorical((x, y), (CatStmt("E", x, y),), CatStmt("E", y, x)).valid is True
    assert decide_categorical((x, y), (CatStmt("I", x, y),), CatStmt("I", y, x)).valid is True
    assert decide_categorical((x, y), (CatStmt("A", x, y),), CatStmt("A", y, x)).valid is False
    assert decide_categorical((x, y), (CatStmt("O", x, y),), CatStmt("O", y, x)).valid is False


# --- independent cross-check: propositional decide vs a truth-table oracle ----------------------

def _truth_table_valid(prob: Problem) -> bool:
    """Brute-force validity: over every assignment to the atoms, every assignment satisfying all
    premises must satisfy the conclusion. Independent of Z3."""
    atoms = prob.atoms
    assert prob.prop_conclusion is not None
    ca, ctruth = prob.prop_conclusion
    for bits in product((False, True), repeat=len(atoms)):
        val = dict(zip(atoms, bits, strict=False))
        prem_ok = all((not val[a]) or val[b] for a, b in prob.conditionals)
        prem_ok = prem_ok and all(val[a] == t for a, t in prob.facts)
        if prem_ok and val[ca] != ctruth:
            return False
    return True


def _prop(conds, facts, concl) -> Problem:
    atoms: list[str] = []
    for a, b in conds:
        for k in (a, b):
            if k not in atoms:
                atoms.append(k)
    for a, _ in (*facts, (concl[0], None)):
        if a not in atoms:
            atoms.append(a)
    return Problem(family="propositional", answer_polarity=True, frame="test",
                   conditionals=tuple(conds), facts=tuple(facts),
                   prop_conclusion=concl, atoms=tuple(atoms))


_PROP_CASES = [
    ((("a", "b"),), (("a", True),), ("b", True)),                # modus ponens         valid
    ((("a", "b"),), (("b", True),), ("a", True)),                # affirming consequent invalid
    ((("a", "b"),), (("b", False),), ("a", False)),              # modus tollens        valid
    ((("a", "b"),), (("a", False),), ("b", False)),              # denying antecedent   invalid
    ((("a", "b"), ("b", "c")), (("a", True),), ("c", True)),     # chain                valid
    ((("a", "b"), ("b", "c")), (("a", True),), ("c", False)),    # chain, wrong sign    invalid
]


def test_propositional_decide_matches_truth_table():
    for conds, facts, concl in _PROP_CASES:
        prob = _prop(conds, facts, concl)
        assert decide_problem(prob).valid == _truth_table_valid(prob), (conds, facts, concl)


# --- report determinism / byte-reproducibility -------------------------------------------------

_BANK_A = [
    {"type": "multiple-choice", "category": "logic",
     "question": "All cats are mammals. All mammals are animals. What follows?",
     "correctAnswer": "All cats are animals."},
    {"type": "true-false", "category": "logic",
     "question": "If the switch is on, the light glows. The switch is on. "
                 "Does it follow that the light glows?",
     "correctAnswer": "Yes"},
]
_BANK_B = [
    {"type": "multiple-choice", "category": "riddle",
     "question": "Why did the man take the elevator down every day?",
     "correctAnswer": "He was too short to reach the top button."},
]


def test_report_is_byte_reproducible(tmp_path):
    (tmp_path / "batch-001.json").write_text(json.dumps(_BANK_A), encoding="utf-8")
    (tmp_path / "batch-002.json").write_text(json.dumps(_BANK_B), encoding="utf-8")
    first = render_json(audit_bank(str(tmp_path)))
    second = render_json(audit_bank(str(tmp_path)))
    assert first == second                                 # a pure function of the tree
    assert first.endswith("\n")
    doc = json.loads(first)
    assert doc["total"] == 3 and doc["recognized"] == 2    # two logic items; the riddle abstains
    assert doc["agree"] == 2 and doc["disagree"] == 0
    assert doc["disagreements"] == []


def test_report_records_a_disagreement(tmp_path):
    (tmp_path / "batch-001.json").write_text(json.dumps([
        {"type": "true-false", "category": "logic",
         "question": "If it rains, the ground is wet. The ground is wet. "
                     "Does it follow that it rains?",
         "correctAnswer": "Yes"},   # wrong: affirming the consequent
    ]), encoding="utf-8")
    report = audit_bank(str(tmp_path))
    assert report.disagree == 1 and report.agree == 0
    (v,) = report.disagreements
    assert v.formal_valid is False and v.answer_polarity is True





