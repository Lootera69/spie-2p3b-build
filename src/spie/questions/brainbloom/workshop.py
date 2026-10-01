"""Versioned, deterministic generation for all six requested BrainBloom types."""

from __future__ import annotations

from dataclasses import asdict, replace
from fractions import Fraction

from ...forge.contract import XP, normalized
from ...forge.corpus import digest, overlap, shingles, stem_key
from ..domains import derive_rng
from ..types import QuestionType
from . import families, logic_grid, reasoning, word_puzzles
from .catalog import DIFFICULTIES, TOPICS, Request, lesson_group
from .content import LESSONS
from .contract import issues
from .crossword import construct
from .generate import THEMES
from .generate import Request as LegacyRequest
from .generate import candidate as conditional_candidate
from .lexicon import Dictionary, validate_context
from .topics import coverage, resolve_many

VERSION = "brainbloom-symbolic-v2"
DICTIONARY_VERSION = "brainbloom-dictionary-v3"
REASONING_VERSION = "brainbloom-reasoning-v4"
TOPIC_VERSION = "brainbloom-topics-v5"
GRID_VERSION = "brainbloom-logic-grid-v6"
AUTOPILOT_VERSION = "brainbloom-autopilot-v7"
ACTIVITIES_VERSION = "brainbloom-activities-v8"


def structure_key(proof: dict) -> str | None:
    """One acceptance rule shared by generation, history and saved replay."""
    return proof.get("structural_key")


def candidate(request: Request, seed: int, context: dict | None = None) -> tuple[dict, dict]:
    interpretation = None
    if request.instructions:
        from .instructions import validate_request

        interpretation = validate_request(request)
    dictionary = request.topic in ("dictionary", "reasoning", "autopilot", "activities")
    version = (ACTIVITIES_VERSION if request.topic == "activities"
               else AUTOPILOT_VERSION if request.topic == "autopilot"
               else GRID_VERSION if request.topic == "logic-grid"
               else TOPIC_VERSION if request.topic_mode == "combined"
               else REASONING_VERSION if request.topic == "reasoning"
               else DICTIONARY_VERSION if dictionary else VERSION)
    rng = derive_rng(
        f"{version}/{request.category}/{request.topic}/"
        f"{request.difficulty}/{request.qtype}",
        QuestionType.MCQ,
        seed,
    )
    title = f"{TOPICS[request.topic].label} {seed}"
    if request.topic == "logic-grid":
        item, proof = logic_grid.candidate(request, rng)
    elif dictionary:
        if context is None:
            context = (resolve_many(
                Dictionary(), request.subject, request.meanings, request.category)
                       if request.topic_mode == "combined" else Dictionary().resolve(
                           request.subject, request.sense, request.category))
        if request.topic == "autopilot":
            from .autopilot import candidate as design

            item, proof = design(request, rng, context)
        elif request.topic == "activities":
            from .smart_activities import candidate as smart

            item, proof = smart(request, rng, context, seed)
        else:
            item, proof = (
                reasoning.candidate(request, rng, context, seed) if request.topic == "reasoning"
                else word_puzzles.candidate(request, rng, context)
            )
    elif request.topic in THEMES:
        legacy_kind = request.qtype if request.qtype != "type-answer" else "multiple-choice"
        item, proof = conditional_candidate(
            LegacyRequest(request.topic, legacy_kind, request.difficulty, seed=seed), seed
        )
        if request.qtype == "type-answer":
            target = proof["target"]["literal"]
            attribute = proof["problem"]["attributes"][target["atom"]]
            answer = ("" if target["positive"] else "not ") + attribute
            item.update(
                {
                    "type": "type-answer",
                    "choices": [],
                    "correctAnswer": answer,
                    "acceptedAnswers": [
                        answer,
                        f"it is {answer}",
                        f"this {THEMES[request.topic].noun} is {answer}",
                    ],
                    "question": item["question"].rsplit("\n", 1)[0]
                    + f"\nComplete the conclusion using '{attribute}' or 'not {attribute}': "
                    f"this {THEMES[request.topic].noun} is what?",
                }
            )
            item["correctExplanation"] = item["correctExplanation"].replace(
                "The other choices are not guaranteed by the stated facts.",
                "This determines the required completion.",
            )
            item["incorrectExplanation"] = f"The answer is {answer}. {item['correctExplanation']}"
        proof["steps"] = _conditional_steps(proof)
        proof["method"] = "z3-and-exhaustive-truth-tables"
    else:
        item = {
            "type": request.qtype,
            "category": request.category,
            "difficulty": request.difficulty,
            "title": title,
            "choices": [],
            "lessonGroup": lesson_group(request.category, request.topic),
            "xpReward": XP[request.difficulty],
        }
        if request.qtype == "crossword":
            data, checks = construct(
                request.category, 2 * DIFFICULTIES[request.difficulty] + 1, rng,
                board_size=request.crossword_size,
            )
            item.update(
                {
                    "question": f"Solve this {len(data['clues'])}-entry crossword using the clues. "
                    "Which words complete the connected grid?",
                    "crosswordData": data,
                    "correctAnswer": ", ".join(c["answer"] for c in data["clues"]),
                    "correctExplanation": (
                        "Every answer matches its clue " "and all crossing letters agree."
                    ),
                    "incorrectExplanation": (
                        "Check each entry against its clue. "
                        "Crossing letters must agree in both directions."
                    ),
                    "lessonContent": "\n".join(LESSONS["crossword"]),
                }
            )
            proof = {
                "method": "independent-crossword-reconstruction",
                "grid_checks": checks,
                "scope": (
                    "grid structure, connectivity, numbering and crossing consistency; "
                    "clue meanings are curated"
                ),
                "steps": [
                    f"{c['number']} {c['direction']}: {c['answer']} — {c['clue']}."
                    for c in data["clues"]
                ],
            }
        elif request.qtype == "wonder":
            draft = families.wonder(request, rng)
            proof = draft["proof"]
            item.update(
                {
                    "question": draft["stem"],
                    "correctAnswer": draft["insight"],
                    "correctExplanation": draft["insight"],
                    "incorrectExplanation": "This is an unscored reflection. " + draft["insight"],
                    "lessonContent": draft["insight"],
                    "sharePrompt": draft["share"],
                    "xpReward": 0,
                }
            )
        else:
            factory = {
                "ordering": families.ordering,
                "number-riddles": families.mystery,
                "word-riddles": families.word_riddle,
            }.get(request.topic, families.arithmetic)
            draft = factory(request, rng)
            proof = draft["proof"]
            _quiz(item, draft, request, rng)
    if request.topic_mode == "combined":
        if request.topic in ("reasoning", "autopilot"):
            used = proof["model"]["names"]
        elif request.qtype == "crossword":
            used = [c["answer"] for c in item["crosswordData"]["clues"]]
        elif request.qtype == "wonder":
            used = proof["words"]
        else:
            used = proof["word_bank"]
        proof["topic_coverage"] = coverage(context, used)
    if interpretation is not None:
        proof["instruction_interpretation"] = interpretation
    if request.engine_revision >= 3 and request.qtype not in ("true-false", "wonder"):
        # A topic can contain a generated answer (e.g. PLATE in Plate Tectonics).
        # Keep that context in the question, but never let the title reveal which
        # candidate wins. Revision gating preserves byte-for-byte old exports.
        answer = normalized(item["correctAnswer"])
        if answer and f" {answer} " in f" {normalized(item['title'])} ":
            item["title"] = next(
                title for title in ("Combine the clues", "Hidden answer challenge",
                                    "Solve this puzzle")
                if f" {answer} " not in f" {normalized(title)} "
            )
    errors = issues(item)
    if errors:
        raise RuntimeError(f"Generated item violates BrainBloom contract: {errors}")
    proof.update(
        {
            "seed": seed,
            "item_sha256": digest(item),
            "family": request.topic,
            "difficulty_measure": TOPICS[request.topic].difficulty,
            "difficulty_scope": "structural heuristic; not calibrated on players",
        }
    )
    return item, proof


def _conditional_steps(proof: dict) -> list[str]:
    def describe(literal):
        return (
            "it is "
            + ("" if literal["positive"] else "not ")
            + proof["problem"]["attributes"][literal["atom"]]
        )

    steps = ["Given: " + describe(proof["problem"]["facts"][0]) + "."]
    for index in proof["rule_order"]:
        rule = proof["problem"]["rules"][index - 1]
        target = (
            rule["after"]
            if proof["reasoning_direction"] == "forward"
            else {
                **rule["before"],
                "positive": not rule["before"]["positive"],
            }
        )
        steps.append(f"Apply rule {index}: {describe(target)}.")
    return steps


def _quiz(item: dict, draft: dict, request: Request, rng) -> None:
    numeric = "value" in draft
    if numeric:
        value, unit = Fraction(draft["value"]), draft["unit"]

        def render(v):
            return families.number(v) + (f" {unit}" if unit else "")

        answer = render(value)
        offsets = rng.sample([i for i in range(-9, 10) if i and value + i > 0], 3)
        wrong_values = [value + i for i in offsets]
        wrongs = [render(v) for v in wrong_values]
        aliases = [answer, families.number(value), "answer: " + answer]
        if not unit and value.denominator == 1:
            aliases = [
                answer,
                families.number_words(int(value)),
                f"{value.numerator}.0",
                "answer: " + answer,
            ]
        aliases = list(dict.fromkeys(aliases))
        if len(aliases) < 3:
            aliases.append("the answer is " + answer)
    else:
        answer = draft["answer"]
        wrongs = rng.sample(draft["distractors"], 3)
        aliases = draft["aliases"]
    item.update(
        {
            "question": draft["stem"],
            "correctAnswer": answer,
            "correctExplanation": draft["explanation"],
            "incorrectExplanation": f"The answer is {answer}. {draft['explanation']}",
            "lessonContent": "\n".join(LESSONS[draft["lesson"]]),
        }
    )
    if request.qtype == "multiple-choice":
        choices = [answer, *wrongs]
        rng.shuffle(choices)
        item["choices"] = choices
        draft["proof"]["candidate_verdicts"] = [choice == answer for choice in choices]
    elif request.qtype == "true-false":
        truth = bool(rng.randrange(2))
        proposed = answer if truth else wrongs[0]
        item["question"] += f"\nTrue or False: the result is {proposed}."
        item["choices"] = ["True", "False"]
        item["correctAnswer"] = str(truth)
        item["correctExplanation"] = (
            "The claim is correct. " if truth else f"The claim is false; the result is {answer}. "
        ) + draft["explanation"]
        item["incorrectExplanation"] = f"The answer is {truth}. " + item["correctExplanation"]
        draft["proof"]["claim"] = proposed
        draft["proof"]["claim_holds"] = truth
    else:
        item["acceptedAnswers"] = aliases
        if request.qtype == "riddle":
            item["hintText"] = "Apply every clue, not just the first one.\n" + (
                "Keep the letter count unchanged when reversing."
                if not numeric
                else "List candidates in the given range, then test each condition."
            )


def generate(
    request: Request, existing: tuple[dict, ...] = (), context: dict | None = None,
    *, excluded: set[str] | None = None,
) -> dict:
    from .history import fingerprint
    dictionary = request.topic in ("dictionary", "reasoning", "autopilot", "activities")
    if dictionary:
        if context is None:
            context = (resolve_many(
                Dictionary(), request.subject, request.meanings, request.category)
                       if request.topic_mode == "combined" else Dictionary().resolve(
                           request.subject, request.sense, request.category))
        context = validate_context(context)
        if (request.topic_mode == "combined") != ("topics" in context):
            raise ValueError("The topic selection does not match this request")
        if request.topic_mode == "combined":
            selected = {t["term"]: t["sense"] for t in context["topics"]}
            if any(selected.get(term) != sense for term, sense in request.meanings.items()):
                raise ValueError("Selected meanings do not match the topic vocabulary")
            request = replace(request, meanings=selected)
    bank_stems = {stem_key(i["question"]) for i in existing}
    bank_features = [shingles(i["question"]) for i in existing]
    seen = set()
    seen_structures = set()
    items, proofs = [], []
    skipped = 0
    for offset in range(request.count * 30):
        item, proof = candidate(request, request.seed + offset, context)
        # Crosswords share a general prompt but carry distinct layouts and clues.
        content = (
            item["question"] if request.qtype != "crossword" else digest(item["crosswordData"])
        )
        key = normalized(content)
        duplicate = key in seen or fingerprint(item, proof) in (excluded or ())
        structural = structure_key(proof)
        if structural is not None:
            duplicate |= structural in seen_structures
        if request.qtype not in ("crossword", "wonder"):
            feature = shingles(item["question"])
            duplicate |= stem_key(content) in bank_stems or any(
                overlap(feature, old) for old in bank_features
            )
        if duplicate:
            skipped += 1
            continue
        items.append(item)
        proofs.append(proof)
        seen.add(key)
        if structural is not None:
            seen_structures.add(structural)
        if len(items) == request.count:
            break
    if len(items) != request.count:
        raise ValueError(
            f"Only {len(items)} distinct drafts found; choose fewer questions or another topic. "
            "No partial batch exported."
        )
    return {
        **({"dictionary": context} if dictionary else {}),
        "version": (8 if request.topic == "activities" else
                    7 if request.topic == "autopilot" else 6 if request.topic == "logic-grid"
                    else 5 if request.topic_mode == "combined"
                    else 4 if request.topic == "reasoning" else 3 if dictionary else 2),
        "generator": (ACTIVITIES_VERSION if request.topic == "activities" else
                      AUTOPILOT_VERSION if request.topic == "autopilot"
                      else GRID_VERSION if request.topic == "logic-grid"
                      else TOPIC_VERSION if request.topic_mode == "combined"
                      else REASONING_VERSION if request.topic == "reasoning"
                      else DICTIONARY_VERSION if dictionary else VERSION),
        "request": asdict(request),
        "items": items,
        "proofs": proofs,
        "rejected": [],
        "intendedImport": {
            "createdBy": "symbolic-generator",
            "reviewStatus": "draft",
            "published": False,
        },
        "checks": {
            "contract": "BrainBloom quiz and native crossword/Wonder fields",
            "answer_correctness": "see each item's proof and scope",
            "human_review": "required",
            "platform_verifier": "not-run",
            "duplicates": (
                "lexical bank comparison; structural keys within reasoning batches; "
                "grid keys ignore labels, group order and left/right reflection"
            ),
        },
        "provenance": {
            "learned_model_used": False,
            "bank_items_compared": (
                0 if request.qtype in ("crossword", "wonder") else len(existing)
            ),
            "bank_items_sha256": digest(existing) if existing else None,
            "bank_compare_scope": (
                "not applicable: this bank contains quiz formats only"
                if request.qtype in ("crossword", "wonder")
                else "lexical question comparison"
            ),
            "duplicate_candidates_skipped": skipped,
        },
    }
