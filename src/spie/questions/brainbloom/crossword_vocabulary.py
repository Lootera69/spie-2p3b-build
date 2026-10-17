"""Revision-16 learning vocabulary: fixed, offline and replayable.

Only historical requests use this policy; new requests use crossword_corpus.py.
Corpus rarity is a screening signal, not a claim about an individual learner.
Authored specialist entries can be rarer than the corpus floor. We never relax
the policy to fill a small board or to meet a requested batch count.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files

from ...forge.corpus import digest
from .crossword_learning_words import BANKS
from .lexicon import validate_context
from .topics import _combine

MIN_ZIPF = 1.5
MAX_ZIPF = 3.5
CURATED_MAX_ZIPF = 4
BAD_CLUE = re.compile(
    r"\[entry\]|\b(?:archaic|obsolete|offensive|derogatory|slur|vulgar|abbreviation|"
    r"acronym|initialism|surname|given name|genus|taxonomic|misspelling)\b", re.I)
LESSON = (
    "Discover less familiar words through their meanings.\n"
    "Start with a clue you recognize, then use word lengths and crossing letters.\n"
    "After solving or revealing the answers, review each word and its definition."
)


@lru_cache(maxsize=1)
def frequencies() -> dict:
    return json.loads(files(__package__).joinpath(
        "data/crossword-frequency-v1.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def policy() -> dict:
    return {"version": 1, "frequency_sha256": digest(frequencies()),
            "dictionary_zipf_range": [MIN_ZIPF, MAX_ZIPF],
            "curated_max_zipf": CURATED_MAX_ZIPF, "bank_sha256": digest(BANKS)}


def eligible(word: str, clue: str) -> bool:
    if (not re.fullmatch(r"[A-Z]{3,15}", word) or len(clue.split()) < 4
            or BAD_CLUE.search(clue)
            or word.lower() in re.findall(r"[a-z]+", clue.lower())):
        return False
    score = frequencies()["zipf"].get(word, 0)
    authored = any((word, clue) in bank for bank in BANKS.values())
    return (score <= CURATED_MAX_ZIPF if authored
            else MIN_ZIPF <= score <= MAX_ZIPF)


def _bank_key(sense: str) -> str | None:
    if sense.startswith("pack:") and sense[5:] in BANKS:
        return sense[5:]
    for topic in BANKS:
        if sense in (f"coverage-v1:{topic.replace(' ', '-')}",
                     f"coverage-v2:{topic.replace(' ', '-')}"):
            return topic
    return None


def _meaning_graph(sense: str) -> bool:
    # WordNet expansion follows this exact sense and its bounded relationships.
    # Authored word:<pack>:<word> instead returns the entire parent pack, so its
    # focal word must remain required to avoid silently changing the topic.
    return sense.startswith(("wn:", "oewn2024:"))


def _source(original: dict, bank: str | None) -> dict:
    return {
        "original_source": deepcopy(original),
        "name": original["name"] + "; BrainBloom learning vocabulary v1",
        "sha256": digest({"original": original, "bank": bank, "policy": policy()}),
        "license": original["license"] + (
            "\n\nAdditional definitions: project-authored. Familiarity selection: "
            "wordfreq 3.1.1 by Robyn Speer, CC BY-SA 4.0; SUBTLEX by Marc Brysbaert "
            "et al. is freely available. See crossword-frequency-attribution.md."
        ),
    }


def _pool(entries: list[dict], bank: str | None) -> list[dict]:
    authored = [{"word": word, "definition": clue,
                 "sense": f"learning-v1:{bank.replace(' ', '-')}:{word.lower()}",
                 "path": [f"learning-v1:{bank}"]}
                for word, clue in BANKS[bank]] if bank else []
    pool = {}
    for entry in [*authored, *entries]:
        if eligible(entry["word"], entry["definition"]):
            pool.setdefault(entry["word"], deepcopy(entry))
    return list(pool.values())[:80]


def _check_anchor(anchor: str | None, entries: list[dict]) -> None:
    if anchor and anchor not in {e["word"] for e in entries}:
        raise ValueError(
            f"{anchor} does not meet the learning-vocabulary policy in this meaning. "
            "Choose a broader topic such as animals, space, plants or science "
            "to discover less familiar related words."
        )


def prepare_context(context: dict) -> dict:
    """Enrich broad roots only, preserve focal meanings, and save the exact pool."""
    validate_context(context)
    if "crossword_learning" in context:
        validate_learning(context)
        return context
    result = deepcopy(context)
    if "topics" in context:
        components = []
        broad = set()
        for topic in context["topics"]:
            bank = _bank_key(topic["sense"])
            if bank or _meaning_graph(topic["sense"]):
                broad.add(topic["term"])
            pool = _pool([e for e in context["entries"] if e["word"] in topic["words"]], bank)
            if not bank and not _meaning_graph(topic["sense"]):
                _check_anchor(topic["anchor"], pool)
            source = next(s for s in context["sources"]
                          if s["sha256"] == topic["source_sha256"])
            components.append({"term": topic["term"], "sense": topic["sense"],
                               "definition": topic["definition"], "entries": pool,
                               "source": _source(source, bank)})
        try:
            result = _combine(context["subject"], components)
        except ValueError as exc:
            raise ValueError("Not enough learning vocabulary for these meanings. "
                             "Choose a broader topic or add a related topic. " + str(exc)) from exc
        for topic in result["topics"]:
            if topic["term"] in broad:
                topic["anchor"] = None
        result["sense"] = "combined:" + digest(result["topics"])
    else:
        bank = _bank_key(context["sense"])
        result["entries"] = _pool(context["entries"], bank)
        if len(result["entries"]) < 4:
            raise ValueError("This meaning has fewer than four suitable learning words. "
                             "Choose a broader topic such as science, plants or space.")
        anchor = None
        if not bank and not _meaning_graph(context["sense"]):
            literal = re.sub(r"[\s-]", "", context["subject"]).upper()
            anchor = next((e["word"] for e in context["entries"]
                           if e["word"] == literal or e["sense"] == context["sense"]), None)
            _check_anchor(anchor, result["entries"])
        result["crossword_anchor"] = anchor
        result["source"] = _source(context["source"], bank)
    result["crossword_learning"] = deepcopy(policy())
    validate_learning(result)
    return result


def validate_learning(context: dict) -> None:
    validate_context(context)
    if context.get("crossword_learning") != policy():
        raise ValueError("Missing or unsupported crossword learning-vocabulary policy")
    if any(not eligible(e["word"], e["definition"]) for e in context["entries"]):
        raise ValueError("Dictionary snapshot contains unsuitable learning vocabulary")
    if "topics" not in context:
        anchor = context.get("crossword_anchor")
        if anchor is not None and not isinstance(anchor, str):
            raise ValueError("Invalid learning crossword anchor")
        _check_anchor(anchor, context["entries"])


def builtin_vocabulary(category: str) -> list[tuple[str, str]]:
    return [(w, c) for w, c in BANKS[category] if eligible(w, c)]


def add_learning(item: dict, proof: dict) -> None:
    clues = item["crosswordData"]["clues"]
    item["lessonContent"] = LESSON
    item["question"] += " Discover less familiar words from their definitions."
    recap = "Vocabulary recap:\n" + "\n".join(f"{c['answer']} — {c['clue']}" for c in clues)
    item["correctExplanation"] += "\n\n" + recap
    item["incorrectExplanation"] += "\n\n" + recap
    proof["learning_vocabulary"] = {
        **deepcopy(policy()), "words": [{"word": c["answer"],
                               "zipf_hundredths": round(
                                   frequencies()["zipf"].get(c["answer"], 0) * 100),
                               "authored": any((c["answer"], c["clue"]) in bank
                                               for bank in BANKS.values())} for c in clues],
        "scope": "Corpus familiarity screening and authored specialist vocabulary; "
                 "not a measurement of an individual player's knowledge",
    }
