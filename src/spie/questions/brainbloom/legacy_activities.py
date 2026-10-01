"""Beginner-facing activity routes backed by existing exact engines."""

from __future__ import annotations

from dataclasses import replace

from ...forge.contract import XP
from ...forge.corpus import digest
from . import contradiction, families, reasoning
from .catalog import Request, lesson_group
from .topics import sample_words


def _quiz_item(
    request: Request, draft: dict, rng, title: str, names: list[str]
) -> tuple[dict, dict]:
    answer = draft.get("answer", draft.get("value"))
    if "value" in draft:
        answer = families.number(answer) + (f" {draft['unit']}" if draft["unit"] else "")
        wrongs = [families.number(answer_value) for answer_value in
                  [draft["value"] - 1, draft["value"] + 1, draft["value"] + 2]]
    else:
        wrongs = list(dict.fromkeys(draft.get("distractors", [])))[:3]
    choices = [answer, *wrongs]
    while len(choices) < 4:
        choices.append(f"Not {len(choices)}")
    rng.shuffle(choices)
    item = {"type": request.qtype, "category": request.category, "difficulty": request.difficulty,
            "title": title, "question": draft["stem"], "choices": [],
            "correctAnswer": answer, "correctExplanation": draft["explanation"],
            "incorrectExplanation": f"The answer is {answer}. {draft['explanation']}",
            "lessonGroup": lesson_group(request.category, "activities"),
            "xpReward": XP[request.difficulty],
            "lessonContent": "\n".join(("Look for the rule shared by every example.",
                "Test the rule on the next case, rather than guessing from one example.",
                "Reject a rule that fails any stated example.",
                "Check the answer with exact arithmetic or finite enumeration.",
                "Share this: explain which example gave the decisive clue."))}
    proof = {**draft["proof"], "word_bank": names,
             "structural_key": digest([request.variation, names, draft["proof"]])}
    if request.qtype == "multiple-choice":
        item["choices"] = choices
    elif request.qtype == "true-false":
        truth = bool(rng.randrange(2))
        claim = answer if truth else rng.choice([choice for choice in choices if choice != answer])
        item.update(
            choices=["True", "False"], correctAnswer=str(truth),
            question=draft["stem"] + f"\nTrue or False: the answer is {claim}.",
            correctExplanation=f"The claim is {str(truth).lower()}. " + draft["explanation"],
        )
        proof.update(claim=claim, claim_holds=truth)
    else:
        item["acceptedAnswers"] = [answer, f"the answer is {answer}", f"answer: {answer}"]
        if request.qtype == "riddle":
            item["hintText"] = (
                "Find the operation shared by all the examples.\n"
                "Test it on the final input."
            )
    return item, proof


def candidate(request: Request, rng, context: dict, seed: int) -> tuple[dict, dict]:
    level = {"easy": 1, "medium": 2, "hard": 3}[request.difficulty]
    names = sample_words(
        context, 4 if request.variation == "most-likely" else level + 3, rng
    )
    if request.variation == "contradiction":
        model = contradiction.propose(
            names, {"easy": 1, "medium": 2, "hard": 3}[request.difficulty], rng
        )
        proof = contradiction.check(model)
        stem, answer, choices, explanation, hint = contradiction.render(model)
        item = {
            "type": request.qtype, "category": request.category,
            "difficulty": request.difficulty,
                "title": f"{context['label'].title()} · Find the impossible clue",
                "question": f"Topic labels: {context['label']}.\n{stem}", "choices": [],
                "correctAnswer": answer, "correctExplanation": explanation,
                "incorrectExplanation": explanation,
                "lessonGroup": lesson_group(request.category, "activities"),
                "xpReward": XP[request.difficulty], "lessonContent": "\n".join((
                    "Connect the stated before-relations into a chain.",
                    "Check each candidate statement against the forced order.",
                    "One statement must fail while the others remain possible.",
                    "Use the contradiction, not a real-world fact about a label.",
                    "Share this: identify the chain that made the impossible clue fail."))}
        proof.update(model=model, word_bank=names, quality={"minimum_supporting_clues": 2,
                     "option_count": 4, "exactly_one_impossible": True})
        if request.qtype == "multiple-choice":
            item["choices"] = choices
        elif request.qtype == "true-false":
            truth = bool(rng.randrange(2))
            claim = answer if truth else rng.choice([c for c in choices if c != answer])
            item.update(choices=["True", "False"], correctAnswer=str(truth),
                        question=item["question"] + f"\nTrue or False: {claim} is impossible.",
                        correctExplanation=f"The claim is {str(truth).lower()}. {explanation}")
            proof.update(claim=claim, claim_holds=truth)
        else:
            item["acceptedAnswers"] = [answer, answer.lower(), f"statement {answer[-1]}"]
            if request.qtype == "riddle":
                item["hintText"] = "\n".join(hint)
        return item, proof
    if request.variation == "pattern":
        inner = replace(request, topic="sequences", variation="auto", category="logic",
                        topic_mode="single",
                        subject="", meanings={})
        draft = families.arithmetic(inner, rng)
        draft["stem"] = (f"Topic labels used for this invented example: {', '.join(names)}.\n"
                         + draft["stem"])
        return _quiz_item(request, draft, rng, "Discover a number rule", names)
    style = "bayesian" if request.variation == "most-likely" else "planning"
    inner = replace(request, topic="reasoning", variation=style, topic_mode="combined")
    item, proof = reasoning.candidate(inner, rng, context, seed)
    proof["word_bank"] = names
    proof.setdefault("structural_key", digest([request.variation, names, proof]))
    return item, proof
