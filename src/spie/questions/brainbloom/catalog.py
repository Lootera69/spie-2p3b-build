"""The supported product surface; only meaningful category/type/topic pairs."""

from __future__ import annotations

from dataclasses import dataclass, field

DIFFICULTIES = {"easy": 1, "medium": 2, "hard": 3}
TYPES = ("multiple-choice", "true-false", "type-answer", "crossword", "riddle", "wonder")
CATEGORIES = {
    "logic": "Logic",
    "riddles": "Riddles",
    "science": "Science",
    "puzzles": "Puzzles",
    "wonders": "Wonder",
}
QUIZ = ("multiple-choice", "true-false", "type-answer")
VARIATIONS = {
    "activities": {"auto": "Mix discovery activities", "pattern": "Discover a number rule",
                   "contradiction": "Find the impossible clue",
                   "most-likely": "Choose the most likely explanation",
                   "best-move": "Plan the best next move"},
    "autopilot": {"auto": "Automatic puzzle design"},
    "dictionary": {"auto": "Automatic", "anagram": "Anagram + dictionary clue",
                   "missing-letters": "Missing letters + dictionary clue",
                   "word-order": "Alphabetical ordering"},
    "reasoning": {"auto": "Mix reasoning skills", "deduction": "Multi-clue deduction",
                   "bayesian": "Bayesian evidence", "planning": "Plan the best next question"},
}


@dataclass(frozen=True)
class Topic:
    label: str
    categories: tuple[str, ...]
    types: tuple[str, ...]
    group: str
    difficulty: str


TOPICS = {
    "autopilot": Topic(
        "Autopilot clue designer", tuple(CATEGORIES), (*QUIZ, "riddle"), "Solve It",
        "3 positions; 1/2/3 groups, with questions requiring multiple clues",
    ),
    **{
        name: Topic(
            name.title(),
            ("logic",),
            QUIZ,
            "Think Straight",
            "1, 2 or 3 necessary implication steps",
        )
        for name in ("warehouse", "library", "laboratory", "delivery")
    },
    "ordering": Topic(
        "Ordering and positions", ("logic",), QUIZ, "Solve It", "4, 5 or 6 objects to order"
    ),
    "arithmetic": Topic(
        "Everyday arithmetic",
        ("puzzles",),
        QUIZ,
        "Number Crunch",
        "1, 2 or 3 arithmetic operations",
    ),
    "sequences": Topic(
        "Rule-based sequences",
        ("puzzles", "logic"),
        QUIZ,
        "Sequence Secrets",
        "Addition, multiplication, or alternating rules",
    ),
    "number-riddles": Topic(
        "Number mysteries",
        ("riddles", "puzzles"),
        (*QUIZ, "riddle"),
        "Brain Busters",
        "Increasing search range and number of constraints",
    ),
    "word-riddles": Topic(
        "Reversed-word riddles",
        ("riddles",),
        ("multiple-choice", "type-answer", "riddle"),
        "Tricky Words",
        "Longer words, from 4 to 8 letters",
    ),
    "motion": Topic(
        "Speed and journeys",
        ("science",),
        QUIZ,
        "Physics Fun",
        "One journey, two stages, or a unit conversion",
    ),
    "circuits": Topic(
        "Simple electric circuits",
        ("science",),
        QUIZ,
        "Physics Fun",
        "One resistor, series resistance, or parallel resistance",
    ),
    "density": Topic(
        "Mass and density",
        ("science",),
        QUIZ,
        "Physics Fun",
        "One sample, combined volume, or a unit conversion",
    ),
    "crossword": Topic(
        "Crossword construction",
        ("logic", "riddles", "science", "puzzles"),
        ("crossword",),
        "Word Play",
        "3, 5 or 7 connected clue entries",
    ),
    "growth": Topic(
        "The surprise of doubling",
        ("wonders",),
        ("wonder",),
        "Mind Stretchers",
        "More doubling stages and a larger comparison",
    ),
    "probability": Topic(
        "Shared birthdays",
        ("wonders",),
        ("wonder",),
        "Think Deeper",
        "Larger groups and more pairwise comparisons",
    ),
    "pigeonhole": Topic(
        "When a match is inevitable",
        ("wonders",),
        ("wonder",),
        "Think Deeper",
        "A larger collection and a stronger guarantee",
    ),
    "dictionary": Topic(
        "Your topic · dictionary puzzles", tuple(CATEGORIES), TYPES, "Word Play",
        "Longer words, fewer revealed letters, more candidates or crossword entries",
    ),
    "reasoning": Topic(
        "Your topic · reasoning lab", tuple(CATEGORIES), (*QUIZ, "riddle"), "Solve It",
        "2/3/4 minimum supporting clues; 1/2/3 evidence steps; or 4/5/6 planning hypotheses",
    ),
    "logic-grid": Topic(
        "Custom rules and logic grids", tuple(CATEGORIES), (*QUIZ, "riddle"), "Solve It",
        "Complexity comes from your groups and rules; additional clues ensure uniqueness",
    ),
    "activities": Topic(
        "Discovery and decision activities", tuple(CATEGORIES), (*QUIZ, "riddle"), "Solve It",
        "Larger rule families, longer clue chains, more readouts or larger route maps",
    ),
}


def lesson_group(category: str, topic: str) -> str:
    if topic in ("dictionary", "reasoning", "logic-grid", "activities"):
        return {"logic": "Solve It", "riddles": "Tricky Words", "science": "Science Mix",
                "puzzles": "Word Play", "wonders": "Think Deeper"}[category]
    if topic == "crossword":
        return {
            "logic": "Think Straight",
            "riddles": "Tricky Words",
            "science": "Science Mix",
            "puzzles": "Word Play",
        }[category]
    if topic == "sequences" and category == "logic":
        return "Spot the Pattern"
    if topic == "number-riddles" and category == "puzzles":
        return "Number Crunch"
    return TOPICS[topic].group


@dataclass(frozen=True)
class Request:
    topic: str = "warehouse"
    qtype: str = "multiple-choice"
    difficulty: str = "medium"
    count: int = 1
    seed: int = 0
    category: str = "logic"
    subject: str = ""
    sense: str = ""
    variation: str = "auto"
    search_effort: str = "balanced"
    topic_mode: str = "single"
    meanings: dict[str, str] = field(default_factory=dict)
    instructions: str = ""
    grid: dict | None = None
    crossword_size: int | None = None
    engine_revision: int = 4

    def __post_init__(self) -> None:
        from .topics import validate_meanings

        if type(self.engine_revision) is not int or self.engine_revision not in (1, 2, 3, 4):
            raise ValueError("Unsupported engine revision")

        # The UI label is singular; BrainBloom's stored category is plural.
        if self.category == "wonder":
            object.__setattr__(self, "category", "wonders")
        for name in ("category", "topic", "qtype", "difficulty"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be text")
        for name, limit in (("subject", 200), ("sense", 80), ("variation", 30)):
            if not isinstance(getattr(self, name), str) or len(getattr(self, name)) > limit:
                raise ValueError(f"{name} must be text of at most {limit} characters")
        if not isinstance(self.instructions, str) or len(self.instructions) > 1000:
            raise ValueError("Instructions must be text of at most 1000 characters")
        if self.topic == "logic-grid":
            from .logic_grid import parse

            parse(self.grid)
        elif self.grid is not None:
            raise ValueError("Custom groups and rules require the logic-grid activity")
        if self.crossword_size is not None and (
            type(self.crossword_size) is not int or not 5 <= self.crossword_size <= 15
        ):
            raise ValueError("Crossword board size must be between 5 and 15")
        if self.qtype != "crossword" and self.crossword_size is not None:
            raise ValueError("Board size applies only to Crossword")
        validate_meanings(self.meanings)
        if self.topic in ("autopilot", "activities"):
            if self.sense:
                raise ValueError("This activity uses a selected meaning for each topic")
            if self.topic_mode not in ("single", "combined"):
                raise ValueError("Topic mode must be single or combined")
            object.__setattr__(self, "topic_mode", "combined")
        if not isinstance(self.topic_mode, str) or self.topic_mode not in ("single", "combined"):
            raise ValueError("Topic mode must be single or combined")
        if self.topic_mode == "combined":
            if self.topic not in VARIATIONS or self.sense:
                raise ValueError(
                    "Combined topics require per-topic meanings and a topic-based activity"
                )
        elif self.meanings:
            raise ValueError("Use combined topic mode to select a meaning for every topic")
        if self.variation not in VARIATIONS.get(self.topic, {"auto": "Automatic"}):
            raise ValueError("Choose a supported variation for this generator")
        if self.topic not in VARIATIONS and (self.subject or self.sense):
            raise ValueError("Choose dictionary or reasoning to use your own topic")
        if (not isinstance(self.search_effort, str)
                or self.search_effort not in ("quick", "balanced", "thorough")):
            raise ValueError("Search effort must be quick, balanced, or thorough")
        if self.topic != "reasoning" and self.search_effort != "balanced":
            raise ValueError("Search effort applies to the reasoning lab")
        if self.qtype in ("crossword", "wonder") and self.variation != "auto":
            raise ValueError("Crossword and Wonder use their own rules; choose automatic variation")
        if self.category not in CATEGORIES:
            raise ValueError(f"Choose a category: {', '.join(CATEGORIES)}")
        if self.qtype not in TYPES:
            raise ValueError(f"Choose a question type: {', '.join(TYPES)}")
        if self.topic not in TOPICS:
            raise ValueError(f"Choose a supported topic: {', '.join(TOPICS)}")
        topic = TOPICS[self.topic]
        if self.category not in topic.categories or self.qtype not in topic.types:
            raise ValueError("This topic does not support the selected category and question type")
        if self.difficulty not in DIFFICULTIES:
            raise ValueError("Difficulty must be easy, medium, or hard")
        if type(self.count) is not int or not 1 <= self.count <= 20:
            raise ValueError("Count must be an integer from 1 to 20")
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("Seed must be an integer from 0 to 4294967295")


def configuration() -> dict:
    return {
        "categories": CATEGORIES,
        "types": TYPES,
        "difficulty": DIFFICULTIES,
        "variations": VARIATIONS,
        "topics": {
            key: {
                "label": value.label,
                "categories": value.categories,
                "types": value.types,
                "difficulty": value.difficulty,
            }
            for key, value in TOPICS.items()
        },
    }
