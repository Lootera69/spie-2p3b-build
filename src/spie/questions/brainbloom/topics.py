"""Resolve every supplied topic automatically and preserve explicit meaning overrides."""

from __future__ import annotations

import re
from difflib import get_close_matches

from ...forge.corpus import digest
from .lexicon import STOP, Dictionary, _key, _tokens
from .vocabulary import ALIASES, PACKS

MAX_TOPICS = 6


def _matches(dictionary: Dictionary, term: str) -> list[dict]:
    return dictionary._matches(term)


def validate_meanings(meanings: object) -> None:
    if not isinstance(meanings, dict) or len(meanings) > MAX_TOPICS:
        raise ValueError("Choose a meaning for each of up to six topics")
    for term, sense in meanings.items():
        if (not isinstance(term, str) or not 1 <= len(term) <= 200
                or not isinstance(sense, str) or not 1 <= len(sense) <= 80):
            raise ValueError("Each topic meaning must have a topic name and a meaning ID")


def _segments(dictionary: Dictionary, subject: str) -> tuple[list[dict], list[str]]:
    """Longest non-overlapping dictionary phrases, preserving input order and unknown words."""
    phrase = _key(subject)
    direct = _matches(dictionary, phrase)
    if direct:
        return [{"term": phrase, "choices": direct}], []
    groups, unknown, seen = [], [], set()
    for chunk in re.split(r"[,;\n]+", subject):
        tokens = _tokens(_key(chunk))
        cursor = 0
        while cursor < len(tokens):
            # A known compound takes precedence over its component words and fillers.
            found = None
            for length in range(min(6, len(tokens) - cursor), 0, -1):
                term = " ".join(tokens[cursor:cursor + length])
                if length == 1 and term in STOP:
                    continue
                matches = _matches(dictionary, term)
                if matches:
                    found = term, length, matches
                    break
            if found is None:
                token = tokens[cursor]
                if token not in STOP and token not in unknown:
                    unknown.append(token)
                cursor += 1
                continue
            term, length, choices = found
            if term not in seen:
                seen.add(term)
                groups.append({"term": term, "choices": choices})
            cursor += length
    return groups, unknown


def lookup_many(
    dictionary: Dictionary, subject: str, meanings: dict[str, str] | None = None,
    category: str = "puzzles", *, strict: bool = False,
) -> dict:
    if not isinstance(subject, str) or len(subject) > 200:
        raise ValueError("Enter up to 200 characters of topics, separated by commas")
    meanings = {} if meanings is None else meanings
    validate_meanings(meanings)
    text = subject.strip() or category
    groups, unknown = _segments(dictionary, text)
    if len(groups) > MAX_TOPICS:
        raise ValueError("Use at most six topics in one puzzle; every topic must fit")
    keys = {g["term"] for g in groups}
    if strict and set(meanings) - keys:
        raise ValueError(
            "Some selected meanings no longer belong to your topics. Check topics again."
        )
    selected, components = {}, []
    for group in groups:
        choices = group["choices"]
        override = meanings.get(group["term"], "")
        if override and not any(c["id"] == override for c in choices):
            if strict:
                raise ValueError(f"Choose a current meaning for '{group['term']}'")
            override = ""
        chosen, selection = dictionary.select(choices, override, context=text)
        group.update(selected=chosen["id"], selection=selection,
                     selection_mode=selection["mode"], selection_reason=selection["reason"])
        selected[group["term"]] = chosen["id"]
        entries, source = dictionary._entries(chosen["id"])
        group["word_count"] = len(entries)
        components.append({"term": group["term"], "sense": chosen["id"],
                           "definition": chosen["definition"], "entries": entries,
                           "source": source})
    report = {
        "subject": subject, "using_category": not bool(subject.strip()), "groups": groups,
        "meanings": selected, "unknown_terms": unknown,
        "suggestions": {word: get_close_matches(
                            word, [*PACKS, *ALIASES, *dictionary.coverage_index], n=3, cutoff=0.65)
                        for word in unknown},
    }
    if unknown or not groups:
        return {**report, "status": "unknown", "message": (
            "Please correct or replace these words: " + ", ".join(unknown)
            if unknown else "Enter a topic word, such as space, animals or ocean."
        )}
    try:
        context = _combine(text, components)
    except ValueError as exc:
        return {**report, "status": "limited", "message": str(exc)}
    return {**report, "status": "ready", "context": context,
            "message": f"All {len(groups)} topics are ready, with {len(context['entries'])} words."}


def resolve_many(dictionary: Dictionary, subject: str, meanings: dict, category: str) -> dict:
    report = lookup_many(dictionary, subject, meanings, category, strict=True)
    if report["status"] != "ready":
        raise ValueError(report["message"])
    return report["context"]


def _combine(subject: str, components: list[dict]) -> dict:
    # Round-robin admission prevents a large topic from crowding out a small one.
    # One spelling has one clue meaning in a puzzle. Homonymous meanings remain
    # separate in the topic records and cannot silently claim the same entry.
    entries, owners = {}, {}
    for depth in range(max((len(c["entries"]) for c in components), default=0)):
        for component in components:
            if depth >= len(component["entries"]):
                continue
            entry = component["entries"][depth]
            word = entry["word"]
            if word not in entries and len(entries) < 80:
                entries[word] = entry
                owners[word] = []
            if word in entries and entries[word]["sense"] == entry["sense"]:
                owners[word].append(component["term"])
    topics, sources = [], []
    for component in components:
        words = [word for word in entries if component["term"] in owners[word]]
        if not words:
            raise ValueError(f"'{component['term']}' has no usable words in this meaning. "
                             "Choose another meaning or a broader topic.")
        anchor = re.sub(r"[\s-]", "", component["term"]).upper()
        if anchor not in words:
            anchor = next((e["word"] for e in component["entries"]
                           if e["sense"] == component["sense"] and e["word"] in words), None)
        topics.append({
            "term": component["term"], "sense": component["sense"],
            "definition": component["definition"], "words": words,
            "anchor": anchor,
            "source_sha256": component["source"]["sha256"],
        })
        if component["source"] not in sources:
            sources.append(component["source"])
    if len(entries) < 4:
        raise ValueError("These topics provide fewer than four usable words. Add a related topic "
                         "or choose a broader meaning.")
    context = {
        "subject": subject, "sense": "combined:" + digest(topics),
        "label": ", ".join(c["term"] for c in components),
        "definition": "A puzzle combining all the selected topic meanings.",
        "topics": topics, "entries": list(entries.values()), "sources": sources,
        "source": {"name": "; ".join(dict.fromkeys(s["name"] for s in sources)),
                   "sha256": digest(sources),
                   "license": "\n\n".join(dict.fromkeys(s["license"] for s in sources))},
    }
    validate_topics(context)
    return context


def validate_topics(context: dict) -> None:
    topics = context.get("topics")
    if not isinstance(topics, list) or not 1 <= len(topics) <= MAX_TOPICS:
        raise ValueError("A combined puzzle needs one to six topic records")
    sources = context.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_TOPICS:
        raise ValueError("Combined topics must retain their dictionary sources")
    for source in sources:
        if not isinstance(source, dict) or any(not isinstance(source.get(k), str) or not source[k]
                                              for k in ("name", "sha256", "license")):
            raise ValueError("Invalid combined-topic source")
    words = {e["word"] for e in context["entries"]}
    terms, covered = set(), set()
    for topic in topics:
        if not isinstance(topic, dict) or set(topic) != {
            "term", "sense", "definition", "words", "anchor", "source_sha256",
        }:
            raise ValueError("Invalid combined topic record")
        if any(not isinstance(topic[k], str) or not 1 <= len(topic[k]) <= 2000
               for k in ("term", "sense", "definition", "source_sha256")):
            raise ValueError("Invalid topic text")
        if topic["term"] in terms:
            raise ValueError("Repeated combined topic")
        terms.add(topic["term"])
        if (not isinstance(topic["words"], list) or not topic["words"]
                or any(not isinstance(w, str) or w not in words for w in topic["words"])
                or len(set(topic["words"])) != len(topic["words"])):
            raise ValueError("A topic refers to missing or repeated vocabulary")
        if topic["anchor"] is not None and topic["anchor"] not in topic["words"]:
            raise ValueError("A topic's requested word is not in its vocabulary")
        if topic["source_sha256"] not in {s["sha256"] for s in sources}:
            raise ValueError("A topic's dictionary source is missing")
        covered.update(topic["words"])
    if covered != words or context["sense"] != "combined:" + digest(topics):
        raise ValueError("Combined-topic vocabulary or identity is inconsistent")
    source = context["source"]
    if (source["sha256"] != digest(sources)
            or source["license"] != "\n\n".join(dict.fromkeys(s["license"] for s in sources))
            or source["name"] != "; ".join(dict.fromkeys(s["name"] for s in sources))):
        raise ValueError("Combined-topic attribution is inconsistent")
    # Verify a distinct representative is possible for every topic, including
    # literal input words when those words are available in the chosen meaning.
    representatives(context)


def representatives(context: dict, rng=None) -> list[str]:
    topics = context["topics"]
    options = []
    for topic in topics:
        words = [topic["anchor"]] if topic["anchor"] else list(topic["words"])
        if rng is not None:
            rng.shuffle(words)
        options.append(words)
    order = sorted(range(len(topics)), key=lambda i: len(options[i]))
    assigned = {}

    def visit(depth, used):
        if depth == len(order):
            return True
        index = order[depth]
        for word in options[index]:
            if word not in used:
                assigned[index] = word
                if visit(depth + 1, used | {word}):
                    return True
        assigned.pop(index, None)
        return False

    if not visit(0, set()):
        raise ValueError("These meanings overlap too much to give every topic a distinct word. "
                         "Combine duplicate topics or choose different meanings.")
    return [assigned[i] for i in range(len(topics))]


def sample_words(context: dict, count: int, rng) -> list[str]:
    required = representatives(context, rng)
    if len(required) > count:
        raise ValueError(f"This activity has room for {count} words but you supplied "
                         f"{len(required)} topics. Choose a larger puzzle or fewer topics.")
    pool = [e["word"] for e in context["entries"] if e["word"] not in required]
    if count > len(context["entries"]):
        raise ValueError(f"This activity needs {count} different words; these topics have "
                         f"{len(context['entries'])}. Choose an easier level or add a topic.")
    words = [*required, *rng.sample(pool, count - len(required))]
    rng.shuffle(words)
    return words


def coverage(context: dict, used_words: list[str]) -> list[dict]:
    used = set(used_words)
    if not used <= {entry["word"] for entry in context["entries"]}:
        raise RuntimeError("The puzzle used a word outside the selected topics")
    report = []
    for topic in context["topics"]:
        words = sorted(used.intersection(topic["words"]))
        if not words or (topic["anchor"] and topic["anchor"] not in used):
            raise RuntimeError(f"The generated puzzle omitted the topic '{topic['term']}'")
        report.append({"term": topic["term"], "sense": topic["sense"], "used_words": words})
    return report
