"""Input-driven conditional questions in BrainBloom's existing draft contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ...forge.contract import XP, issues, normalized
from ...forge.corpus import digest, overlap, shingles, stem_key
from ..domains import derive_rng
from ..types import QuestionType
from .logic import Literal, Problem, Rule, analyze, minimum_rules, phrase, rule_text

VERSION = "brainbloom-symbolic-v1"
DIFFICULTIES = {"easy": 1, "medium": 2, "hard": 3}
TYPES = ("multiple-choice", "true-false")


@dataclass(frozen=True)
class Theme:
    noun: str
    title: str
    attributes: tuple[str, ...]


THEMES = {
    "warehouse": Theme("crate", "Warehouse", (
        "sealed", "labelled", "inspected", "fragile", "insured", "refrigerated",
        "tagged", "weighed", "reserved", "registered", "padded", "tracked",
    )),
    "library": Theme("book", "Library", (
        "catalogued", "reserved", "illustrated", "indexed", "bound", "archived",
        "stamped", "numbered", "translated", "repaired", "borrowed", "shelved",
    )),
    "laboratory": Theme("sample", "Laboratory", (
        "sealed", "labelled", "frozen", "sterile", "filtered", "weighed",
        "diluted", "screened", "logged", "stored", "coded", "calibrated",
    )),
    "delivery": Theme("parcel", "Delivery", (
        "wrapped", "tracked", "insured", "express", "signed", "weighed",
        "scanned", "labelled", "registered", "oversized", "sealed", "fragile",
    )),
}


@dataclass(frozen=True)
class Request:
    topic: str = "warehouse"
    qtype: str = "multiple-choice"
    difficulty: str = "medium"
    count: int = 1
    seed: int = 0
    category: str = "logic"

    def __post_init__(self) -> None:
        if self.category != "logic":
            raise ValueError("This release supports category 'logic' only")
        if self.topic not in THEMES:
            raise ValueError(f"Choose a supported topic: {', '.join(THEMES)}")
        if self.qtype not in TYPES:
            raise ValueError(f"Choose a supported question type: {', '.join(TYPES)}")
        if self.difficulty not in DIFFICULTIES:
            raise ValueError("Difficulty must be easy, medium, or hard")
        if type(self.count) is not int or not 1 <= self.count <= 20:
            raise ValueError("Count must be an integer from 1 to 20")
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("Seed must be an integer from 0 to 4294967295")


LESSON = "\n".join((
    "Treat the stated rules as assumptions, even if everyday practice differs.",
    "Follow an implication in its stated direction; its converse need not hold.",
    "If a required consequence is absent, its sufficient condition cannot hold.",
    "A conclusion is guaranteed only when every case matching the premises supports it.",
    "Share this: explain the difference between a possible conclusion and a necessary one.",
))


def candidate(request: Request, seed: int) -> tuple[dict, dict]:
    theme = THEMES[request.topic]
    depth = DIFFICULTIES[request.difficulty]
    qt = QuestionType.parse(request.qtype)
    rng = derive_rng(f"{VERSION}/{request.topic}/{request.difficulty}", qt, seed)
    attributes = tuple(rng.sample(theme.attributes, depth + 3))
    # Randomized literal signs and chain direction are proposals, never verdicts.
    chain = tuple(Literal(i, rng.randrange(3) != 0) for i in range(depth + 1))
    main_rules = tuple(Rule(a, b) for a, b in zip(chain[:-1], chain[1:], strict=True))
    spare_a, spare_b = Literal(depth + 1), Literal(depth + 2)
    rules = [*main_rules, Rule(spare_a, spare_b)]
    rng.shuffle(rules)
    backwards = bool(rng.randrange(2))
    fact = chain[-1].opposite() if backwards else chain[0]
    target = chain[0].opposite() if backwards else chain[-1]
    problem = Problem(attributes, tuple(rules), (fact,))
    ordered_rules = list(reversed(main_rules)) if backwards else list(main_rules)
    indices = [rules.index(r) + 1 for r in ordered_rules]
    target_proof = analyze(problem, (target,))
    if not target_proof["candidates"][0]["entailed"]:
        raise RuntimeError("Proposed target failed its proof")
    measured_depth = minimum_rules(problem, target)
    if measured_depth != depth:
        raise RuntimeError("Difficulty mismatch: measured minimal proof differs from request")
    options = [target, target.opposite(), spare_a, spare_b]
    rng.shuffle(options)
    if qt is QuestionType.TRUE_FALSE:
        options = [target if rng.randrange(2) else target.opposite()]
    proof = analyze(problem, tuple(options))
    correct = [v["entailed"] for v in proof["candidates"]]
    if qt is QuestionType.MCQ and sum(correct) != 1:
        raise RuntimeError("MCQ does not have exactly one entailed answer")
    subject = f"This {theme.noun}"
    target_text = f"{subject} {phrase(problem, target)}"
    statements = [f"{subject} {phrase(problem, lit)}" for lit in options]
    intro = f"Use only these rules about {theme.noun}s; assume they always hold."
    lines = [intro, *[
        f"{i + 1}. {rule_text(problem, rule, theme.noun)}" for i, rule in enumerate(rules)
    ], f"Known: {subject.lower()} {phrase(problem, fact)}."]
    if qt is QuestionType.MCQ:
        lines.append("Which statement must be true?")
        answer = statements[correct.index(True)]
        choices = statements
    else:
        lines.append(f'True or False: the rules guarantee that {statements[0].lower()}.')
        answer = "True" if correct[0] else "False"
        choices = ["True", "False"]
    route = ", then ".join(map(str, indices))
    method = "by ruling out each sufficient condition" if backwards else "in their stated direction"
    # These explanations follow the constructed chain; the target and all options
    # have already been checked independently, including the measured rule depth.
    explanation = (
        f"Apply rule{'s' if depth > 1 else ''} {route} {method}: "
        f"{target_text.lower()}. "
        + ("The other choices are not guaranteed by the stated facts."
           if qt is QuestionType.MCQ else
           "The claim therefore follows." if correct[0] else
           "The proposed claim is the opposite, so the answer is False.")
    )
    title = f"{theme.title} Rulebook {seed}"
    item = {
        "type": request.qtype, "category": "logic", "difficulty": request.difficulty,
        "title": title, "question": "\n".join(lines), "choices": choices,
        "correctAnswer": answer, "correctExplanation": explanation,
        "incorrectExplanation": f"The answer is {answer}. {explanation}",
        "lessonContent": LESSON, "lessonGroup": "Think Straight",
        "xpReward": XP[request.difficulty],
    }
    errors = issues(item)
    if errors:
        raise RuntimeError(f"Generated item violates BrainBloom contract: {errors}")
    proof.update({
        "item_sha256": digest(item), "seed": seed, "target": target_proof["candidates"][0],
        "minimal_required_rules": measured_depth, "reasoning_direction": (
            "contraposition" if backwards else "forward"
        ), "rule_order": indices, "candidate_texts": statements,
        "difficulty_scope": "structural rule-count heuristic; not calibrated on players",
    })
    return item, proof


def generate(request: Request, existing: tuple[dict, ...] = ()) -> dict:
    """Bounded deterministic search. Never rename repetitions to claim novelty.

    The optional bank is consulted ONLY for lexical duplicate exclusion. Its
    authored answers are not used to establish correctness or generate targets.
    """
    bank_stems = {stem_key(i["question"]) for i in existing}
    bank_features = [shingles(i["question"]) for i in existing]
    seen_stems: set[str] = set()
    seen_answers: set[str] = set()
    seen_titles: set[str] = set()
    items, proofs = [], []
    skipped = 0
    for offset in range(request.count * 30):
        item, proof = candidate(request, request.seed + offset)
        key = stem_key(item["question"])
        answer = normalized(item["correctAnswer"])
        title = normalized(item["title"])
        feature = shingles(item["question"])
        duplicate = (
            key in bank_stems or key in seen_stems or title in seen_titles
            or (request.qtype == "multiple-choice" and answer in seen_answers)
            or any(overlap(feature, other) for other in bank_features)
        )
        if duplicate:
            skipped += 1
            continue
        items.append(item)
        proofs.append(proof)
        seen_stems.add(key)
        seen_answers.add(answer)
        seen_titles.add(title)
        if len(items) == request.count:
            break
    if len(items) != request.count:
        raise ValueError(
            f"Only {len(items)} distinct drafts found for {request.count} requested; "
            "try fewer questions or another topic/seed. No partial batch exported."
        )
    return {
        "version": 1, "generator": VERSION, "request": asdict(request),
        "items": items, "rejected": [], "proofs": proofs,
        "intendedImport": {
            "createdBy": "symbolic-generator", "reviewStatus": "draft", "published": False,
        },
        "checks": {
            "contract": "BrainBloom local-shape-checks",
            "answer_correctness": "Z3 and exhaustive truth tables agree on stated assumptions",
            "human_review": "required", "platform_verifier": "not-run",
            "duplicates": "lexical-only; structural/template novelty is not established",
        },
        "provenance": {
            "learned_model_used": False, "bank_items_compared": len(existing),
            "bank_items_sha256": digest(existing) if existing else None,
            "duplicate_candidates_skipped": skipped,
        },
    }
