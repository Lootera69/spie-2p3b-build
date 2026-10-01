"""A bounded, auditable English instruction grammar. No language model or code execution.

Every content token must be accounted for. Recognising one keyword never licenses
silently ignoring the rest of a request or inventing a new puzzle rule.
"""

from __future__ import annotations

import re

VERSION = "brainbloom-instructions-v1"
MAX_LENGTH = 1000
EXAMPLES = (
    "Make 3 hard multiple-choice puzzles. Players should solve a set of clues.",
    "Create a crossword about plants and animals.",
    "Unscramble a word. Include topics: space, ocean.",
    "Choose the best next question. Use typed answers.",
)
NUMBERS = {word: i for i, word in enumerate((
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split())}
ACTIVITY_PATTERNS = {
    "autopilot": (r"design (?:a )?clue puzzle for me", r"autopilot(?: clue designer)?"),
    "contradiction": (r"find (?:the )?impossible clue", r"spot (?:the )?contradiction"),
    "most-likely": (r"(?:choose|find) (?:the )?most likely explanation",),
    "best-move": (r"plan (?:the )?best next move", r"choose (?:the )?best next move"),
    "pattern": (r"discover (?:a |the )?number rule", r"spot (?:the )?number pattern"),
    "logic-grid": (r"(?:create|build|solve) (?:a )?(?:custom )?logic grid",),
    "deduction": (
        r"(?:solve|combine|follow|use) (?:a |the )?(?:set of )?(?:logical )?clues",
        r"(?:logic|deduction|deductive) puzzles?",
        r"arrange (?:the )?cards (?:using|with) clues",
    ),
    "bayesian": (
        r"weigh (?:the )?evidence", r"(?:bayesian|probabilistic) reasoning",
        r"(?:find|choose) (?:the )?most likely (?:hidden )?(?:card|answer)",
        r"update probabilities (?:using|with|from) (?:new )?evidence",
    ),
    "planning": (
        r"choose (?:the )?best next question",
        r"identify (?:the )?hidden card (?:in|using) (?:the )?fewest questions",
        r"plan (?:the )?(?:best|optimal) questions",
    ),
    "anagram": (r"unscramble (?:a |the )?(?:word|words|letters)",
                r"rearrange (?:the )?letters", r"anagrams?"),
    "missing-letters": (r"(?:find|fill(?: in)?) (?:the )?missing letters",),
    "word-order": (r"put (?:the )?words in (?:alphabetical )?order",
                   r"sort (?:the )?words alphabetically"),
    "crossword": (r"connect words in (?:a )?crossword",),
    "word-wonder": (r"explore patterns in words", r"(?:explore|count) letter arrangements"),
    "arithmetic": (r"(?:solve )?(?:an? )?(?:everyday )?(?:arithmetic|number) problems?",),
    "sequences": (r"find (?:the )?next number",
                  r"(?:follow|solve) (?:a )?number (?:pattern|sequence)"),
    "number-riddles": (r"guess (?:the )?hidden number",),
    "ordering": (r"work out positions",),
    "word-riddles": (r"reverse (?:a |the )?word",),
    "motion": (r"calculate (?:speed and journeys|speed)",),
    "circuits": (r"solve (?:a )?(?:simple )?circuit",),
    "density": (r"calculate mass and volume",),
    "growth": (r"explore (?:how )?doubling(?: works)?",),
    "probability": (r"explore shared birthdays",),
    "pigeonhole": (r"explore when a match is certain",),
    "warehouse": (r"follow rules about parcels",),
    "library": (r"follow rules about books",),
    "laboratory": (r"follow rules about samples",),
    "delivery": (r"follow delivery rules",),
}
FILLERS = set((
    "please i we want would like can could you make create generate design build "
    "a an the puzzle puzzles question questions draft drafts player players should "
    "to for me us and then using with use in this it them these be let difficulty level"
).split())


def interpret(text: str) -> dict:
    if not isinstance(text, str) or len(text) > MAX_LENGTH:
        raise ValueError(f"Instructions must be text of at most {MAX_LENGTH} characters")
    text = " ".join(text.replace("\n", "; ").replace("’", "'").casefold().split())
    remaining = list(text)
    fields, matches, issues, includes = {}, [], [], []

    def masked():
        return "".join(remaining)

    def bind(key, value, match):
        if key in fields and fields[key] != value:
            issues.append(f"The instructions give conflicting values for {key}.")
        else:
            fields[key] = value
        matches.append({"text": text[match.start():match.end()], "setting": key, "value": value})
        remaining[match.start():match.end()] = " " * (match.end() - match.start())

    # Whole labels containing 'about' must be matched before topic clauses.
    for key in ("warehouse", "library", "laboratory"):
        pattern = "|".join(ACTIVITY_PATTERNS[key]).replace(" ", r"\s+")
        for match in re.finditer(r"\b(?:" + pattern + r")\b", masked()):
            bind("activity", key, match)
    topic_pattern = (
        r"\b(?P<directive>about|topics?\s*:|"
        r"(?:include|add|use) (?:the )?(?:topics?|words?|keywords?)\s*:?)\s*"
        r"(?P<topics>[^.;!?]+)"
    )
    for match in re.finditer(topic_pattern, masked()):
        topic = match.group("topics").strip().strip('"\'')
        if re.search(
            r"\b(?:with|without|using|where|whose|that|must|should|exactly|except|only|not|no)\b",
            topic,
        ):
            issues.append("Topic clauses only list topics. Put extra requirements in a separate "
                          "sentence so they can be checked.")
        if not topic:
            issues.append("List the topics after 'about' or 'Include topics:'.")
        elif match.group("directive").startswith(("include", "add", "use")):
            includes.append(topic)
            matches.append({"text": match.group(), "setting": "include_topics", "value": topic})
            remaining[match.start():match.end()] = " " * (match.end() - match.start())
        else:
            bind("subject", topic, match)
    number = r"(?:\d+|" + "|".join(NUMBERS) + r")"
    count_pattern = (
        rf"(?<![\w.\-])(?P<number>{number})\s+"
        r"(?:(?:easy|simple|medium|moderate|hard|challenging|multiple[- ]choice|"
        r"true\s*(?:/|or|-)\s*false|typed[- ]answer)\s+)*"
        r"(?:puzzles?|questions?|riddles?|crosswords?|drafts?|anagrams?)\b"
    )
    for match in re.finditer(count_pattern, masked()):
        token = match.group("number")
        value = int(token) if token.isdecimal() else NUMBERS[token]
        # Consume just the number; other settings in the same phrase still need parsing.
        start, end = match.start(), match.start() + len(token)
        if "count" in fields and fields["count"] != value:
            issues.append("The instructions request different puzzle counts.")
        fields["count"] = value
        matches.append({"text": token, "setting": "count", "value": value})
        remaining[start:end] = " " * (end - start)
        if not 1 <= value <= 20:
            issues.append("Request between 1 and 20 puzzles.")
    for value, pattern in (
        ("easy", r"easy|simple|beginner"), ("medium", r"medium|moderate"),
        ("hard", r"hard|challenging|advanced"),
    ):
        for match in re.finditer(r"\b(?:" + pattern + r")\b", masked()):
            bind("difficulty", value, match)
    # Match activities before format words: 'number riddles' must not lose its noun.
    for key, patterns in ACTIVITY_PATTERNS.items():
        pattern = "|".join(patterns).replace(" ", r"\s+")
        for match in re.finditer(r"\b(?:" + pattern + r")\b", masked()):
            bind("activity", key, match)
    for value, pattern in (
        ("multiple-choice", r"multiple[- ]choice|mcq"),
        ("true-false", r"true\s*(?:/|or|-)\s*false"),
        ("type-answer", r"(?:typed|type|text)[- ]answers?|type (?:their|the|an?) answers?"),
        ("crossword", r"crosswords?"), ("riddle", r"riddles?"),
        ("wonder", r"wonders?|unscored reflections?"),
    ):
        for match in re.finditer(r"\b(?:" + pattern + r")\b", masked()):
            bind("qtype", value, match)
    if fields.get("qtype") == "crossword":
        if fields.get("activity", "crossword") != "crossword":
            issues.append("A crossword cannot use the other requested activity.")
        fields["activity"] = "crossword"
    if fields.get("activity") == "crossword":
        if fields.get("qtype", "crossword") != "crossword":
            issues.append("Crossword instructions require the Crossword answer format.")
        fields["qtype"] = "crossword"
    if fields.get("activity") == "word-wonder":
        if fields.get("qtype", "wonder") != "wonder":
            issues.append("Letter-arrangement reflections use the Wonder answer format.")
        fields["qtype"] = "wonder"
    unrecognised = [token for token in re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", masked())
                    if token not in FILLERS]
    if unrecognised:
        issues.append("I cannot apply this part yet: " + " ".join(unrecognised) + ".")
    if not matches and not issues:
        issues.append("Describe an activity or setting, for example: 'Unscramble a word'.")
    if "subject" in fields and len(fields["subject"]) > 200:
        issues.append("Keep the topic list within 200 characters.")
    return {"version": VERSION, "status": "supported" if not issues else "clarify",
            "fields": fields, "include_topics": includes, "matches": matches,
            "unrecognised": unrecognised, "issues": list(dict.fromkeys(issues))}


def combined_subject(base: str, report: dict) -> str:
    subject = report["fields"].get("subject", base).strip()
    for addition in report["include_topics"]:
        existing = re.findall(r"\w+", subject.casefold())
        extra = re.findall(r"\w+", addition.casefold())
        if not any(existing[i:i + len(extra)] == extra for i in range(len(existing) + 1)):
            subject = ", ".join(part for part in (subject, addition) if part)
    return subject


def validate_request(request) -> dict:
    """Bind interpreted instructions to the actual engine settings, including on replay."""
    from .brief import ACTIVITIES

    report = interpret(request.instructions)
    if report["status"] != "supported":
        raise ValueError(" ".join(report["issues"]))
    fields = report["fields"]
    for key in ("count", "difficulty", "qtype"):
        if key in fields and fields[key] != getattr(request, key):
            raise ValueError(f"The {key} setting does not match the written instructions")
    if "activity" in fields:
        activity = ACTIVITIES[fields["activity"]]
        if request.topic != activity.family or request.variation != activity.variation:
            raise ValueError("The puzzle activity does not match the written instructions")
    if combined_subject(request.subject, report).casefold() != request.subject.strip().casefold():
        raise ValueError("The topics do not match the written instructions")
    return report
