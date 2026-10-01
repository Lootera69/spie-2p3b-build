"""Bounded propose–solve–rank generation with inspectable quality objectives."""

from __future__ import annotations

from ...forge.contract import XP
from ...forge.corpus import digest
from . import deduction, probabilistic
from .catalog import DIFFICULTIES, Request, lesson_group
from .lexicon import validate_context
from .topics import sample_words

STYLES = ("deduction", "bayesian", "planning")
BUDGETS = {"quick": 12, "balanced": 32, "thorough": 80}
LABELS = {
    "deduction": "Multi-clue deduction",
    "bayesian": "Bayesian evidence",
    "planning": "Plan the best next question",
}
CONCISE_LABELS = {
    "deduction": "Follow the clues",
    "bayesian": "Weigh the evidence",
    "planning": "Plan the questions",
}
LESSON = "\n".join((
    "Represent the possible states and the rules explicitly before choosing an answer.",
    "For deduction, eliminate arrangements that violate even one clue.",
    "For probability, combine prior weights with the stated evidence model.",
    "For planning, consider both possible answers and the questions needed afterwards.",
    "Share this: explain why the closest alternative fails or costs more.",
))


def _render(style: str, model: dict, *, concise: bool = False
            ) -> tuple[str, str, list[str], str, str]:
    names = model["names"]
    if style == "deduction":
        clues = [deduction.Clue(**row) for row in model["clues"]]
        stem = (f"Arrange {len(names)} cards labelled {', '.join(names)} in a row. "
                f"Each card appears exactly once; positions run from 1 to {len(names)}, "
                "left to right. Use only these clues:\n"
                + "\n".join(f"{i + 1}. {deduction.text(c, names)}" for i, c in enumerate(clues))
                + f"\nWhich card must occupy position {model['position'] + 1}?")
        if concise:
            stem = (f"Arrange cards {', '.join(names)} once each, left to right, "
                    f"in positions 1–{len(names)}.\n"
                    + "\n".join(f"{i + 1}. {deduction.text(c, names, concise=True)}"
                                for i, c in enumerate(clues))
                    + f"\nWhich card must occupy position {model['position'] + 1}?")
        answer = names[model["answer_index"]]
        explanation = (f"{answer} must occupy position {model['position'] + 1}. "
                       "Exactly one full arrangement satisfies all the clues. "
                       f"At least {model['minimum_support']} clues are needed "
                       "to force this answer.")
        hint = ("Track possible positions and combine clues that mention the same card.\n"
                "An adjacent pair can face either way unless another clue fixes its direction.")
        return stem, answer, names, explanation, hint
    if style == "bayesian":
        observed = model["observed_positive"]
        stem = ("A fictional scanner hides one labelled card. Its prior selection probabilities "
                "are proportional to the weights below. Each readout is positive or negative. "
                "Readouts are independent CONDITIONAL ON the hidden card; "
                "a negative readout has probability 1 minus the listed positive probability.\n"
                + "\n".join(
                    f"{name}: prior weight {model['priors'][i]}; "
                    + "; ".join(f"P(readout {j + 1} positive | {name}) = {rate}/10"
                                for j, rate in enumerate(model['positive_rates_out_of_ten'][i]))
                    for i, name in enumerate(names))
                + "\nObserved: "
                + ", ".join(f"readout {j + 1} {'positive' if value else 'negative'}"
                            for j, value in enumerate(observed))
                + ". Which hidden card is now MOST LIKELY?")
        if concise:
            stem = ("One card is hidden. The table gives prior weights and positive-readout "
                    "probabilities. Readouts are independent given the card; negative "
                    "probability is one minus positive.\nCard | Prior weight | "
                    + " | ".join(f"Readout {j + 1}" for j in range(len(observed)))
                    + "\n" + "\n".join(
                        f"{name} | {model['priors'][i]} | "
                        + " | ".join(f"{rate}/10"
                                     for rate in model['positive_rates_out_of_ten'][i])
                        for i, name in enumerate(names))
                    + "\nObserved: "
                    + ", ".join(f"readout {j + 1} {'positive' if value else 'negative'}"
                                for j, value in enumerate(observed))
                    + ". Which hidden card is now most likely?")
        answer = names[model["answer_index"]]
        probability = model["posterior"][model["answer_index"]]
        explanation = (f"{answer} has the largest posterior probability, {probability}. "
                       "Multiply each prior weight by its observed-readout likelihoods, "
                       "then divide by the sum of all four products. Most likely is not certain.")
        hint = ("Use both the prior weights and the readout likelihoods.\n"
                "For a negative readout, use 1 minus its positive probability.")
        return stem, answer, names, explanation, hint
    total = sum(model["weights"])
    choices = [f"Question {chr(65 + i)}" for i in range(4)]
    stem = ("A hidden card must be identified exactly. The prior probabilities are:\n"
            + ", ".join(f"{name}: {weight}/{total}"
                        for name, weight in zip(names, model["weights"], strict=True))
            + ".\nYou can ask only the four yes/no questions below. Every answer is truthful; "
            "each question costs one unit. You can adapt later questions to earlier answers, "
            "and stop only when one card remains possible.\n"
            + "\n".join(f"{choices[i]}: Is the hidden card in "
                        + "{" + ", ".join(names[j] for j in group) + "}?"
                        for i, group in enumerate(model["tests"]))
            + "\nWhich FIRST question minimizes the expected TOTAL number of questions, "
            "including itself, if all subsequent choices are optimal?")
    if concise:
        stem = ("Identify one hidden card. Prior probabilities:\n"
                + ", ".join(f"{name}: {weight}/{total}"
                            for name, weight in zip(names, model["weights"], strict=True))
                + ".\nOnly these yes/no questions are allowed; answers are truthful. "
                "Each costs one. Adapt later questions to earlier answers; "
                "stop when one card remains.\n"
                + "\n".join(f"{choices[i]}: Is the card in "
                            + "{" + ", ".join(names[j] for j in group) + "}?"
                            for i, group in enumerate(model["tests"]))
                + "\nWhich first question minimizes expected total questions, including "
                "itself, with optimal later choices?")
    answer = choices[model["answer_index"]]
    explanation = (f"{answer} is uniquely optimal: its expected total is "
                   f"{model['expected_questions'][model['answer_index']]} questions. "
                   "The planner checks both branches recursively until exact identification.")
    hint = ("Consider what remains possible after both yes and no.\n"
            "Weight the future costs by their branch probabilities and add one for this question.")
    return stem, answer, choices, explanation, hint


def candidate(request: Request, rng, context: dict, seed: int) -> tuple[dict, dict]:
    validate_context(context)
    level = DIFFICULTIES[request.difficulty]
    # Auto rotates skills across consecutive candidate seeds, rather than allowing
    # a single numerical score to favour one unrelated skill over the others.
    style = STYLES[seed % len(STYLES)] if request.variation == "auto" else request.variation
    if request.variation == "auto" and "topics" in context:
        eligible = [s for s in STYLES
                    if len(context["topics"]) <= (4 if s == "bayesian" else level + 3)
                    <= len(context["entries"])]
        if not eligible:
            raise ValueError("Choose a larger puzzle to include all your topics")
        style = eligible[seed % len(eligible)]
    size = 4 if style == "bayesian" else level + 3
    if len(context["entries"]) < size:
        raise ValueError(f"This reasoning difficulty requires at least {size} topic words")
    propose = {
        "deduction": deduction.propose, "bayesian": probabilistic.bayes_propose,
        "planning": probabilistic.planning_propose,
    }[style]
    pool = [entry["word"] for entry in context["entries"]]
    models, rejected = [], 0
    for attempt in range(BUDGETS[request.search_effort]):
        names = (sample_words(context, size, rng) if "topics" in context
                 else rng.sample(pool, size))
        model = propose(names, level, rng)
        if model is None:
            rejected += 1
            continue
        model["attempt"] = attempt
        models.append(model)
    if not models:
        raise ValueError(
            "No reasoning candidate met the uniqueness and difficulty gates within this budget. "
            "Choose a larger search budget or a different seed."
        )
    model = max(models, key=lambda row: (row["score"], -row["attempt"]))
    checker = {
        "deduction": deduction.check, "bayesian": probabilistic.bayes_check,
        "planning": probabilistic.planning_check,
    }[style]
    proof = checker(model)
    concise = request.engine_revision >= 4
    stem, answer, candidates, explanation, hint = _render(style, model, concise=concise)
    stem = (("Fictional card labels.\n" if concise else
             f"Topic: {context['label']}. This is an invented card puzzle; "
             "the labels do not imply real-world properties.\n") + stem)
    item = {
        "type": request.qtype, "category": request.category, "difficulty": request.difficulty,
        "title": (CONCISE_LABELS[style] if concise else
                  f"{context['label'].title()} · {LABELS[style]}"), "question": stem,
        "choices": [], "correctAnswer": answer, "correctExplanation": explanation,
        "incorrectExplanation": "Recheck the stated assumptions. " + explanation,
        "lessonGroup": lesson_group(request.category, "reasoning"),
        "xpReward": XP[request.difficulty], "lessonContent": LESSON,
    }
    wrongs = [value for value in candidates if value != answer]
    if request.qtype == "multiple-choice":
        choices = [answer, *rng.sample(wrongs, 3)]
        rng.shuffle(choices)
        item["choices"] = choices
    elif request.qtype == "true-false":
        truth = bool(rng.randrange(2))
        claimed = answer if truth else rng.choice(wrongs)
        item.update({"choices": ["True", "False"], "correctAnswer": str(truth),
                     "question": stem + f"\nTrue or False: the answer above is {claimed}.",
                     "correctExplanation": f"The claim is {str(truth).lower()}. " + explanation})
        proof.update({"claim": claimed, "claim_holds": claimed == answer})
    else:
        item["acceptedAnswers"] = [answer, "the answer is " + answer, "answer: " + answer]
        if request.qtype == "riddle":
            item["hintText"] = hint
    proof.update({
        "reasoning_style": style, "model": model, "quality": model["quality"],
        "dictionary_sha256": digest(context), "selected_sense": context["sense"],
        "source": context["source"]["name"],
        "search": {
            "budget": BUDGETS[request.search_effort], "qualified": len(models),
            "rejected": rejected, "selected_attempt": model["attempt"],
            "selected_score": model["score"], "first_qualified_score": models[0]["score"],
            "qualified_scores": [m["score"] for m in models],
            "objective": "structural heuristic within one skill; not a human quality rating",
            "independent_check": "selected candidate checked before release",
        },
    })
    return item, proof
