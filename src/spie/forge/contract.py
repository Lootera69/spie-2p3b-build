"""BrainBloom's quiz wire contract. Shape checking is NOT answer verification."""

from __future__ import annotations

import re
import unicodedata

GROUPS = {
    "logic": (
        "Think Straight", "Spot the Pattern", "Solve It", "Master Mind",
        "Fallacy Field Guide", "Paradox Alley", "Mind the Odds", "Decision Frames",
        "Lateral Leaps", "Argument Repair", "Map & Territory",
    ),
    "science": (
        "Body & Biology", "Physics Fun", "Earth & Space", "Crazy Chemistry", "Science Mix",
        "Quantum Café", "Relativity Road", "Mind Machinery", "Deep Time", "Fermi's Notebook",
    ),
    "riddles": (
        "Classic Riddles", "Funny Business", "Tricky Words", "Brain Busters",
        "Paradox Riddles", "Modern Twists",
    ),
    "puzzles": (
        "Number Crunch", "Word Play", "Think Different", "Bonus Round", "Scale Stories",
        "Sequence Secrets",
    ),
    "wonders": (
        "Think Deeper", "Mind Stretchers", "Cosmic Wonders", "Life Puzzles", "Mind Mirrors",
        "Poet's Corner",
    ),
}
TYPES = ("multiple-choice", "true-false", "type-answer", "riddle")
XP = {"easy": 10, "medium": 25, "hard": 50}
TEXT_FIELDS = {
    "type", "category", "difficulty", "title", "question", "correctAnswer",
    "correctExplanation", "incorrectExplanation", "lessonContent", "lessonGroup",
}
COMMON = TEXT_FIELDS | {"choices", "xpReward"}


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return " ".join(re.findall(r"\w+", text))


def canonical_item(item: dict) -> dict:
    """Only normalize documented legacy omissions; never rewrite answers or prose."""
    result = {k: v for k, v in item.items() if k not in {"forgeId", "forgeScore"}}
    if result.get("type") in {"riddle", "type-answer"}:
        result.setdefault("choices", [])
    group = result.get("lessonGroup")
    if isinstance(group, str):
        result["lessonGroup"] = group.replace("’", "'")
    return result


def issues(item: object) -> list[str]:
    if not isinstance(item, dict):
        return ["item-not-object"]
    errors = []
    kind = item.get("type")
    if not isinstance(kind, str):
        return ["text:type"]
    expected = COMMON | ({"acceptedAnswers"} if kind in {"type-answer", "riddle"} else set())
    if kind == "riddle":
        expected |= {"hintText"}
    if set(item) != expected:
        errors.append("field-set")
    for key in TEXT_FIELDS:
        if not isinstance(item.get(key), str) or not item[key].strip():
            errors.append(f"text:{key}")
    if errors:
        return errors
    if kind not in TYPES:
        errors.append("type")
    if item["category"] not in GROUPS:
        errors.append("category")
    elif item["lessonGroup"] not in GROUPS[item["category"]]:
        errors.append("lesson-group")
    if item["difficulty"] not in XP:
        errors.append("difficulty")
    elif type(item.get("xpReward")) is not int or item["xpReward"] != XP[item["difficulty"]]:
        errors.append("xp-reward")
    choices = item.get("choices")
    if (not isinstance(choices, list)
            or any(not isinstance(c, str) or not c.strip() for c in choices)):
        errors.append("choices")
    elif kind in {"multiple-choice", "true-false"}:
        if kind == "multiple-choice" and len(choices) != 4:
            errors.append("choice-count")
        if kind == "true-false" and choices != ["True", "False"]:
            errors.append("true-false-choices")
        if len(set(map(normalized, choices))) != len(choices):
            errors.append("duplicate-choice")
        if choices.count(item["correctAnswer"]) != 1:
            errors.append("answer-choice")
    elif choices:
        errors.append("unexpected-choices")
    if kind in {"riddle", "type-answer"}:
        accepted = item.get("acceptedAnswers")
        if (not isinstance(accepted, list) or not 3 <= len(accepted) <= 6
                or any(not isinstance(a, str) or not a.strip() for a in accepted)):
            errors.append("accepted-answers")
        elif normalized(item["correctAnswer"]) not in set(map(normalized, accepted)):
            errors.append("canonical-answer-not-accepted")
    if kind == "riddle":
        hint = item.get("hintText")
        if not isinstance(hint, str) or not 2 <= len(hint.strip().splitlines()) <= 3:
            errors.append("riddle-hints")
    lines = item["lessonContent"].strip().splitlines()
    if not 4 <= len(lines) <= 6 or not lines[-1].startswith("Share this:"):
        errors.append("lesson-lines")
    return errors
