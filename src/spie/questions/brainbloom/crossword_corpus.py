"""Revision 17: discover crossword vocabulary from lexical corpora, never answer banks.

The same retrieval, familiarity and clue rules apply to every topic. Candidate
pools vary with the seed and are embedded in exports for offline replay.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from random import Random

from ...forge.corpus import digest
from . import coverage_sources
from .lexicon import (
    DEFAULT_WORDNET,
    RELATIONS,
    WORDNET_SHA256,
    Dictionary,
    _clue,
    _normalization_candidates,
    validate_context,
)
from .topics import _combine, lookup_many

MIN_ZIPF = 150
MAX_ZIPF = 350
MAX_DEPTH = 4
MAX_NODES = 4000
GENERAL = "corpus:english"
CORPUS_SENSE = re.compile(r"(?:wn:[nvar]:\d{8}|oewn2024:oewn-\d{8}-[nvars])\Z")
BAD_CLUE = re.compile(
    r"\[entry\]|\b(?:archaic|obsolete|offensive|derogatory|slur|vulgar|abbreviation|"
    r"acronym|initialism|surname|given name|genus|taxonomic|misspelling|misspelt|"
    r"cardinal number|ordinal number)\b|\bbeing .{1,60} (?:more|less) than\b", re.I)
# Input-parser fillers include topic words such as "puzzle"; those must remain
# searchable in definitions. Only grammatical function words are excluded here.
GLOSS_STOP = frozenset("a an the about above after again against all also am an and any are as "
                       "at be because been before being below between both but by can could "
                       "did do does doing down during each few for from further had has have "
                       "having he her here hers herself him himself his how if in into is it "
                       "its itself just may more most much must no nor not of off on once "
                       "only or other our ours ourselves out over own same she should so some "
                       "such than that their theirs them themselves then there these they "
                       "this those through to too under until up upon us very was we were "
                       "what when where which while who whom why will with would you your".split())


@lru_cache(maxsize=1)
def frequencies() -> dict[str, int]:
    data = json.loads(files(__package__).joinpath(
        "data/crossword-frequency-v1.json").read_text(encoding="utf-8"))
    return {word: round(value * 100) for word, value in data["zipf"].items()}


@lru_cache(maxsize=1)
def policy() -> dict:
    return {"version": 2, "method": "corpus-relationships-and-familiarity-v1",
            "frequency_sha256": digest(frequencies()),
            "zipf_hundredths_range": [MIN_ZIPF, MAX_ZIPF],
            "max_graph_depth": MAX_DEPTH, "max_visited_nodes": MAX_NODES}


def eligible(word: str, clue: str) -> bool:
    return (bool(re.fullmatch(r"[A-Z]{3,15}", word))
            and MIN_ZIPF <= frequencies().get(word, 0) <= MAX_ZIPF
            and 3 <= len(clue.split()) <= 60
            and not BAD_CLUE.search(clue)
            and word.lower() not in re.findall(r"[a-z]+", clue.lower()))


@lru_cache(maxsize=2)
def _installed(wordnet: str | None, oewn: str | None) -> Dictionary:
    return Dictionary(Path(wordnet) if wordnet else None,
                      oewn=Path(oewn) if oewn else None, coverage=False)


def installed_dictionary(*, allow_oewn: bool = True) -> Dictionary:
    wordnet = str(DEFAULT_WORDNET.resolve()) if DEFAULT_WORDNET.is_file() else None
    oewn = (str(coverage_sources.DEFAULT_OEWN.resolve())
            if allow_oewn and coverage_sources.DEFAULT_OEWN.is_file() else None)
    if not wordnet and not oewn:
        raise ValueError("Automatic crossword vocabulary needs a local dictionary corpus. "
                         "Run dictionary-install or oewn-install, then try again.")
    return _installed(wordnet, oewn)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", text.lower())) - GLOSS_STOP


def _stems(text: str) -> set[str]:
    return {word[:-3] + "y" if word.endswith("ies") else
            word[:-1] if len(word) > 4 and word.endswith("s")
            and not word.endswith(("ss", "us", "is")) else word
            for word in _tokens(text)}


def _forms(phrase: str) -> set[str]:
    """Regular noun plurals; these are lookup forms, never invented answers."""
    if re.search(r"[^aeiou]y$", phrase):
        plural = phrase[:-1] + "ies"
    elif phrase.endswith(("s", "x", "z", "ch", "sh")):
        plural = phrase + "es"
    else:
        plural = phrase + "s"
    return {phrase, plural}


def _definition(node: dict) -> str:
    # Example sentences may mention a topic incidentally. They must not turn
    # "dabble in astronomy" into evidence that DABBLE is an astronomy term.
    return node["definition"].split('; "', 1)[0]


@lru_cache(maxsize=4)
def _gloss_index(dictionary: Dictionary, modern: bool) -> dict[str, set[str]]:
    nodes = dictionary.oewn_synsets if modern else dictionary.synsets
    index = defaultdict(set)
    for sid, node in nodes.items():
        for token in _tokens(_definition(node)):
            index[token].add(sid)
    return dict(index)


def _source(dictionary: Dictionary, modern: bool) -> dict:
    original = coverage_sources.source() if modern else dictionary.source
    return _attribution(original)


def _attribution(original: dict) -> dict:
    return {"name": original["name"] + "; automatic crossword vocabulary",
            "sha256": digest({"source": original, "policy": policy()}),
            "original_source": deepcopy(original),
            "license": original["license"] + (
                "\n\nWord familiarity: wordfreq 3.1.1 by Robyn Speer, CC BY-SA 4.0. "
                "SUBTLEX by Marc Brysbaert et al. is freely available. See "
                "crossword-frequency-attribution.md. Clues are dictionary definitions."
            )}


@lru_cache(maxsize=512)
def _reference_profiles(dictionary: Dictionary, modern: bool, phrase: str) -> dict:
    """Extended dictionary definitions for conservative reference disambiguation.

    A biological plant's definition alone rarely shares words with definitions
    of its leaves or flowers. Its immediate lexical relatives supply that
    evidence. Competing senses are excluded from one another's profiles.
    """
    nodes = dictionary.oewn_synsets if modern else dictionary.synsets
    index = dictionary.oewn_index if modern else dictionary.index
    senses = set(index.get(phrase, ()))
    glosses = _gloss_index(dictionary, modern)
    profiles = {}
    for sense in sorted(senses):
        ambiguous_words = set().union(*(
            _stems(word) for word in nodes[sense]["words"]
            if len(index.get(word.replace("_", " ").lower(), ())) > 1
        ))
        queue = deque([(sense, 0, 1.0)])
        seen, weights = set(), {}
        while queue and len(seen) < 256:
            sid, depth, scale = queue.popleft()
            if sid in seen or sid not in nodes or (sid != sense and sid in senses):
                continue
            seen.add(sid)
            node = nodes[sid]
            text = _definition(node) + " " + " ".join(node["words"]).replace("_", " ")
            for token in _stems(text) - _stems(phrase) - ambiguous_words:
                # Very frequent gloss words are weak evidence for a particular
                # meaning (e.g. "large", "usually", "something").
                idf = math.log((len(nodes) + 1) / (len(glosses.get(token, ())) + 1))
                if idf >= 3:
                    weights[token] = max(weights.get(token, 0), scale * idf)
            if depth < 2:
                for relation, target in sorted([*node["links"],
                                                 *node.get("crossword_links", [])]):
                    if relation in ("~", "~i"):
                        queue.append((target, depth + 1, scale * 0.5))
                    elif depth == 0 and relation in ("@", "%p", "%m", "domain-member",
                                                     "related-form"):
                        queue.append((target, 2, 0.35))
        profiles[sense] = weights
    return profiles


def _reference_sense(dictionary: Dictionary, modern: bool, phrase: str,
                     target: str) -> str | None:
    profiles = _reference_profiles(dictionary, modern, phrase)
    nodes = dictionary.oewn_synsets if modern else dictionary.synsets
    node = nodes[target]
    tokens = _stems(_definition(node)) - _stems(phrase)
    parent_tokens = set().union(*(
        _stems(_definition(nodes[sid])) for relation, sid in node["links"]
        if relation == "@" and sid in nodes
    )) - tokens - _stems(phrase)
    direct = {sid: sum(weights.get(token, 0) for token in sorted(tokens))
              for sid, weights in profiles.items()}
    ranked = sorted((direct[sid]
                     + 0.5 * sum(weights.get(token, 0) for token in sorted(parent_tokens)), sid)
                    for sid, weights in profiles.items())
    if not ranked:
        return None
    score, sense = ranked[-1]
    runner_up = ranked[-2][0] if len(ranked) > 1 else 0
    # No fallback to the first dictionary sense when there is no evidence.
    # Ties and weak matches are omitted rather than assigned to a homonym.
    return sense if direct[sense] >= 2.5 and score > runner_up * 1.2 else None


def _node_entries(node: dict, sid: str, path: list[str]):
    candidates = []
    scores = frequencies()
    for lemma in node["words"]:
        word = lemma.upper()
        if (MIN_ZIPF <= scores.get(word, 0) <= MAX_ZIPF
                and re.fullmatch(r"[a-z]{3,15}", lemma)):
            candidates.append((lemma, word))
    if not candidates:
        return
    # The source sometimes lowercases an initialism or puts Roman numerals
    # beside spelled-out numbers. Recognize these from their companion lemmas,
    # without a hand-maintained list of accepted or rejected answers.
    if any(re.fullmatch(r"\d+(?:[.,]\d+)*", lemma) for lemma in node["words"]):
        return
    initialisms = {"".join(part[0] for part in parts).lower()
                   for lemma in node["words"]
                   if len(parts := re.findall(r"[a-zA-Z]+", lemma)) > 1}
    definition = _definition(node).strip().rstrip(".")
    ascii_definition = definition.isascii()
    lowercase_definition = definition.lower()
    for lemma, word in candidates:
        if lemma in initialisms:
            continue
        clue = definition
        # Most definitions do not mention the lemma. Avoid compiling a distinct
        # redaction regex for each of the corpus's 100,000+ words in that case.
        # Non-ASCII text still needs re.IGNORECASE's full Unicode matching rules.
        if not ascii_definition or lemma in lowercase_definition:
            clue = _clue(lemma, node["definition"]).strip().rstrip(".")
        if eligible(word, clue):
            yield {"word": word, "definition": clue, "sense": sid, "path": path}


def _study_objects(dictionary: Dictionary, modern: bool, sense: str) -> set[str]:
    """Resolve an explicit subject of study from a field's dictionary definition.

    Only complete indexed noun phrases qualify. This does not turn arbitrary
    words from a definition into new topics or consult authored topic aliases.
    """
    nodes = dictionary.oewn_synsets if modern else dictionary.synsets
    index = dictionary.oewn_index if modern else dictionary.index
    definition = _definition(nodes[sense]).lower()
    match = re.search(r"\b(?:study of|science of|(?:that|which) studies) (.+)", definition)
    if not match:
        return set()
    objects = set()
    for phrase in re.split(r"[;,()]|\band\b", match[1]):
        phrase = re.sub(r"^(?:a|an|the) ", "", phrase.strip()).rstrip(".")
        for term, _, provenance in _normalization_candidates(phrase):
            if provenance == "authored-alias":
                continue
            candidates = [sid for sid in index.get(term, ())
                          if sid.startswith("wn:n:") or sid.endswith("-n")]
            if not candidates:
                continue
            selected = (candidates[0] if len(candidates) == 1 else
                        _reference_sense(dictionary, modern, term, sense))
            if selected not in candidates:
                # A field's explicit plural subject denotes a class. Prefer a
                # meaning with actual kinds over an isolated figurative use,
                # such as "insect" used as an insult for a person.
                def rank(sid, term=term):
                    kinds = {target for relation, target in nodes[sid]["links"]
                             if relation in ("~", "~i")}
                    return (-len(kinds), dictionary.wordnet_rank.get(term, {}).get(sid, 100_000),
                            sid)
                selected = min(candidates, key=rank)
            if selected in candidates and selected != sense:
                objects.add(selected)
            break
    return objects


@lru_cache(maxsize=128)
def _discover(dictionary: Dictionary, sense: str) -> tuple[dict, ...]:
    general = sense == GENERAL
    modern = sense.startswith("oewn2024:") or (general and bool(dictionary.oewn_synsets))
    nodes = dictionary.oewn_synsets if modern else dictionary.synsets
    lexical_index = dictionary.oewn_index if modern else dictionary.index
    if general:
        entries = {}
        for sid, node in nodes.items():
            for entry in _node_entries(node, sid, [GENERAL, f"dictionary:{sid}"]):
                entries.setdefault(entry["word"], entry)
        return tuple(entries.values())
    if sense not in nodes:
        raise ValueError("Choose a meaning from the installed dictionary corpus")
    queue = deque([(sense, [sense])])
    for target in sorted(_study_objects(dictionary, modern, sense)):
        queue.append((target, [sense, f"study-object:{target}"]))
    paths = {}
    while queue and len(paths) < MAX_NODES:
        sid, path = queue.popleft()
        if sid in paths or sid not in nodes:
            continue
        paths[sid] = path
        related = path[-1].startswith("related-form:")
        if (len(path) > MAX_DEPTH
                or (len(path) > 1 and not related and not path[-1].startswith(
                    ("kind:", "instance:", "study-object:")))
                or sum(step.startswith("related-form:") for step in path) >= 2):
            continue
        for relation, target in sorted([*nodes[sid]["links"],
                                         *nodes[sid].get("crossword_links", [])]):
            # Descend the selected meaning, its parts and its subject domain.
            # Never walk up to a broad parent and then drift into its siblings.
            if related and relation != "related-form":
                continue
            # Derive forms of the requested concept only. Deriving a distant
            # subtype such as an insect "worker" can drift into human labour.
            if relation == "related-form" and sid != sense and not related:
                continue
            if relation in ("~", "~i", "%p", "%m"):
                queue.append((target, [*path, f"{RELATIONS[relation]}:{target}"]))
            elif relation in ("domain-member", "related-form"):
                queue.append((target, [*path, f"{relation}:{target}"]))

    # Dictionary definitions provide additional explicit lexical connections.
    # Ambiguous references need corroboration from the selected sense's lexical
    # neighbourhood; example sentences never contribute evidence.
    glosses = _gloss_index(dictionary, modern)
    root_tokens = _stems(" ".join(nodes[sense]["words"]).replace("_", " "))
    for sid, path in list(paths.items()):
        if len(path) > MAX_DEPTH:
            continue
        node = nodes[sid]
        for lemma in node["words"]:
            phrase = lemma.replace("_", " ").replace("-", " ")
            if not re.fullmatch(r"[a-z][a-z ]{2,}", phrase):
                continue
            if sid != sense and (len(_tokens(phrase)) < 2
                                 or not _stems(phrase) & root_tokens
                                 or len(lexical_index.get(phrase, ())) != 1):
                continue
            forms = _forms(phrase)
            matches = set()
            for form in forms:
                tokens = _tokens(form)
                if tokens and all(token in glosses for token in tokens):
                    matches.update(set.intersection(*(glosses[token] for token in tokens)))
            ambiguous = len(lexical_index.get(phrase, ())) > 1
            pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(forms))) + r")\b",
                                 re.I)
            for target in sorted(matches):
                definition = _definition(nodes[target])
                if not pattern.search(definition):
                    continue
                if ambiguous and _reference_sense(
                        dictionary, modern, phrase, target) != sid:
                    continue
                if len(paths) >= MAX_NODES:
                    break
                paths.setdefault(target, [*path, f"definition:{target}"])

    entries = {}
    for sid, path in paths.items():
        for entry in _node_entries(nodes[sid], sid, path):
            word = entry["word"]
            if word not in entries or len(path) < len(entries[word]["path"]):
                entries[word] = entry
    return tuple(entries.values())


class CorpusDictionary(Dictionary):
    """A corpus-only view sharing parsed data; authored packs are never queried."""

    def __init__(self, dictionary: Dictionary | None = None, *, seed: int = 0):
        dictionary = dictionary or installed_dictionary()
        if not dictionary.synsets and not dictionary.oewn_synsets:
            dictionary = installed_dictionary(
                allow_oewn=getattr(dictionary, "crossword_allow_oewn", True))
        self.__dict__.update(dictionary.__dict__)
        self.corpus = dictionary
        self.seed = seed
        self.coverage_index = {}

    def _matches(self, phrase: str) -> list[dict]:
        choices = []
        for term, label, provenance in _normalization_candidates(phrase):
            if provenance == "authored-alias":
                continue
            if choices:
                break
            for modern, index, nodes in ((False, self.index, self.synsets),
                                         (True, self.oewn_index, self.oewn_synsets)):
                for sid in index.get(term, ()):
                    choices.append({
                        "id": sid, "term": phrase, "normalized_term": term,
                        "definition": nodes[sid]["definition"],
                        "normalization": label, "provenance": provenance,
                        "source_rank": self.wordnet_rank.get(term, {}).get(sid, 100_000),
                        "source": ("Open English WordNet 2024" if modern
                                   else "Princeton WordNet 3.0"),
                    })
        return list({row["id"]: row for row in choices}.values())

    def _entries(self, sense: str) -> tuple[list[dict], dict]:
        candidates = _discover(self.corpus, sense)
        # Interleave lengths so compact boards retain candidates. Within each
        # length, seed-based sampling can reach the whole discovered vocabulary.
        rng = Random(digest([self.seed, sense, "crossword-corpus-v1"]))
        buckets = defaultdict(list)
        for entry in candidates:
            buckets[len(entry["word"])].append(entry)
        for bucket in buckets.values():
            bucket.sort(key=lambda entry: entry["word"])
            rng.shuffle(bucket)
        pool = []
        while buckets and len(pool) < 80:
            for length in sorted(buckets):
                pool.append(buckets[length].pop())
                if not buckets[length]:
                    del buckets[length]
                if len(pool) == 80:
                    break
        modern = sense.startswith("oewn2024:") or (sense == GENERAL and bool(self.oewn_synsets))
        return deepcopy(pool), _source(self.corpus, modern)

    def select(self, choices: list[dict], sense: str = "", *, context: str = ""):
        if sense:
            chosen = next((row for row in choices if row["id"] == sense), None)
            if chosen is None:
                raise ValueError("Choose a current corpus meaning for this topic")
        else:
            def score(row):
                sid = row["id"]
                noun = sid.startswith("wn:n:") or sid.endswith("-n")
                other = _tokens(context) - _tokens(row["term"])
                overlap = other & _tokens(row["definition"])
                count = len(_discover(self.corpus, sid))
                capacity = min(count, 80 if row["normalization"] == "plural" else 8)
                return (-int(noun), -len(overlap), -int(count >= 7), -capacity,
                        not sid.startswith("wn:"), row["source_rank"], sid)
            chosen = min(choices, key=score)
        count = len(_discover(self.corpus, chosen["id"]))
        return chosen, {
            "mode": "explicit" if sense else "automatic", "policy": "corpus-context-capacity-v1",
            "reason": ("Using your selected meaning. " if sense else
                       "Selected a noun meaning using context and available uncommon vocabulary. ")
                      + "Words come from dictionary relationships and definitions.",
            "usable_entries": min(count, 80), "alternatives": len(choices) - 1,
            "context_matches": sorted((_tokens(context) - _tokens(chosen["term"]))
                                      & _tokens(chosen["definition"])),
        }


def _finalize(context: dict, seed: int) -> dict:
    context = deepcopy(context)
    if len(context["entries"]) < 4:
        raise ValueError("This meaning has fewer than four uncommon dictionary words with usable "
                         "definitions. Choose another meaning, add a related topic or try a "
                         "broader topic.")
    if "topics" in context:
        for topic in context["topics"]:
            topic["anchor"] = None
        context["sense"] = "combined:" + digest(context["topics"])
    context["crossword_learning"] = deepcopy(policy())
    context["crossword_retrieval_seed"] = seed
    validate_learning(context)
    return context


def lookup(dictionary: Dictionary | None, subject: str, meanings: dict, category: str,
           *, seed: int = 0, strict: bool = False) -> dict:
    corpus = CorpusDictionary(dictionary, seed=seed)
    if not subject.strip():
        if meanings and meanings != {category: GENERAL} and strict:
            raise ValueError("The saved meaning does not match general English vocabulary")
        entries, source = corpus._entries(GENERAL)
        definition = "Less familiar English vocabulary from the dictionary"
        context = _combine(category, [{"term": category, "sense": GENERAL,
                                       "definition": definition, "entries": entries,
                                       "source": source}])
        context["label"] = "English vocabulary"
        return {"status": "ready", "subject": subject, "using_category": True,
                "unknown_terms": [], "suggestions": {}, "meanings": {category: GENERAL},
                "message": "Ready: uncommon English vocabulary selected from the dictionary.",
                "groups": [{"term": category, "selected": GENERAL, "word_count": len(entries),
                            "choices": [{"id": GENERAL, "definition": definition}],
                            "selection_mode": "automatic",
                            "selection_reason": "No topic supplied; using general vocabulary."}],
                "context": _finalize(context, seed)}
    report = lookup_many(corpus, subject, meanings, category, strict=strict)
    if report["status"] == "ready":
        report["context"] = _finalize(report["context"], seed)
        for group, topic in zip(report["groups"], report["context"]["topics"], strict=True):
            group["word_count"] = len(topic["words"])
    else:
        report["message"] += (" Automatic crosswords need enough uncommon dictionary words "
                              "with usable definitions. Try a broader topic or another meaning.")
    return report


def resolve(request, dictionary: Dictionary | None = None) -> dict:
    if request.topic_mode == "combined":
        report = lookup(dictionary, request.subject, request.meanings, request.category,
                        seed=request.seed, strict=True)
    else:
        corpus = CorpusDictionary(dictionary, seed=request.seed)
        if not request.subject:
            entries, source = corpus._entries(GENERAL)
            return _finalize({"subject": request.category, "sense": GENERAL,
                              "label": "English vocabulary", "definition": "Dictionary vocabulary",
                              "entries": entries, "source": source}, request.seed)
        report = corpus.lookup(request.subject, request.sense, request.category)
        if report["status"] == "ready":
            report["context"] = _finalize(report["context"], request.seed)
    if report["status"] != "ready":
        raise ValueError(report["message"])
    return report["context"]


def canonical_request(request):
    """Default category crosswords use the same corpus retrieval as typed topics."""
    return (replace(request, topic="dictionary")
            if request.topic == "crossword" else request)


def validate_learning(context: dict, *, seed: int | None = None) -> None:
    validate_context(context)
    if context.get("crossword_learning") != policy():
        raise ValueError("Missing or unsupported automatic crossword vocabulary policy")
    if type(context.get("crossword_retrieval_seed")) is not int:
        raise ValueError("Missing automatic crossword retrieval seed")
    if seed is not None and context["crossword_retrieval_seed"] != seed:
        raise ValueError("Crossword vocabulary seed does not match the request")
    roots = {t["sense"] for t in context.get("topics", [])} or {context["sense"]}
    if any(sense != GENERAL and not CORPUS_SENSE.fullmatch(sense) for sense in roots):
        raise ValueError("Automatic crosswords require dictionary corpus meanings")
    source_prefixes = set()
    for source in context.get("sources", [context["source"]]):
        original = source.get("original_source")
        if not isinstance(original, dict) or any(
                not isinstance(original.get(key), str) or not original[key]
                for key in ("name", "sha256", "license")):
            raise ValueError("Missing automatic crossword corpus attribution")
        identity = (original["name"], original["sha256"])
        if identity == ("Princeton WordNet 3.0", WORDNET_SHA256):
            source_prefixes.add("wn")
        elif identity == ("Open English WordNet 2024", coverage_sources.OEWN_SHA256):
            source_prefixes.add("oewn2024")
        else:
            raise ValueError("Unsupported automatic crossword corpus source")
        if source != _attribution(original):
            raise ValueError("Automatic crossword corpus attribution is inconsistent")
    for entry in context["entries"]:
        path = entry["path"]
        prefix = entry["sense"].split(":", 1)[0]
        if (not CORPUS_SENSE.fullmatch(entry["sense"])
                or path[0] not in roots or prefix not in source_prefixes
                or not eligible(entry["word"], entry["definition"])):
            raise ValueError("Unsuitable or unsourced automatic crossword vocabulary")
        if path[0] == GENERAL:
            valid_path = path == [GENERAL, "dictionary:" + entry["sense"]]
        else:
            valid_path = (path[0].startswith(prefix + ":")
                          and (path[0] == entry["sense"] if len(path) == 1 else
                               path[-1].split(":", 1)[-1] == entry["sense"]))
            for step in path[1:]:
                relation, _, target = step.partition(":")
                valid_path &= (relation in {"kind", "instance", "part", "member",
                                             "domain-member", "related-form", "study-object",
                                             "definition"}
                               and bool(CORPUS_SENSE.fullmatch(target))
                               and target.startswith(prefix + ":"))
        if not valid_path:
            raise ValueError("Invalid automatic crossword dictionary relationship path")
    if (context.get("crossword_anchor") is not None
            or any(t["anchor"] is not None for t in context.get("topics", []))):
        raise ValueError("Automatic crossword topics use relevant vocabulary, not forced anchors")


def add_learning(item: dict, proof: dict) -> None:
    clues = item["crosswordData"]["clues"]
    item["question"] += " Discover less familiar words from their definitions."
    item["lessonContent"] = (
        "Discover less familiar words through their dictionary meanings.\n"
        "Use word lengths and crossing letters to work out unfamiliar answers.\n"
        "Review each word and its definition after revealing the completed grid."
    )
    recap = "Vocabulary recap:\n" + "\n".join(f"{c['answer']} — {c['clue']}" for c in clues)
    item["correctExplanation"] += "\n\n" + recap
    item["incorrectExplanation"] += "\n\n" + recap
    proof["learning_vocabulary"] = {
        **deepcopy(policy()),
        "words": [{"word": c["answer"], "zipf_hundredths": frequencies()[c["answer"]]}
                  for c in clues],
        "scope": "Automatic dictionary retrieval and corpus familiarity screening; "
                 "not a measurement of a player's vocabulary",
    }
