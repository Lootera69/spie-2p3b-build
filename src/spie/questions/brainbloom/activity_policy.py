"""Creator eligibility and presentation, separate from saved puzzle verification.

Legacy activity identifiers stay valid for explicit requests and replay. This policy
controls which activities the creator recommends and how deliberate choices are named.
"""

from __future__ import annotations

from dataclasses import dataclass

PATTERN_TRUE_FALSE_UNAVAILABLE = (
    "Number-rule true/false is unavailable because the current design can reveal "
    "the verdict without combining the observations. "
    "Choose multiple choice, typed answer or riddle."
)

COLLECTIONS = {
    "core": {
        "label": "Core puzzles",
        "description": "Combine clues, design a logic grid or connect words in a crossword.",
    },
    "practice": {
        "label": "Practice",
        "description": "Deliberate word, number, science and rule exercises.",
    },
    "experimental": {
        "label": "Experimental",
        "description": (
            "Answers are checked, but challenge and variety are still being improved. "
            "Choose an activity to try."
        ),
    },
    "explore": {
        "label": "Explore — unscored",
        "description": "Unscored demonstrations and word explorations, with no skill rating.",
    },
}


@dataclass(frozen=True)
class ActivityPolicy:
    collection: str
    automatic: bool = False
    canonical: str = ""
    note: str = ""


POLICIES = {
    "deduction": ActivityPolicy("core", automatic=True),
    "autopilot": ActivityPolicy("core", automatic=True),
    "logic-grid": ActivityPolicy("core"),
    "crossword": ActivityPolicy("core", automatic=True),
    **{activity: ActivityPolicy("practice") for activity in (
        "best-move", "anagram", "missing-letters", "word-order", "arithmetic",
        "sequences", "number-riddles", "ordering", "word-riddles", "motion",
        "circuits", "density", "warehouse", "library", "laboratory", "delivery",
    )},
    **{activity: ActivityPolicy("experimental") for activity in (
        "contradiction", "pattern", "resource-plan", "state-planning", "planning", "bayesian",
    )},
    "most-likely": ActivityPolicy(
        "experimental", canonical="bayesian", note="This activity is now Weigh the evidence.",
    ),
    **{activity: ActivityPolicy("explore", automatic=activity in ("word-wonder", "growth"))
       for activity in ("word-wonder", "growth", "probability", "pigeonhole")},
}


def canonical_activity(activity: str) -> str:
    policy = POLICIES.get(activity)
    return policy.canonical or activity if policy else activity


def metadata(activity: str) -> dict:
    policy = POLICIES[activity]
    return {
        "collection": policy.collection,
        "automatic": policy.automatic,
        "visible": not bool(policy.canonical),
        "canonical_id": canonical_activity(activity),
        "policy_note": policy.note,
        "menu_order": list(POLICIES).index(activity),
    }


def automatic_activities(qtype: str, collection: str) -> tuple[str, ...]:
    # Choosing an explicitly unscored format is itself a deliberate exploration.
    # Never fall back to a practice/experimental generator for a scored puzzle.
    if qtype == "wonder":
        candidates = ("word-wonder", "growth")
    elif qtype == "crossword":
        candidates = ("crossword",)
    else:
        candidates = ("deduction", "autopilot") if collection == "core" else ()
    return tuple(activity for activity in candidates if POLICIES[activity].automatic)


def selection(activity: str, collection: str, qtype: str) -> dict:
    if activity in POLICIES:
        collection = POLICIES[activity].collection
    elif qtype == "wonder":
        collection = "explore"
    elif qtype == "crossword":
        collection = "core"
    details = COLLECTIONS[collection]
    return {
        "selected_collection": collection,
        "collection_label": details["label"],
        "policy_notice": details["description"],
    }
