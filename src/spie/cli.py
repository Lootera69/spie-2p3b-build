"""Command-line entry point: ``python -m spie.cli <command> ...``.

Commands wrap the library end to end so the whole proof loop is reachable from a shell:

    gen                     (re)write the hand-encoded examples to examples/*.json
    validate  PUZZLE        static checks + quality score
    solve     PUZZLE        find a minimal solution, print the trace (a branching plan when hidden)
    unique    PUZZLE        report the uniqueness verdict
    conform   PUZZLE        replay the solver trace through the interpreter (all worlds when hidden)
    crosscheck PUZZLE       run all three solvers, report their agreement (gate G2)
    verify    PUZZLE        run every verification gate, print the report
    quality   PUZZLE        print the machine quality vector as canonical JSON
    cert      PUZZLE        emit the full certificate as canonical JSON
    present   PUZZLE        render rules, hints, answer, certificate as plain text
    suite     [--dir DIR]   certify + verify every puzzle in a directory, print a summary
    invent    WORD          run the concept→mechanic pipeline, certify + print the puzzle
    evolve    [--seeds ...]  invent from seed words, run a bounded MAP-Elites search
    archive show PATH       summarize a saved archive as a niche table
    calibrate [--dir DIR]   fit difficulty weights to synthetic telemetry, report Gate G5
    ask CATEGORY QTYPE      generate one proven-answer question (formal categories)
    audit-bank [--path DIR] formally re-decide the recognizable subset of the authored bank (Path B)

Commands that solve (``solve``/``unique``/``conform``/``crosscheck``) branch on
``puzzle.initial_belief``: a puzzle that declares hidden initial state is solved by the
belief-space epistemic solver (and cross-checked by the symbolic multi-world one), so ``solve``
prints a contingent branching plan and ``suite`` reports each puzzle's ``|B0|``.

Output is plain text (or canonical JSON for ``cert``/``quality``), and every command's exit
code is 0 on success and 1 when the puzzle is unsolvable, non-conformant, has validation
findings, fails a verification gate, or the solvers disagree — so the CLI is usable as a
check in scripts.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

from . import calibrate, epistemic, presentation
from .audit import DEFAULT_BANK, audit_bank, render_json, render_text
from .certificate import certify
from .conformance import check_conformance, check_plan_conformance
from .context_policy import ContextualPolicy
from .crosscheck import cross_solve, epistemic_cross_solve
from .decision import FrozenProposer
from .fingerprint import corpus_fingerprints
from .invent import evolve as invent_evolve
from .invent import invent_traced
from .mapelites import archive_to_json
from .quality import descriptors, quality_to_json
from .questions import render as render_question
from .questions.generate import (
    CATEGORIES,
    generate_question,
    realistic_categories,
    supported_types,
)
from .questions.serialize import question_to_json
from .report import build_report
from .results import Plan
from .serialize import certificate_to_json, dumps, load_puzzle, puzzle_to_json
from .solver import check_uniqueness, solve
from .steering import SteeringPolicy
from .validate import validate
from .verify import verify

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "examples")


def _format_plan_lines(plan: Plan, prefix: str = "  ") -> list[str]:
    """Render a contingent plan as an indented branching trace: each action on its own line,
    each sensing outcome shown as the observed valuation that selects the sub-plan beneath it.
    A leaf marks a belief in which the goal is already guaranteed on every possible world."""
    if plan.is_leaf:
        return [f"{prefix}goal reached"]
    lines = [f"{prefix}{plan.action}"]
    for valuation, child in plan.branches:
        lines.append(f"{prefix}  observe ({', '.join(str(v) for v in valuation)}):")
        lines.extend(_format_plan_lines(child, prefix + "    "))
    return lines


def _cmd_gen(args: argparse.Namespace) -> int:
    from .examples_src import write_examples

    written = write_examples(args.dir)
    for path in written:
        print(f"wrote {path}")
    print(f"{len(written)} example(s) written to {args.dir}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    report = build_report(puzzle.id, validate(puzzle))
    print(f"{puzzle.id}: score {report.score}/100, {len(report.findings)} finding(s)")
    for f in report.findings:
        print(f"  [{f.rule}] {f.message}")
    return 0 if report.ok else 1


def _cmd_solve(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    if puzzle.initial_belief:
        strong = epistemic.solve_strong(puzzle)
        if not strong.solvable or strong.plan is None:
            print(
                f"{puzzle.id}: NOT strongly solvable within horizon "
                f"{puzzle.objective.max_horizon}"
            )
            return 1
        worlds = len(epistemic.build_initial_belief(puzzle))
        pc = check_plan_conformance(puzzle, strong.plan)
        print(
            f"{puzzle.id}: strongly solved, worst-case depth {strong.depth} "
            f"over {worlds} world(s)"
        )
        for line in _format_plan_lines(strong.plan):
            print(line)
        ok_msg = "OK (all worlds reach goal, uniform)"
        print(f"conformance: {ok_msg if pc.ok else 'FAILED — ' + pc.detail}")
        return 0 if pc.ok else 1
    solution = solve(puzzle)
    if not solution.solvable:
        print(f"{puzzle.id}: UNSOLVABLE within horizon {puzzle.objective.max_horizon}")
        return 1
    conf = check_conformance(puzzle, solution)
    print(f"{puzzle.id}: solved at horizon {solution.horizon} ({len(solution.trace)} step(s))")
    for i, action in enumerate(solution.trace):
        print(f"  {i}: {action}")
    print(f"conformance: {'OK' if conf.ok else 'FAILED — ' + conf.detail}")
    return 0 if conf.ok else 1


def _cmd_unique(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    if puzzle.initial_belief:
        strong = epistemic.solve_strong(puzzle)
        if not strong.solvable:
            print(f"{puzzle.id}: NOT strongly solvable — uniqueness not applicable")
            return 1
        verdict = epistemic.check_uniqueness(puzzle)
        print(f"{puzzle.id}: unique = {str(verdict.unique).lower()} (by {verdict.equivalence})")
        return 0
    solution = solve(puzzle)
    if not solution.solvable:
        print(f"{puzzle.id}: UNSOLVABLE — uniqueness not applicable")
        return 1
    verdict = check_uniqueness(puzzle, solution)
    print(f"{puzzle.id}: unique = {str(verdict.unique).lower()} (by {verdict.equivalence})")
    if verdict.witness is not None:
        print("  second solution exists:")
        for i, action in enumerate(verdict.witness):
            print(f"    {i}: {action}")
    return 0


def _cmd_conform(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    if puzzle.initial_belief:
        pc = check_plan_conformance(puzzle, epistemic.canonical_plan(puzzle))
        print(f"{puzzle.id}: plan conformance {'OK' if pc.ok else 'FAILED'} — {pc.detail}")
        print(
            f"  reached goal on all worlds: {str(pc.reached_goal_all).lower()}; "
            f"uniform (no clairvoyance): {str(pc.uniform).lower()}"
        )
        for r in pc.world_replays:
            status = "ok" if r.ok else "FAIL"
            print(f"  [{status:4}] world {r.world} -> {', '.join(r.trace)}")
        return 0 if pc.ok else 1
    solution = solve(puzzle)
    conf = check_conformance(puzzle, solution)
    print(f"{puzzle.id}: conformance {'OK' if conf.ok else 'FAILED'} — {conf.detail}")
    return 0 if conf.ok else 1


def _cmd_crosscheck(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    if puzzle.initial_belief:
        cross = epistemic_cross_solve(puzzle)
        print(
            f"{puzzle.id}: agree = {str(cross.agree).lower()} "
            f"(|B0| = {cross.world_count} world(s))"
        )
        for ev in cross.evidence:
            print(
                f"  {ev.name} v{ev.version}: solvable={str(ev.solvable).lower()} "
                f"depth={ev.depth} unique={str(ev.unique).lower()}"
            )
        for d in cross.discrepancies:
            print(f"  discrepancy: {d}")
        return 0 if cross.agree else 1
    cross = cross_solve(puzzle)
    print(f"{puzzle.id}: agree = {str(cross.agree).lower()}")
    for ev in cross.evidence:
        print(
            f"  {ev.name} v{ev.version}: solvable={str(ev.solvable).lower()} "
            f"horizon={ev.horizon} cost={ev.cost} unique={str(ev.unique).lower()}"
        )
    for d in cross.discrepancies:
        print(f"  discrepancy: {d}")
    return 0 if cross.agree else 1


def _cmd_verify(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    report = verify(puzzle)
    print(f"{puzzle.id}: {'OK' if report.ok else 'FAILED'}")
    for g in report.gates:
        print(f"  [{g.status.value.upper():4}] {g.name}: {g.detail}")
        for f in g.findings:
            print(f"        - {f.rule}: {f.message}")
    return 0 if report.ok else 1


def _cmd_quality(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    q = descriptors(puzzle)
    sys.stdout.write(dumps(quality_to_json(q)))
    return 0


def _cmd_cert(args: argparse.Namespace) -> int:
    puzzle = load_puzzle(args.puzzle)
    cert = certify(puzzle)
    text = dumps(certificate_to_json(cert))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote certificate to {args.out}")
    else:
        sys.stdout.write(text)
    return 0 if (cert.solvable and cert.conformance_ok) else 1


def _cmd_present(args: argparse.Namespace) -> int:
    """Render a puzzle's rules, proof-derived hint ladder, worked answer, and machine-readable
    certificate as one plain-text document (see :mod:`spie.presentation`). Exit code mirrors
    ``cert``: 0 when the puzzle is solvable and its certified solution is conformant, else 1."""
    puzzle = load_puzzle(args.puzzle)
    cert = certify(puzzle)
    text = "\n".join(presentation.render(puzzle, cert)) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote presentation to {args.out}")
    else:
        sys.stdout.write(text)
    return 0 if (cert.solvable and cert.conformance_ok) else 1


def _cmd_suite(args: argparse.Namespace) -> int:
    paths = sorted(glob.glob(os.path.join(args.dir, "*.json")))
    if not paths:
        print(f"no puzzles found in {args.dir} (run 'gen' first)")
        return 1
    out_dir = args.out
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    puzzles = [load_puzzle(path) for path in paths]
    corpus = corpus_fingerprints(puzzles)

    header = (
        f"{'puzzle':<22} {'solved':>6} {'H':>3} {'|B0|':>4} {'unique':>6} {'conform':>7} "
        f"{'gates':>5} {'band':>4} {'score':>5}"
    )
    print(header)
    print("-" * len(header))

    certified = 0
    gates_passed = 0
    for puzzle in puzzles:
        cert = certify(puzzle)
        report = verify(puzzle)
        quality = descriptors(puzzle, corpus)
        static = build_report(puzzle.id, validate(puzzle))
        worlds = len(epistemic.build_initial_belief(puzzle))
        cert_ok = cert.solvable and cert.conformance_ok
        certified += 1 if cert_ok else 0
        gates_passed += 1 if report.ok else 0
        print(
            f"{puzzle.id:<22} {str(cert.solvable).lower():>6} {cert.horizon:>3} {worlds:>4} "
            f"{str(cert.unique).lower():>6} {str(cert.conformance_ok).lower():>7} "
            f"{('ok' if report.ok else 'FAIL'):>5} {quality.difficulty.band:>4} "
            f"{static.score:>5}"
        )
        if out_dir:
            with open(os.path.join(out_dir, f"{puzzle.id}.cert.json"), "w", encoding="utf-8") as fh:
                fh.write(dumps(certificate_to_json(cert)))

    print("-" * len(header))
    print(
        f"{certified}/{len(puzzles)} certified (solvable and conformant); "
        f"{gates_passed}/{len(puzzles)} pass all verification gates"
    )
    return 0 if (certified == len(puzzles) and gates_passed == len(puzzles)) else 1


def _cmd_invent(args: argparse.Namespace) -> int:
    puzzle, prov = invent_traced(
        args.word, seed=args.seed, depth=args.depth, length=args.length
    )
    report = verify(puzzle, prov)
    cert = certify(puzzle)
    relevance = next(g for g in report.gates if g.name == "concept-relevance")
    print(f"{puzzle.id}: invented from {args.word!r}")
    print(f"  {puzzle.notes}")
    print(
        f"  solvable={str(cert.solvable).lower()} horizon={cert.horizon} "
        f"unique={str(cert.unique).lower()} conform={str(cert.conformance_ok).lower()}"
    )
    print(
        f"  gates: {'ok' if report.ok else 'FAIL'}; "
        f"concept-relevance [{relevance.status.value.upper()}]: {relevance.detail}"
    )
    for g in report.gates:
        for f in g.findings:
            print(f"    - [{g.name}] {f.rule}: {f.message}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(dumps(puzzle_to_json(puzzle)))
        print(f"wrote puzzle to {args.out}")
    ok = cert.solvable and cert.conformance_ok and report.ok
    return 0 if ok else 1


# The steering policies the `evolve --policy` flag can drive the MAP-Elites search with. Each only
# proposes which niche/operator to try; the validate -> verify -> certify gate stays the sole judge.
# "trained" loads the offline-fitted frozen decision model (propose-only, no online learning).
_POLICY_FACTORIES = {
    "none": lambda: None,
    "steering": SteeringPolicy,
    "contextual": ContextualPolicy,
    "trained": FrozenProposer,
}


def _cmd_evolve(args: argparse.Namespace) -> int:
    seeds = [w for w in (s.strip() for s in args.seeds.split(",")) if w]
    if not seeds:
        print("evolve: no seed words given")
        return 1
    policy = _POLICY_FACTORIES[args.policy]()
    archive = invent_evolve(seeds, args.iters, args.seed, policy=policy)
    print(
        f"evolve: seeds={seeds} iterations={args.iters} seed={args.seed} policy={args.policy} "
        f"-> {len(archive.cells)} niche(s) occupied"
    )
    for reason in sorted(archive.tally):
        print(f"  {reason}: {archive.tally[reason]}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(dumps(archive_to_json(archive)))
        print(f"wrote archive to {args.out}")
    return 0 if archive.cells else 1


def _cmd_archive_show(args: argparse.Namespace) -> int:
    with open(args.path, encoding="utf-8") as fh:
        data = json.load(fh)
    cells = data.get("cells", [])
    if not cells:
        print(f"{args.path}: empty archive (0 niches)")
        return 1
    print(
        f"archive: seed {data['seed']}, {data['iterations']} iteration(s), "
        f"{len(cells)} niche(s) occupied"
    )
    header = f"{'niche':<12} {'fitness':>8} {'band':>4} {'puzzle':<28} {'digest':>12}"
    print(header)
    print("-" * len(header))
    for cell in cells:
        niche = ",".join(str(x) for x in cell["niche"])
        pid = cell["puzzle"]["id"]
        band = cell["quality"]["difficulty"]["band"]
        print(
            f"{niche:<12} {cell['fitness']:>8.3f} {band:>4} {pid:<28} "
            f"{cell['certificate_digest'][:12]:>12}"
        )
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    """Fit the structural difficulty weights to synthetic-player effort over the puzzles in a
    directory, and report the train / held-out Spearman correlations against the default-weight
    baseline (Gate G5 -- the held-out rho clearing the threshold -- reported, never asserted).
    Produces only an artifact: the live difficulty formula is untouched. Exit 0 when the fit
    generalises (held-out rho clears the threshold), else 1."""
    paths = sorted(glob.glob(os.path.join(args.dir, "*.json")))
    if not paths:
        print(f"no puzzles found in {args.dir} (run 'gen' first)")
        return 1
    puzzles = [load_puzzle(path) for path in paths]
    result = calibrate.calibrate(puzzles, players=args.players, base_seed=args.seed)

    def _line(label: str, fitted: float, base: float) -> str:
        return f"  {label:<8} fitted rho={fitted:.6f}  baseline rho={base:.6f}"

    print(
        f"calibrate: {len(puzzles)} puzzle(s), {result.players} synthetic player(s), "
        f"seed {result.base_seed}"
    )
    print(_line("train:", result.train_rho, result.baseline_train_rho))
    print(_line("holdout:", result.holdout_rho, result.baseline_holdout_rho))
    print(f"  G5 (holdout rho >= {result.threshold}): {'PASS' if result.generalizes else 'FAIL'}")
    wj = calibrate.weights_to_json(result.weights)
    print("  weights: " + " ".join(f"{k}={v}" for k, v in wj.items()))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(dumps(calibrate.calibration_to_json(result)))
        print(f"wrote calibration to {args.out}")
    return 0 if result.generalizes else 1


def _prompt_line(out, input_fn, prompt: str, default: str) -> str:
    """Ask for one free-form value, echoing the default; empty input keeps the default."""
    suffix = f" [{default}]" if default != "" else ""
    out.write(f"{prompt}{suffix}: ")
    out.flush()
    raw = input_fn().strip()
    return raw if raw else default


def _prompt_menu(out, input_fn, prompt: str, options: list[str]) -> str:
    """Ask the user to pick one of ``options`` by number (or exact name); default is the first."""
    out.write(prompt + ":\n")
    for i, opt in enumerate(options, 1):
        out.write(f"  {i}. {opt}\n")
    while True:
        out.write(f"Enter 1-{len(options)} [1]: ")
        out.flush()
        raw = input_fn().strip()
        if not raw:
            return options[0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        out.write(f"  '{raw}' is not one of the choices; try again.\n")


def _interactive_ask(args: argparse.Namespace, *, input_fn, out) -> None:
    """Fill in every unset ``ask`` parameter by prompting for it one at a time."""
    if args.category is None:
        args.category = _prompt_menu(out, input_fn, "Pick a category", list(CATEGORIES))
    if not args.all_types and args.qtype is None:
        types = [qt.value for qt in supported_types(args.category)]
        choice = _prompt_menu(out, input_fn, "Pick a question type", [*types, "all of the above"])
        if choice == "all of the above":
            args.all_types = True
        else:
            args.qtype = choice
    if not args.random and args.seed is None:
        ans = _prompt_line(out, input_fn, "Random question each run? (Y/n)", "Y").lower()
        if ans in ("", "y", "yes"):
            args.random = True
        else:
            raw = _prompt_line(out, input_fn, "Seed number", "0")
            args.seed = int(raw) if raw.lstrip("-").isdigit() else 0
    raw = _prompt_line(out, input_fn, "How many questions?", str(args.count))
    args.count = int(raw) if raw.isdigit() and int(raw) > 0 else args.count
    if not args.realistic and args.category in realistic_categories():
        ans = _prompt_line(out, input_fn, "Real-world wording? (y/N)", "N").lower()
        args.realistic = ans in ("y", "yes")
    if not args.words and args.category == "sets":
        from .questions.domains.sets import _CLASSES

        out.write(f"  (known shapes: {', '.join(sorted(_CLASSES))})\n")
        args.words = _prompt_line(out, input_fn, "Seed words, comma-separated (Enter to skip)", "")


def _emit_questions(questions: list, args: argparse.Namespace) -> None:
    """Render one or many proven-answer questions as text (or canonical JSON) to stdout / a file.

    A single question keeps the bare format; a batch (``--count`` / ``--all-types``) or a
    ``--random`` pick is headed with its seed so any question can be reproduced exactly with
    ``--seed``. JSON stays valid: one object for a single question, a list for a batch."""
    multiple = len(questions) > 1
    if args.json:
        if multiple:
            text = dumps([question_to_json(q) for q in questions])
        else:
            text = dumps(question_to_json(questions[0]))
    else:
        blocks = []
        for i, q in enumerate(questions, 1):
            head = ""
            if multiple or args.random:
                head = f"# question {i}/{len(questions)} (reproduce with --seed {q.seed})\n"
            blocks.append(head + "\n".join(render_question(q)))
        text = "\n\n".join(blocks) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {len(questions)} question(s) to {args.out}")
    else:
        sys.stdout.write(text)


def _cmd_ask(args: argparse.Namespace, *, input_fn=None, out=None) -> int:
    """Generate proven-answer question(s) and render them (or emit canonical JSON).

    Each answer is produced by the category's formal decision procedure (Z3 validity or exact
    computation), never a learned model; :meth:`Question.check` has already re-asserted the shape
    invariants inside :func:`generate_question`. ``--random`` only chooses *which* seed to pose (and
    prints it), so the answer path stays fully deterministic and reproducible. With no ``category``
    (or ``-i``) the missing parameters are prompted for one at a time. Exit 0 on success; 1 on an
    unknown category or a type the category cannot pose with a proof (argparse errors exit 2)."""
    input_fn = input if input_fn is None else input_fn
    out = sys.stdout if out is None else out

    if args.interactive or args.category is None:
        _interactive_ask(args, input_fn=input_fn, out=out)
    if args.category is None:
        print("ask: no category given")
        return 1

    try:
        if args.all_types:
            qtypes = [qt.value for qt in supported_types(args.category)]
        elif args.qtype is None:
            print("ask: no question type given (use tf/mcq/blank, --all-types, or run -i)")
            return 1
        else:
            qtypes = [args.qtype]
    except ValueError as exc:
        print(f"ask: {exc}")
        return 1

    count = max(1, args.count)
    if args.random:
        seeds = [random.randrange(10_000) for _ in range(count)]
    else:
        base = 0 if args.seed is None else args.seed
        seeds = [base + i for i in range(count)]
    words = tuple(w for w in (s.strip() for s in (args.words or "").split(",")) if w)
    style = "realistic" if args.realistic else "plain"

    questions = []
    try:
        for seed in seeds:
            for qt in qtypes:
                questions.append(
                    generate_question(args.category, qt, seed=seed, words=words, style=style)
                )
    except ValueError as exc:
        print(f"ask: {exc}")
        return 1
    _emit_questions(questions, args)
    return 0


def _cmd_audit_bank(args: argparse.Namespace) -> int:
    """Re-decide the recognizable subset of the authored bank with the formal solvers and compare
    each verdict to the authored answer (Path B). Recognition abstains unless certain, so
    UNRECOGNIZED is honest coverage loss, never a pass. Exit 0 when no authored answer is formally
    contradicted; 1 when at least one DISAGREE (a counter-model or validity proof against an
    authored answer) is found -- each such finding must still be verified by hand before being
    reported as an error."""
    report = audit_bank(args.path)
    if args.json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report, show_disagreements=not args.summary))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(render_json(report))
        print(f"wrote audit report to {args.out}")
    return 0 if report.disagree == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spie", description="Symbolic Puzzle Invention Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("gen", help="(re)write the hand-encoded examples")
    p_gen.add_argument("--dir", default=DEFAULT_DIR)
    p_gen.set_defaults(func=_cmd_gen)

    for name, func, helptext in (
        ("validate", _cmd_validate, "static checks + score"),
        ("solve", _cmd_solve, "find a minimal solution"),
        ("unique", _cmd_unique, "report the uniqueness verdict"),
        ("conform", _cmd_conform, "replay the solver trace in the interpreter"),
        ("crosscheck", _cmd_crosscheck, "run all three solvers, report agreement (gate G2)"),
        ("verify", _cmd_verify, "run every verification gate"),
        ("quality", _cmd_quality, "print the machine quality vector as JSON"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("puzzle")
        sp.set_defaults(func=func)

    p_cert = sub.add_parser("cert", help="emit the full certificate as JSON")
    p_cert.add_argument("puzzle")
    p_cert.add_argument("--out", default=None, help="write JSON here instead of stdout")
    p_cert.set_defaults(func=_cmd_cert)

    p_present = sub.add_parser(
        "present", help="render rules, hints, answer, and certificate as text"
    )
    p_present.add_argument("puzzle")
    p_present.add_argument("--out", default=None, help="write the text here instead of stdout")
    p_present.set_defaults(func=_cmd_present)

    p_suite = sub.add_parser("suite", help="certify every puzzle in a directory")
    p_suite.add_argument("--dir", default=DEFAULT_DIR)
    p_suite.add_argument("--out", default=None, help="directory to write per-puzzle certificates")
    p_suite.set_defaults(func=_cmd_suite)

    p_invent = sub.add_parser("invent", help="invent a certified puzzle from a single word")
    p_invent.add_argument("word", help="a word in the curated concept KB")
    p_invent.add_argument("--seed", type=int, default=0)
    p_invent.add_argument("--depth", type=int, default=2, help="semantic-graph expansion depth")
    p_invent.add_argument("--length", type=int, default=3, help="forced-skeleton length")
    p_invent.add_argument("--out", default=None, help="write the puzzle JSON here")
    p_invent.set_defaults(func=_cmd_invent)

    p_evolve = sub.add_parser("evolve", help="run a bounded MAP-Elites search from seed words")
    p_evolve.add_argument("--seeds", default="door,fuel,water", help="comma-separated seed words")
    p_evolve.add_argument("--iters", type=int, default=20, help="mutation iterations")
    p_evolve.add_argument("--seed", type=int, default=0)
    p_evolve.add_argument(
        "--policy", choices=tuple(_POLICY_FACTORIES), default="none",
        help="operator/niche steering policy (default none = uniform; trained = frozen model)",
    )
    p_evolve.add_argument("--out", default=None, help="write the archive JSON here")
    p_evolve.set_defaults(func=_cmd_evolve)

    p_archive = sub.add_parser("archive", help="inspect a saved archive")
    a_sub = p_archive.add_subparsers(dest="archive_command", required=True)
    p_show = a_sub.add_parser("show", help="summarize a saved archive as a niche table")
    p_show.add_argument("path", help="path to an archive JSON written by 'evolve'")
    p_show.set_defaults(func=_cmd_archive_show)

    p_calibrate = sub.add_parser(
        "calibrate", help="fit difficulty weights to synthetic telemetry, report Gate G5"
    )
    p_calibrate.add_argument("--dir", default=DEFAULT_DIR)
    p_calibrate.add_argument(
        "--players", type=int, default=20, help="synthetic players per puzzle"
    )
    p_calibrate.add_argument("--seed", type=int, default=0, help="telemetry base seed")
    p_calibrate.add_argument("--out", default=None, help="write the calibration JSON here")
    p_calibrate.set_defaults(func=_cmd_calibrate)

    p_ask = sub.add_parser(
        "ask", help="generate proven-answer question(s) (formal categories; interactive if bare)"
    )
    p_ask.add_argument(
        "category", nargs="?", choices=CATEGORIES, help="question category (omit for interactive)"
    )
    p_ask.add_argument(
        "qtype", nargs="?", help="tf (true/false), mcq, or blank (omit to be prompted)"
    )
    p_ask.add_argument("--seed", type=int, default=None, help="deterministic question seed (0)")
    p_ask.add_argument(
        "--random",
        action="store_true",
        help="pick a random seed each run (printed, so still reproducible via --seed)",
    )
    p_ask.add_argument(
        "--count", type=int, default=1, help="generate this many (consecutive, or random, seeds)"
    )
    p_ask.add_argument(
        "--all-types",
        dest="all_types",
        action="store_true",
        help="generate every question type this category supports",
    )
    p_ask.add_argument(
        "-i", "--interactive", action="store_true", help="prompt for each parameter one by one"
    )
    p_ask.add_argument(
        "--realistic",
        action="store_true",
        help="word the question as an everyday scenario (a skin over the same proven answer)",
    )
    p_ask.add_argument(
        "--words", default="", help="comma-separated seed words (e.g. square,rectangle)"
    )
    p_ask.add_argument("--json", action="store_true", help="emit canonical JSON instead of text")
    p_ask.add_argument("--out", default=None, help="write the question here instead of stdout")
    p_ask.set_defaults(func=_cmd_ask)

    p_audit = sub.add_parser(
        "audit-bank",
        help="formally re-decide the recognizable subset of the authored bank (Path B)",
    )
    p_audit.add_argument(
        "--path", default=DEFAULT_BANK,
        help="directory of batch-*.json (default: puzzle-batch/output)",
    )
    p_audit.add_argument("--json", action="store_true", help="emit canonical JSON instead of text")
    p_audit.add_argument(
        "--summary", action="store_true", help="omit the per-disagreement detail (counts only)"
    )
    p_audit.add_argument("--out", default=None, help="write the JSON report here as well")
    p_audit.set_defaults(func=_cmd_audit_bank)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
