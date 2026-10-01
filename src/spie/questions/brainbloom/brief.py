"""Plain-language workshop choices translated into compatible, validated engine requests."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

from .catalog import CATEGORIES, DIFFICULTIES, QUIZ, TOPICS, Request
from .instructions import EXAMPLES, MAX_LENGTH, combined_subject, interpret, validate_request
from .lexicon import Dictionary
from .topics import lookup_many, validate_meanings


@dataclass(frozen=True)
class Activity:
    label: str
    family: str
    variation: str
    description: str
    types: tuple[str, ...] = (*QUIZ, "riddle")

    @property
    def uses_topics(self) -> bool:
        return self.family in ("dictionary", "reasoning", "autopilot", "activities")


ACTIVITIES = {
    "autopilot": Activity("Design a clue puzzle for me", "autopilot", "auto",
                          "Choose topics and a level. BrainBloom invents the groups, clues, "
                          "question and hints, then checks the complete solution."),
    "contradiction": Activity("Find the impossible clue", "activities", "contradiction",
                               "Use a verified set of clues to identify the one statement "
                               "that cannot be true."),
    "most-likely": Activity("Choose the most likely explanation", "activities", "most-likely",
                            "Compare fictional hidden-card hypotheses using the supplied prior "
                            "chances and scanner readouts; choose the most likely card."),
    "best-move": Activity("Plan the best next move", "activities", "best-move",
                          "Compare routes on a topic-labelled map and choose the first move "
                          "with the lowest total cost to the goal."),
    "pattern": Activity("Discover a number rule", "activities", "pattern",
                        "Use input/output examples to find the only matching rule among "
                        "four stated possibilities."),
    "logic-grid": Activity("Create a custom logic grid", "logic-grid", "auto",
                           "Define your own groups and rules; verify or complete a unique puzzle."),
    "deduction": Activity("Solve a set of clues", "reasoning", "deduction",
                          "Arrange topic-labelled cards by combining several clues."),
    "bayesian": Activity("Weigh the evidence", "reasoning", "bayesian",
                         "Use given chances and new clues to find the most likely hidden card."),
    "planning": Activity("Choose the best next question", "reasoning", "planning",
                         "Identify a hidden card in the fewest expected steps."),
    "anagram": Activity("Unscramble a word", "dictionary", "anagram",
                        "Rearrange letters with a meaning clue and a bank covering every topic."),
    "missing-letters": Activity("Find the missing letters", "dictionary", "missing-letters",
                                "Complete a word using a clue and all your topics' vocabulary."),
    "word-order": Activity("Put words in order", "dictionary", "word-order",
                           "Arrange words from all your topics in alphabetical order."),
    "crossword": Activity("Connect words in a crossword", "dictionary", "auto",
                          "Fill a connected grid with at least one entry from every topic.",
                          ("crossword",)),
    "word-wonder": Activity("Explore patterns in words", "dictionary", "auto",
                            "Explore letter arrangements using one word from each topic; unscored.",
                            ("wonder",)),
    **{key: Activity(label, key, "auto", description, TOPICS[key].types)
       for key, label, description in (
           ("arithmetic", "Solve an everyday number problem",
            "Calculate quantities in a built-in scenario."),
           ("sequences", "Find the next number", "Follow a stated number pattern."),
           ("number-riddles", "Guess the hidden number", "Combine clues to identify one number."),
           ("ordering", "Work out positions", "Use a built-in set of ordering clues."),
           ("word-riddles", "Reverse a word", "Solve a built-in word-reversal challenge."),
           ("motion", "Calculate speed and journeys", "Use given distances, times and formulas."),
           ("circuits", "Solve a simple circuit", "Use given resistances, voltage and formulas."),
           ("density", "Calculate mass and volume", "Use given measurements and density formula."),
           ("growth", "Explore how doubling works", "Consider a doubling thought experiment."),
           ("probability", "Explore shared birthdays", "Explore a probability model; unscored."),
           ("pigeonhole", "Explore when a match is certain", "Use a counting argument; unscored."),
           ("warehouse", "Follow rules about parcels", "Draw conclusions from given parcel rules."),
           ("library", "Follow rules about books", "Draw conclusions from built-in library rules."),
           ("laboratory", "Follow rules about samples", "Draw conclusions from given rules."),
           ("delivery", "Follow delivery rules", "Draw conclusions from built-in delivery rules."),
       )},
}


@dataclass(frozen=True)
class Brief:
    category: str = "logic"
    qtype: str = "multiple-choice"
    activity: str = "auto"
    subject: str = ""
    meanings: dict[str, str] = field(default_factory=dict)
    difficulty: str = "hard"
    count: int = 1
    seed: int = 7
    search_effort: str = "balanced"
    instructions: str = ""
    grid: dict | None = None
    crossword_size: int | None = None

    def __post_init__(self):
        validate_meanings(self.meanings)
        if (not isinstance(self.activity, str)
                or self.activity not in ("auto", "custom", *ACTIVITIES)):
            raise ValueError("Choose a puzzle activity from the list")
        if not isinstance(self.instructions, str) or len(self.instructions) > MAX_LENGTH:
            raise ValueError(f"Instructions must be text of at most {MAX_LENGTH} characters")
        if self.activity != "custom" and self.instructions:
            raise ValueError("Select 'Describe it in my own words' to use written instructions")
        if self.grid is not None and not isinstance(self.grid, dict):
            raise ValueError("Grid settings must be an object")
        if self.grid is not None and self.activity not in ("custom", "logic-grid"):
            raise ValueError("Choose the custom logic-grid activity to use groups and rules")
        # Reuse the engine's strict numeric/text validation, independent of activity.
        Request("reasoning" if self.qtype not in ("crossword", "wonder") else "dictionary",
                self.qtype, self.difficulty, self.count, self.seed, self.category,
                self.subject, search_effort=(self.search_effort if self.qtype not in
                                             ("crossword", "wonder") else "balanced"),
                crossword_size=self.crossword_size)
        if (not isinstance(self.search_effort, str)
                or self.search_effort not in ("quick", "balanced", "thorough")):
            raise ValueError("Choose Quick, Standard or More exploration")


def configuration() -> dict:
    from .logic_grid import EXAMPLE

    return {
        "activities": {key: {"label": a.label, "description": a.description,
                             "categories": TOPICS[a.family].categories, "types": a.types,
                             "uses_topics": a.uses_topics}
                       for key, a in ACTIVITIES.items()},
        "category_help": "Where the puzzle will appear on your platform.",
        "format_help": "How the player answers. This controls the available activities.",
        "max_topics": 6,
        "instruction_examples": EXAMPLES,
        "instruction_limit": MAX_LENGTH,
        "grid_example": EXAMPLE,
    }


def _fits(activity: Activity, difficulty: str, context: dict | None, topic_count: int) -> str:
    if not activity.uses_topics:
        return ""
    level = DIFFICULTIES[difficulty]
    if activity.family == "autopilot":
        slots = level * 3
    elif activity.family == "activities":
        slots = (4 if activity.variation == "most-likely" else
                 level + 4 if activity.variation == "best-move" else level + 3)
    elif activity.family == "reasoning":
        slots = 4 if activity.variation == "bayesian" else level + 3
    elif activity.types == ("crossword",):
        slots = 2 * level + 1
    elif activity.types == ("wonder",):
        slots = topic_count
    else:
        slots = 4 + 2 * level
    if topic_count > slots:
        return (f"This level uses {slots} words, but you entered {topic_count} topics. "
                "Choose a larger puzzle or a different activity.")
    if context and len(context["entries"]) < slots and (
        activity.family in ("reasoning", "autopilot", "activities")
        or activity.types == ("crossword",)
    ):
        return (f"This level needs {slots} words; your selected meanings provide "
                f"{len(context['entries'])}. Choose an easier level or add a topic.")
    return ""


def _difficulty_help(activity: Activity, difficulty: str) -> str:
    level = DIFFICULTIES[difficulty]
    if activity.family == "autopilot":
        return (f"3 positions and {level} {'group' if level == 1 else 'groups'} of labels. "
                "BrainBloom writes all clues and checks that the answer needs multiple clues.")
    if activity.family == "activities":
        return {
            "pattern": (f"{level + 3} examples; " +
                        ("one arithmetic operation." if level == 1 else
                         "two arithmetic operations." if level == 2 else
                         "quadratic and linear rules.")),
            "contradiction": f"{level + 3} cards; combine at least {level + 1} ordering clues.",
            "most-likely": f"4 hidden-card hypotheses and {level} noisy readouts.",
            "best-move": f"{level + 4} map locations; compare full routes, not just first steps.",
        }[activity.variation]
    if activity.family == "reasoning":
        return {
            "deduction": (f"{level + 3} cards; the answer needs "
                          f"{level + 1}–{level + 2} clues together."),
            "bayesian": (f"4 possible answers; {level} evidence "
                         f"{'step' if level == 1 else 'steps'}."),
            "planning": f"Choose a strategy for identifying one of {level + 3} hidden cards.",
        }[activity.variation]
    if activity.types == ("crossword",):
        return f"{2 * level + 1} connected entries, including every topic."
    if activity.family == "dictionary":
        return (f"Compare up to {4 + 2 * level} words. Higher levels use longer words "
                "or fewer visible letters.")
    descriptions = {
        "arithmetic": ["One calculation step.", "Two calculation steps.",
                       "Three calculation steps."],
        "sequences": ["Add the same amount each time.", "Multiply by the same amount each time.",
                      "Alternate between two stated rules."],
        "motion": ["One journey.", "Combine two stages of a journey.", "Convert time units first."],
        "circuits": ["One resistor.", "Resistors in series.", "Resistors in parallel."],
        "density": ["One sample.", "Combine the volumes of samples.", "Convert the stated units."],
        "ordering": ["Order four objects.", "Order five objects.", "Order six objects."],
    }
    if activity.family in descriptions:
        return descriptions[activity.family][level - 1]
    return TOPICS[activity.family].difficulty + "."


def _prepare(brief: Brief, dictionary: Dictionary) -> dict:
    if brief.activity == "logic-grid":
        return _prepare_grid(brief)
    category = "wonders" if brief.category == "wonder" else brief.category
    lookup = lookup_many(dictionary, brief.subject, brief.meanings, category)
    context = lookup.get("context")
    count = len(lookup["groups"])
    options = []
    for key, activity in ACTIVITIES.items():
        if category not in TOPICS[activity.family].categories or brief.qtype not in activity.types:
            continue
        reason = ("This built-in activity cannot use custom topics. Choose a topic-based activity."
                  if brief.subject.strip() and not activity.uses_topics and key != "logic-grid" else
                  _fits(activity, brief.difficulty, context, count))
        options.append({"id": key, "label": activity.label, "description": activity.description,
                        "available": not bool(reason), "reason": reason,
                        "uses_topics": activity.uses_topics})
    selected = brief.activity
    if selected == "auto":
        # Automatic scored drafts should require combining constraints or looking
        # ahead. Letter sorting, anagrams and one-step exercises remain explicit
        # choices; do not quietly downgrade to them when a topic pool is too small.
        preferred = {
            "logic": ["deduction", "planning", "contradiction", "best-move"],
            "riddles": ["deduction", "planning", "contradiction", "best-move"],
            "science": ["deduction", "planning", "best-move", "contradiction"],
            "puzzles": ["planning", "deduction", "best-move", "contradiction"],
            "wonders": ["planning", "deduction", "best-move", "contradiction"],
        }[category]
        if brief.qtype in ("crossword", "wonder"):
            preferred = ["crossword"] if brief.qtype == "crossword" else ["word-wonder", "growth"]
        available = {a["id"] for a in options if a["available"]}
        selected = next((key for key in preferred if key in available), "")
    choice = next((a for a in options if a["id"] == selected), None)
    report = {"lookup": lookup, "activities": options, "selected_activity": selected,
              "ready": False, "message": "", "request": None, "max_count": 20,
              "difficulty_options": [], "difficulty_relevant": True, "search_relevant": False}
    if choice is None:
        report["message"] = (
            "No activity fits these settings. Add a related topic, change the challenge level "
            "or choose another activity."
        )
        report["difficulty_options"] = [
            {"id": level, "available": any(not _fits(ACTIVITIES[a["id"]], level, context, count)
                                             for a in options
                                             if brief.activity != "auto" or a["id"] in preferred),
             "reason": ""}
            for level in DIFFICULTIES
        ]
        if selected in ACTIVITIES:
            missing = ACTIVITIES[selected]
            categories = TOPICS[missing.family].categories
            if category not in categories:
                report["message"] = (f"'{missing.label}' uses the "
                                     + ", ".join(CATEGORIES[c] for c in categories)
                                     + " category. Change the category or choose another activity.")
            elif brief.qtype not in missing.types:
                report["message"] = (f"'{missing.label}' needs another answer format: "
                                     + ", ".join(missing.types) + ".")
        return report
    activity = ACTIVITIES[selected]
    report.update({
        "description": activity.description, "uses_topics": activity.uses_topics,
        "search_relevant": activity.family == "reasoning",
        "difficulty_relevant": selected != "word-wonder",
        "difficulty_help": _difficulty_help(activity, brief.difficulty),
        "difficulty_options": [
            {"id": level, "available": not bool(_fits(activity, level, context, count)),
             "reason": _fits(activity, level, context, count)} for level in DIFFICULTIES
        ],
    })
    if selected == "crossword" and context:
        from .crossword import recommend_size

        entry_pairs = [(entry["word"], entry["definition"]) for entry in context["entries"]]
        count_for_board = 2 * DIFFICULTIES[brief.difficulty] + 1
        recommendation = recommend_size(
            entry_pairs, count_for_board,
            [topic["anchor"] for topic in context.get("topics", []) if topic["anchor"]],
            [topic["words"] for topic in context.get("topics", [])],
        )
        report["crossword_recommendation"] = recommendation
        report["crossword_size_options"] = recommendation["options"]
        chosen_size = brief.crossword_size or recommendation["recommended"]
        if chosen_size is None:
            report["message"] = recommendation["reason"]
            return report
        chosen_option = next(o for o in recommendation["options"] if o["id"] == chosen_size)
        if not chosen_option["available"]:
            report["message"] = chosen_option["reason"]
            return report
    else:
        chosen_size = brief.crossword_size
    if not choice["available"]:
        report["message"] = choice["reason"]
        return report
    if activity.uses_topics and lookup["status"] != "ready":
        report["message"] = lookup["message"]
        return report
    if selected == "word-wonder" and context:
        report["max_count"] = min(20, math.prod(1 if t["anchor"] else len(t["words"])
                                               for t in context["topics"]))
    if brief.count > report["max_count"]:
        report["message"] = (f"These words allow at most {report['max_count']} distinct "
                             "reflections. Reduce the count or broaden your topics.")
        return report
    request = Request(
        activity.family, brief.qtype, "medium" if selected == "word-wonder" else brief.difficulty,
        brief.count, brief.seed, category,
        brief.subject.strip() if activity.uses_topics else "", variation=activity.variation,
        search_effort=brief.search_effort if activity.family == "reasoning" else "balanced",
        topic_mode="combined" if activity.uses_topics else "single",
        meanings=lookup["meanings"] if activity.uses_topics else {},
        crossword_size=chosen_size if selected == "crossword" else None,
    )
    report.update({"ready": True, "request": asdict(request),
                   "message": f"Ready: {activity.label.lower()}. " + (
                       f"All {count} topics will be included."
                       if activity.uses_topics else "Uses a built-in scenario.")})
    return report


def _prepare_grid(brief: Brief) -> dict:
    from .logic_grid import analyze

    # Reuse the normal option inventory, but do not run dictionary lookup on grid labels.
    category = "wonders" if brief.category == "wonder" else brief.category
    report = {
        "lookup": {"groups": [], "meanings": {}, "unknown_terms": [], "suggestions": {},
                   "using_category": False},
        "activities": [{"id": key, "label": a.label, "description": a.description,
                        "available": True, "uses_topics": a.uses_topics, "reason": ""}
                       for key, a in ACTIVITIES.items()
                       if category in TOPICS[a.family].categories and brief.qtype in a.types],
        "selected_activity": "logic-grid", "description": ACTIVITIES["logic-grid"].description,
        "ready": False, "request": None, "uses_topics": False,
        "difficulty_relevant": False, "difficulty_options": [], "search_relevant": False,
        "max_count": 20, "message": "", "grid_analysis": None,
    }
    if brief.qtype not in ACTIVITIES["logic-grid"].types:
        report["message"] = "Custom grids use Multiple Choice, True / False, Type Answer or Riddle."
        return report
    if brief.subject.strip() or brief.meanings:
        report["message"] = "For custom grids, enter labels in Groups instead of dictionary topics."
        return report
    try:
        analysis = analyze(brief.grid)
        report["grid_analysis"] = analysis
    except ValueError as exc:
        report["message"] = str(exc)
        return report
    report["max_count"] = analysis["max_count"]
    if analysis["status"] == "contradictory":
        report["message"] = "These rules conflict: " + "; ".join(
            f"{c['number']}. {c['text']}" for c in analysis["conflicts"])
        return report
    completing = brief.grid is None or brief.grid.get("complete", True)
    if analysis["status"] == "ambiguous" and not completing:
        report["message"] = (f"Your rules allow {analysis['solution_count']} arrangements. "
                             "Add a rule or allow the engine to add clues.")
        return report
    if brief.count > analysis["max_count"]:
        report["message"] = (f"These rules support at most {analysis['max_count']} distinct "
                             "grid/question pairs. Reduce the count or change the target.")
        return report
    request = Request("logic-grid", brief.qtype, analysis["difficulty"], brief.count,
                      brief.seed, category, grid=brief.grid)
    report.update(ready=True, request=asdict(request), message=(
        "Your rules already give one unique complete grid."
        if analysis["status"] == "unique" else
        f"{analysis['solution_count']} arrangements fit your rules. "
        "The engine will add and label clues to select one unique grid."
    ))
    return report


def prepare(brief: Brief, dictionary: Dictionary) -> dict:
    if brief.activity != "custom":
        return _prepare(brief, dictionary)
    interpreted = interpret(brief.instructions)
    baseline = replace(brief, activity="auto", instructions="", grid=None)
    if interpreted["status"] != "supported":
        report = _prepare(baseline, dictionary)
        report.update(ready=False, request=None, instruction=interpreted,
                      message=" ".join(interpreted["issues"]))
        return report
    fields = interpreted["fields"]
    subject = combined_subject(brief.subject, interpreted)
    if len(subject) > 200:
        interpreted.update(
            status="clarify", issues=["Keep the combined topics within 200 characters."]
        )
        report = _prepare(baseline, dictionary)
        report.update(ready=False, request=None, instruction=interpreted,
                      message=interpreted["issues"][0])
        return report
    patches = {key: value for key, value in fields.items()
               if key in ("count", "difficulty", "qtype") and value != getattr(brief, key)}
    if subject != brief.subject.strip():
        patches["subject"] = subject
    if patches:
        report = _prepare(baseline, dictionary)
        interpreted.update(status="apply", changes=patches)
        report.update(ready=False, request=None, instruction=interpreted,
                      message="Review the interpretation and apply the settings below.")
        return report
    effective = replace(baseline, activity=fields.get("activity", "auto"),
                        grid=brief.grid if fields.get("activity") == "logic-grid" else None)
    report = _prepare(effective, dictionary)
    interpreted["resolved_activity"] = report["selected_activity"]
    report["instruction"] = interpreted
    if report["ready"]:
        if report["selected_activity"] == "word-wonder" and "difficulty" in fields:
            report.update(ready=False, request=None, message=(
                "This unscored reflection has no challenge level. Remove the difficulty "
                "from your instructions, or choose a scored activity."
            ))
            return report
        request = Request(**{**report["request"], "instructions": brief.instructions})
        try:
            validate_request(request)
        except ValueError as exc:
            report.update(ready=False, request=None, message=str(exc))
        else:
            report["request"] = asdict(request)
    return report
