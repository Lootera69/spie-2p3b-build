"""The exhaustive certify gate — the thesis applied to the vocabulary itself.

A word enters the shipped artifact only if it has been *proven*, here, to invent a puzzle the
formal solvers accept. For each candidate and each seed ``0 .. seeds-1``:

``invent_traced`` -> ``validate`` (must be finding-free) -> ``certify`` (must be solvable, unique
and conformant) -> ``verify`` (no gate may FAIL) -> ``presentation.render`` (must be ASCII and a
bijection with the formal representation).

That is a strict superset of what the shipped runtime tests assert, run exhaustively rather than
sampled. Soundness of the expanded vocabulary is therefore established *by construction* at build
time; ``tests/test_conceptnet_data.py`` then proves the shipped artifact is byte-identical to the
gated one, which is what lets the run-time sweeps stay scoped to the curated core.

Two mechanisms make an exhaustive gate affordable:

* **A dependency memo.** ``invent(word)`` reads exactly the relations of the concepts within one
  hop of ``word`` and the affordances of those within two (``expand`` is a depth-2 walk and
  ``afford`` reads every reached concept's tags). :func:`dependency_key` captures precisely that
  sub-KB, so across the prune/gate fixpoint a word is re-gated only when its own neighbourhood
  actually changed.
* **Process-level parallelism.** Each word's verdict is independent given the trial KB, so the
  work fans out over a process pool and the results are re-sorted by word — the verdicts are a
  function of the vocabulary, never of completion order.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor

import z3

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if _SRC not in sys.path:  # the tool runs from the repo root; workers re-import this module
    sys.path.insert(0, _SRC)

from spie import concepts, presentation  # noqa: E402
from spie.certificate import certify  # noqa: E402
from spie.invent import invent_traced  # noqa: E402
from spie.validate import validate  # noqa: E402
from spie.verify import GateStatus, verify  # noqa: E402

# name -> (((relation, (target, ...)), ...), (affordance, ...)) — the merged KB as plain data.
KbView = Mapping[str, tuple[tuple[tuple[str, tuple[str, ...]], ...], tuple[str, ...]]]

# (passed, reason) — ``reason`` is a short stable slug so the build can histogram the drops.
Verdict = tuple[bool, str]

# What ``gate_word`` proves. Bump this on **any** change to the proof stack below — a stored
# verdict from an older, weaker gate must never be reused as if this gate had accepted the word.
# ``tools.conceptnet_build.verdicts`` writes it into its header and discards mismatches.
# v2: Z3 checks are now bounded by a deterministic ``rlimit`` (see ``configure_z3``); a v1 verdict
# was produced unbounded and could have hung, so it must not be reused.
GATE_VERSION = "2"


def configure_z3(rlimit: int) -> None:
    """Bound every Z3 ``check()`` by a *deterministic* resource limit, not wall-clock time.

    A handful of generated puzzles have a solve/uniqueness query whose default Z3 tactics do not
    terminate in any practical time (observed: one word's uniqueness check ran unboundedly, stalling
    the whole build). ``rlimit`` counts Z3's internal work units, so the query instead returns
    ``unknown`` after a *machine-independent* amount of work — the artifact stays byte-reproducible
    (unlike a wall-clock timeout, whose cutoff depends on the machine). Soundness is unaffected:
    a bailed ``unknown`` is consumed as "not sat", and the three-way cross-check (Z3 vs explicit
    search vs ASP) fails the gate whenever the bail makes Z3 disagree — a bailed word is dropped,
    never admitted on an unproven claim. Set once per process; ``z3.set_param`` is a global default
    that every later ``z3.Solver()`` inherits."""
    if rlimit > 0:
        z3.set_param("rlimit", rlimit)


def curated_view() -> dict[str, tuple[tuple[tuple[str, tuple[str, ...]], ...], tuple[str, ...]]]:
    """The curated core as plain data, so keys and trial merges never touch ``Concept`` objects."""
    view = {}
    for concept in concepts._CONCEPTS:
        relations = tuple(
            (relation.value, tuple(sorted(targets)))
            for relation, targets in sorted(concept.relations.items(), key=lambda kv: kv[0].value)
        )
        view[concept.name] = (relations, tuple(a.value for a in concept.affordances))
    return view


def merged_view(records: Sequence[tuple]) -> dict[str, tuple]:
    """The trial KB as plain data, curated first — the same precedence ``_merge_kb`` applies."""
    view = curated_view()
    for name, relations, affordances in records:
        view.setdefault(name, (relations, affordances))
    return view


def dependency_key(word: str, view: KbView) -> str:
    """Everything ``invent(word, ...)`` can read: relations within one hop, affordances within two.

    Anything outside this sub-KB is unreachable from ``word``'s depth-2 expansion, so two trial
    vocabularies agreeing on this key must produce byte-identical puzzles for ``word``."""
    near = {word}  # distance <= 1: relations *and* affordances are read
    for _relation, targets in view.get(word, ((), ()))[0]:
        near.update(targets)
    far = set(near)  # distance <= 2: affordances are read
    for name in sorted(near):
        for _relation, targets in view.get(name, ((), ()))[0]:
            far.update(targets)
    parts = [
        (name, view.get(name, ((), ()))[0] if name in near else (), view.get(name, ((), ()))[1])
        for name in sorted(far)
    ]
    return repr(parts)


def install_trial_kb(records: Sequence[tuple]) -> None:
    """Install a trial vocabulary by rebuilding ``spie.concepts.KB`` in place.

    Every downstream stage reads that module global live (no module imports ``KB`` by name), so
    an in-place rebuild is a complete vocabulary swap. Curated concepts are re-seated first and
    records only ``setdefault``-ed, reproducing the shipped merge exactly — including the fact
    that a record can never shadow a curated concept."""
    concepts.KB.clear()
    concepts.KB.update({c.name: c for c in concepts._CONCEPTS})
    for record in records:
        concepts.KB.setdefault(record[0], concepts._record_to_concept(record))


def _block(lines: list[str], header: str) -> list[str]:
    """The indented child lines under a zero-indent ``header`` (mirrors the presentation tests)."""
    if header not in lines:
        return []
    index = lines.index(header) + 1
    out: list[str] = []
    while index < len(lines) and lines[index].startswith(" "):
        out.append(lines[index])
        index += 1
    return out


def _bijection_failure(puzzle) -> str:
    """``""`` when the rendered rules name exactly the puzzle's formal symbols, else which set."""
    rules = presentation.rules_lines(puzzle)
    locations = {ln.strip() for ln in _block(rules, "Locations:") if ln.strip() != "(none)"}
    if locations != set(puzzle.nodes):
        return "nodes"
    variables = {ln.strip().split(":", 1)[0] for ln in _block(rules, "State variables:")}
    if variables != {v.key for v in puzzle.variables}:
        return "variables"
    actions = {
        ln.strip()[:-1]
        for ln in _block(rules, "Actions:")
        if (len(ln) - len(ln.lstrip(" "))) == 2 and ln.rstrip().endswith(":")
    }
    return "" if actions == {a.name for a in puzzle.actions} else "actions"


def gate_word(word: str, seeds: int) -> Verdict:
    """Run the full proof stack for one word at every seed; the first failure decides."""
    try:
        for seed in range(seeds):
            puzzle, provenance = invent_traced(word, seed=seed)
            findings = validate(puzzle)
            if findings:
                return False, f"validate:{findings[0].rule}"
            cert = certify(puzzle)
            if not cert.solvable:
                return False, "certify:unsolvable"
            if not cert.unique:
                return False, "certify:not-unique"
            if not cert.conformance_ok:
                return False, "certify:nonconformant"
            report = verify(puzzle, provenance)
            failed = [g.name for g in report.gates if g.status is GateStatus.FAIL]
            if failed:
                return False, f"verify:{sorted(failed)[0]}"
            text = "\n".join(presentation.render(puzzle, cert))
            if any(ord(ch) >= 128 for ch in text):
                return False, "present:non-ascii"
            mismatch = _bijection_failure(puzzle)
            if mismatch:
                return False, f"present:{mismatch}"
    except Exception as exc:  # a word that crashes the pipeline is simply not admitted
        return False, f"error:{type(exc).__name__}"
    return True, ""


def _init_worker(records: Sequence[tuple], rlimit: int) -> None:
    configure_z3(rlimit)
    install_trial_kb(records)


def _gate_task(args: tuple[str, int]) -> tuple[str, bool, str]:
    word, seeds = args
    passed, reason = gate_word(word, seeds)
    return word, passed, reason


def gate_words(
    records: Sequence[tuple],
    words: Collection[str],
    *,
    seeds: int,
    jobs: int,
    z3_rlimit: int = 0,
    progress_every: int = 100,
    on_verdict: Callable[[str, Verdict], None] | None = None,
) -> dict[str, Verdict]:
    """Gate every word in ``words`` against the trial vocabulary ``records``.

    Results are collected into a dict keyed by word and the caller consumes them in sorted order,
    so process scheduling cannot influence the outcome.

    ``z3_rlimit`` bounds every Z3 check deterministically (see :func:`configure_z3`) so no word can
    stall the build on a non-terminating solve; it is applied in this process (``jobs <= 1``) and
    in every worker's initializer.

    ``on_verdict`` is invoked for each verdict *as it arrives*, which is how the durable verdict
    log survives a kill mid-round. It therefore fires in completion order — it must be used only
    for write-through side effects, never to derive anything order-sensitive."""
    todo = sorted(words)
    if not todo:
        return {}
    verdicts: dict[str, Verdict] = {}
    if jobs <= 1:
        configure_z3(z3_rlimit)
        install_trial_kb(records)
        for done, word in enumerate(todo, start=1):
            verdicts[word] = gate_word(word, seeds)
            if on_verdict is not None:
                on_verdict(word, verdicts[word])
            if progress_every and done % progress_every == 0:
                print(f"    gated {done:,}/{len(todo):,}", file=sys.stderr)
        return verdicts
    with ProcessPoolExecutor(
        max_workers=jobs, initializer=_init_worker, initargs=(tuple(records), z3_rlimit)
    ) as pool:
        tasks = [(word, seeds) for word in todo]
        for done, (word, passed, reason) in enumerate(pool.map(_gate_task, tasks, chunksize=1), 1):
            verdicts[word] = (passed, reason)
            if on_verdict is not None:
                on_verdict(word, verdicts[word])
            if progress_every and done % progress_every == 0:
                print(f"    gated {done:,}/{len(todo):,}", file=sys.stderr)
    return verdicts


__all__ = [
    "GATE_VERSION",
    "KbView",
    "Verdict",
    "curated_view",
    "merged_view",
    "dependency_key",
    "install_trial_kb",
    "gate_word",
    "gate_words",
]
