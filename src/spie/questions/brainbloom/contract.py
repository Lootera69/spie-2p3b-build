"""Quiz contract plus native crossword and unscored Wonder contracts."""

from ...forge.contract import COMMON, GROUPS, XP
from ...forge.contract import issues as quiz_issues
from .crossword import validate_grid


def issues(item: object) -> list[str]:
    if not isinstance(item, dict) or item.get("type") not in ("crossword", "wonder"):
        return quiz_issues(item)
    kind = item["type"]
    expected = COMMON | ({"crosswordData"} if kind == "crossword" else {"sharePrompt"})
    errors = []
    if set(item) != expected:
        errors.append("field-set")
    for key in COMMON - {"choices", "xpReward"}:
        if not isinstance(item.get(key), str) or not item[key].strip():
            errors.append(f"text:{key}")
    if errors:
        return errors
    if item["category"] not in GROUPS or item["lessonGroup"] not in GROUPS[item["category"]]:
        errors.append("lesson-group")
    if item["difficulty"] not in XP:
        errors.append("difficulty")
    if item.get("choices") != []:
        errors.append("unexpected-choices")
    reward = 0 if kind == "wonder" else XP.get(item["difficulty"])
    if type(item.get("xpReward")) is not int or item["xpReward"] != reward:
        errors.append("xp-reward")
    if kind == "wonder":
        if not isinstance(item.get("sharePrompt"), str) or not item["sharePrompt"].strip():
            errors.append("share-prompt")
    else:
        try:
            if not isinstance(item.get("crosswordData"), dict):
                raise ValueError("Missing grid")
            validate_grid(item["crosswordData"])
        except (ValueError, TypeError, KeyError):
            errors.append("crossword-grid")
    return errors
