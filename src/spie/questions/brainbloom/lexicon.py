"""Offline lexical lookup and sense-specific graph expansion. No language model.

Read Princeton WordNet's original data files directly, so generation needs neither
NLTK nor a corpus download. The optional installer is a separate explicit command.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
import zipfile
from collections import defaultdict, deque
from pathlib import Path

from ...forge.corpus import digest
from . import coverage_sources
from .vocabulary import ALIASES, PACKS

WORDNET_URL = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip"
WORDNET_SHA256 = "cbda5ea6eef7f36a97a43d4a75f85e07fccbb4f23657d27b4ccbc93e2646ab59"
DEFAULT_WORDNET = Path(".brainbloom/wordnet.zip")
WORD = re.compile(r"[a-z]{3,15}\Z")
STOP = set("a an the about around on in of for with and or make create questions question "
           "puzzle puzzles please me some want i we need generate topic themed".split())
RELATIONS = {"~": "kind", "~i": "instance", "%p": "part", "%m": "member", "%s": "substance"}
ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def install_wordnet(path: Path) -> None:
    """Explicit download, hash-pinned, exclusive write. Never called by generation."""
    if path.exists():
        raise ValueError(f"Dictionary already exists: {path}")
    with urllib.request.urlopen(WORDNET_URL, timeout=60) as response:
        data = response.read(16_000_001)
    if hashlib.sha256(data).hexdigest() != WORDNET_SHA256:
        raise ValueError("WordNet download did not match the pinned corpus SHA256")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _key(text: str) -> str:
    # Do not erase digits, accents or unsupported scripts: space123 is not space.
    # Unicode casefold would also silently turn the unsupported long s (ſ) into s.
    return " ".join(text.translate(ASCII_LOWER).split())


def _tokens(text: str) -> list[str]:
    """Split ordinary prose separators while retaining unsupported token content."""
    # A word-character regex would silently drop emoji, zero-width characters or
    # underscores before lookup. Preserve them so the caller can report the input.
    return [word for token in re.findall(r'[^\s,;.!?():"“”\[\]{}]+', text)
            if (word := token.strip("'‘’"))]


# Deliberately small, auditable normalization rules.  These produce lookup
# candidates only; they never merge source-qualified senses.
_SPELLING_VARIANTS = {
    "colour": "color", "centre": "center", "analyse": "analyze",
    "programme": "program", "organise": "organize",
}


def _normalization_candidates(phrase: str) -> list[tuple[str, str, str]]:
    """Return (candidate, label, provenance), without guessing intent."""
    phrase = _key(phrase)
    candidates = [(phrase, "exact", "input")]
    if phrase in ALIASES:
        candidates.append((ALIASES[phrase], "phrase-alias", "authored-alias"))
    if re.fullmatch(r"[a-z]+(?:[-_][a-z]+)+", phrase):
        candidates.append((re.sub(r"[-_]", " ", phrase), "compound", "separator-compound"))
    if " " in phrase:
        compact = phrase.replace(" ", "")
        candidates.append((compact, "compound", "space-compound"))
    if phrase.endswith("s") and len(phrase) > 3:
        singular = phrase[:-1]
        if singular.endswith("ie"):
            singular = singular[:-2] + "y"
        candidates.append((singular, "plural", "regular-plural"))
    if phrase in _SPELLING_VARIANTS:
        candidates.append((_SPELLING_VARIANTS[phrase], "spelling-variant", "curated-variant"))
    return list(dict.fromkeys(candidates))


def _clue(word: str, definition: str) -> str:
    # WordNet glosses sometimes repeat the headword, especially in examples.
    definition = definition.split('; "', 1)[0]
    return re.sub(rf"\b{re.escape(word)}(?:s|es)?\b", "[entry]", definition, flags=re.I)


class Dictionary:
    def __init__(self, wordnet: Path | None = None, *, oewn: Path | None = None,
                 coverage: bool = True):
        self.synsets: dict[str, dict] = {}
        self.index: dict[str, list[str]] = defaultdict(list)
        self.wordnet_rank: dict[str, dict[str, int]] = {}
        self.source = None
        if wordnet is not None:
            self._load_wordnet(wordnet)
        self.oewn_synsets, self.oewn_index, self.oewn_stats = {}, {}, {}
        if oewn is not None:
            self.oewn_synsets, self.oewn_index, self.oewn_stats = coverage_sources.load_oewn(oewn)
        self.coverage = coverage_sources.load_packs() if coverage else {"packs": []}
        self.coverage_index = defaultdict(list)
        self.coverage_entries = {}
        for pack in self.coverage["packs"]:
            for term in [pack["topic"], *pack["aliases"]]:
                self.coverage_index[term].append((pack["id"], pack["definition"]))
            for entry in pack["entries"]:
                sid = pack["id"] + ":" + entry["word"].lower()
                self.coverage_entries[sid] = pack
                if entry["lemma"] != pack["topic"]:
                    self.coverage_index[entry["lemma"]].append((sid, entry["definition"]))
            self.coverage_entries[pack["id"]] = pack
        self._configuration = self._counts()

    def _load_wordnet(self, path: Path) -> None:
        if not path.is_file():
            raise ValueError(
                f"No WordNet corpus at {path}; run `dictionary-install` or omit --wordnet"
            )
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != WORDNET_SHA256:
            raise ValueError(
                "WordNet corpus hash mismatch; use the pinned dictionary-install corpus"
            )
        with zipfile.ZipFile(path) as archive:
            license_text = archive.read("wordnet/LICENSE").decode("utf-8")
            for filename, pos in (("noun", "n"), ("verb", "v"), ("adj", "a"), ("adv", "r")):
                for line in archive.read(f"wordnet/data.{filename}").decode("utf-8").splitlines():
                    if not line or not line[0].isdigit():
                        continue
                    data, gloss = line.split("|", 1)
                    fields = data.split()
                    count = int(fields[3], 16)
                    words = [re.sub(r"\(.*\)$", "", fields[4 + 2 * i]) for i in range(count)]
                    cursor = 4 + 2 * count
                    pointers = int(fields[cursor])
                    links = []
                    for i in range(pointers):
                        relation, offset, target_pos, _ = fields[cursor + 1 + 4*i:cursor + 5 + 4*i]
                        if relation in RELATIONS or relation in ("@", "@i"):
                            links.append((relation, f"wn:{target_pos}:{offset}"))
                    sid = f"wn:{pos}:{fields[0]}"
                    self.synsets[sid] = {
                        "words": words, "definition": gloss.strip(), "links": links,
                    }
                    for word in words:
                        self.index[word.replace("_", " ").lower()].append(sid)
                # WordNet's index records its sense ordering. Preserve the
                # original index/sense IDs, but use this order before arbitrary
                # synset offsets when equally suitable meanings need a tie-break.
                for line in archive.read(f"wordnet/index.{filename}").decode("utf-8").splitlines():
                    if not line or line.startswith(" "):
                        continue
                    fields = line.split()
                    count = int(fields[2])
                    term = fields[0].replace("_", " ").lower()
                    ranks = self.wordnet_rank.setdefault(term, {})
                    ranks.update({f"wn:{pos}:{offset}": rank
                                  for rank, offset in enumerate(fields[-count:])})
            lemma_terms = set(self.index)
            for filename in ("noun", "verb", "adj", "adv"):
                for line in archive.read(f"wordnet/{filename}.exc").decode("utf-8").splitlines():
                    form, *lemmas = line.split()
                    for lemma in lemmas:
                        for sid in self.index.get(lemma.replace("_", " "), ()):
                            if sid not in self.index[form]:
                                self.index[form].append(sid)
        self.source = {
            "name": "Princeton WordNet 3.0", "sha256": checksum,
            "url": "https://wordnet.princeton.edu/", "license": license_text,
        }
        self.wordnet_aliases = len(set(self.index) - lemma_terms)

    def configuration(self) -> dict:
        import copy

        return copy.deepcopy(self._configuration)

    def _counts(self) -> dict:
        old_entries = sum(len(entries) for entries in PACKS.values())
        rows = [{"id": "authored-v1", "name": "Original authored topic packs",
                 "indexed_terms": len(set(PACKS) | set(ALIASES)
                                      | {w.lower() for p in PACKS.values() for w, _ in p}),
                 "unique_senses": old_entries, "alias_terms": len(ALIASES),
                 "usable_entry_pairs": old_entries, "topic_packs": len(PACKS),
                 "unique_topic_count": len(PACKS), "pack_version_count": len(PACKS),
                 "relationships": old_entries, "relation_scope": "editorial topic memberships"}]
        if self.source:
            rows.append({"id": "wn30", "name": self.source["name"],
                         "sha256": self.source["sha256"],
                         **coverage_sources.lexical_counts(self.index, self.synsets),
                         "alias_terms": self.wordnet_aliases,
                         "relation_scope": "retained directed lexical relationships"})
        if self.oewn_stats:
            rows.append({"id": "oewn2024", "name": "Open English WordNet 2024",
                         "sha256": coverage_sources.OEWN_SHA256, **self.oewn_stats,
                         "relation_scope": "retained directed lexical relationships"})
        packs = self.coverage["packs"]
        for version, checksum in (("v1", coverage_sources.PACKS_SHA256),
                                  ("v2", coverage_sources.PACKS_V2_SHA256)):
            version_packs = [p for p in packs if p["id"].startswith("coverage-" + version + ":")]
            if not version_packs:
                continue
            count = sum(len(p["entries"]) for p in version_packs)
            metadata = self.coverage["versions"]["coverage-" + version]
            terms = {term for p in version_packs
                     for term in [p["topic"], *p["aliases"],
                                  *(e["lemma"] for e in p["entries"]) ]}
            rows.append({"id": "coverage-" + version, "name": "Coverage topic packs " + version,
                         "sha256": checksum,
                         "indexed_terms": len(terms),
                         "unique_senses": count,
                         "alias_terms": sum(len(p["aliases"]) for p in version_packs),
                         "usable_entry_pairs": count, "topic_packs": len(version_packs),
                         "unique_topic_count": len({p["topic"] for p in version_packs}),
                         "pack_version_count": len(version_packs),
                         "relationships": count, "relation_scope": "editorial topic memberships",
                         "review": metadata["review"]})
        indexed = (set(self.index) | set(self.oewn_index) | set(self.coverage_index)
                   | set(PACKS) | set(ALIASES)
                   | {w.lower() for p in PACKS.values() for w, _ in p})
        return {
            "packs": list(dict.fromkeys([*PACKS, *(p["topic"] for p in packs)])),
            "unique_topic_count": len(set(PACKS) | {p["topic"] for p in packs}),
            "pack_version_count": len(PACKS) + len(packs),
            "wordnet_available": self.source is not None,
            "oewn_available": bool(self.oewn_stats), "sources": rows,
            "indexed_terms": len(indexed),
            "senses": sum(r["unique_senses"] for r in rows),
            "unique_senses": sum(r["unique_senses"] for r in rows),
            "alias_terms": sum(r["alias_terms"] for r in rows),
            "usable_entry_pairs": sum(r["usable_entry_pairs"] for r in rows),
            "relationships": sum(r["relationships"] for r in rows),
            "metric_scope": {
                "indexed_terms": "Distinct lookup keys across loaded sources, including aliases",
                "unique_senses": "Source-qualified meaning records; overlapping concepts across "
                                 "sources are not deduplicated or claimed as new knowledge",
                "alias_terms": "Source-local extra forms or editorial topic aliases; summed",
                "usable_entry_pairs": "Source-qualified word/meaning pairs passing 3-15 A-Z "
                                      "filter; not guaranteed puzzle capacity or suitability",
                "relationships": "Retained directed lexical edges plus editorial memberships; "
                                 "not deductions or cross-source equivalences",
                "unique_topic_count": "Distinct authored topic names across all pack versions",
                "pack_version_count": "Loaded authored topic/version records; older versions "
                                      "remain available for explicit selection and replay",
            },
            "examples": ["space", "animals", "plants", "ocean", "science", "logic"],
            "scope": "English lexical lookup and bounded relationships; no prose understanding",
        }

    def _matches(self, phrase: str) -> list[dict]:
        choices = []
        for candidate, label, provenance in _normalization_candidates(phrase):
            # Curated topic aliases remain useful even if a lexical corpus also
            # contains the literal phrase. Other rules are fallback-only.
            if choices and label != "phrase-alias":
                continue
            pack = candidate if candidate in PACKS else None
            rows = []
            if pack:
                rows = [{"id": f"pack:{pack}", "definition": f"Authored {pack} vocabulary"}]
            rows += [{"id": sid, "definition": self.synsets[sid]["definition"],
                      "source_rank": self.wordnet_rank.get(candidate, {}).get(sid, 100_000),
                      "source": "Princeton WordNet 3.0"} for sid in self.index.get(candidate, ())]
            rows += [{"id": sid, "definition": definition,
                        "source": "Coverage topic packs "
                        + sid.split(":", 1)[0].removeprefix("coverage-")}
                     for sid, definition in self.coverage_index.get(candidate, ())]
            rows += [{"id": sid, "definition": self.oewn_synsets[sid]["definition"],
                      "source": "Open English WordNet 2024"}
                     for sid in self.oewn_index.get(candidate, ())]
            if not rows and re.fullmatch(r"[a-z]+(?:[ -][a-z]+)*", candidate):
                word = candidate.replace(" ", "").replace("-", "").upper()
                rows = [{"id": f"word:{topic}:{word}", "definition": definition,
                         "source": "Original authored topic packs"}
                        for topic, entries in PACKS.items() for entry, definition in entries
                        if entry == word]
                if rows and word.lower() != candidate:
                    provenance = "separator-compound" if "-" in candidate else "space-compound"
                    candidate, label = word.lower(), "compound"
            for row in rows:
                choices.append({**row, "term": phrase, "normalized_term": candidate,
                                "normalization": label, "provenance": provenance})
        return list({row["id"]: row for row in choices}.values())

    def select(
        self, choices: list[dict], sense: str = "", *, context: str = ""
    ) -> tuple[dict, dict]:
        """Choose one bounded puzzle vocabulary, retaining every source ID for overrides.

        This is a deterministic suitability policy, not a claim to infer intent.
        Authored topics take precedence; lexical meanings use literal context
        overlap, noun suitability and bounded capacity. Stable IDs break ties.
        """
        selected = next((row for row in choices if row["id"] == sense), None)
        if sense and selected is None:
            raise ValueError(
                "Selected meaning no longer matches this topic; look up the topic again"
            )
        if not choices:
            raise ValueError("No dictionary topic found")
        newest = {}
        for row in choices:
            match = re.fullmatch(r"coverage-v(\d+):(.+)", row["id"])
            if match:
                newest[match[2]] = max(newest.get(match[2], 0), int(match[1]))
        candidates = []
        for row in choices:
            match = re.fullmatch(r"coverage-v(\d+):(.+)", row["id"])
            if not match or int(match[1]) == newest[match[2]]:
                candidates.append(row)
        facts = {}
        for row in ([selected] if selected else candidates):
            sid = row["id"]
            entries, _ = self._entries(sid)
            other_words = set(re.findall(r"[a-z]{3,}", context.casefold())) - STOP
            other_words -= set(re.findall(r"[a-z]+", row["term"].casefold()))
            vocabulary = " ".join([row["definition"], *(
                e["word"] + " " + e["definition"] for e in entries)])
            overlap = sorted(other_words & set(re.findall(r"[a-z]{3,}", vocabulary.casefold())))
            topic_pack = sid.startswith("pack:") or (
                sid.startswith("coverage-v") and sid.count(":") == 1)
            pack_entry = sid.startswith(("word:", "coverage-v")) and not topic_pack
            noun = sid.startswith("wn:n:") or (
                sid.startswith("oewn2024:") and sid.endswith("-n"))
            facts[sid] = {"count": len(entries), "overlap": overlap,
                          "topic_pack": topic_pack, "pack_entry": pack_entry}
            row_score = (len(entries) >= 4, 2 if topic_pack else int(pack_entry),
                         len(overlap), noun, min(len(entries), 8),
                         sid.startswith("wn:"), -row.get("source_rank", 100_000))
            facts[sid]["score"] = tuple(-int(value) for value in row_score) + (sid,)
        selected = selected or min(candidates, key=lambda row: facts[row["id"]]["score"])
        fact = facts[selected["id"]]
        mode = "explicit" if sense else "automatic"
        if sense:
            reason = "Using your selected meaning."
        elif fact["topic_pack"] or fact["pack_entry"]:
            reason = ("Using the latest authored topic pack"
                      if selected["id"].startswith("coverage-v")
                      else "Using the authored topic vocabulary")
            reason += "; its bounded vocabulary is prepared for these puzzles."
        elif fact["overlap"]:
            reason = ("Selected a usable meaning linked to your other words: "
                      + ", ".join(fact["overlap"]) + ".")
        else:
            reason = ("Selected a usable topic meaning by noun suitability and vocabulary "
                      "capacity; source sense order and stable IDs break ties.")
        if fact["count"] < 4:
            reason += " This meaning has fewer than four usable words; add a related topic."
        return selected, {
            "mode": mode, "reason": reason, "policy": "authored-context-capacity-v1",
            "usable_entries": fact["count"], "alternatives": len(choices) - 1,
            "context_matches": fact["overlap"],
        }

    def lookup(self, subject: str, sense: str = "", category: str = "puzzles") -> dict:
        if not isinstance(subject, str) or len(subject) > 200:
            raise ValueError("Topic input must be text of at most 200 characters")
        if not isinstance(sense, str) or len(sense) > 80:
            raise ValueError("Meaning must be a dictionary sense ID")
        phrase = _key(subject or category)
        if not phrase:
            raise ValueError("Enter an English topic word or phrase")
        choices = self._matches(phrase)
        tokens = _tokens(phrase)
        matched = set(tokens) if choices else set()
        if not choices:
            # Longest phrase first; deterministic lexical matching, not inferred intent.
            for length in range(min(4, len(tokens)), 0, -1):
                for start in range(len(tokens) - length + 1):
                    words = tokens[start:start + length]
                    if all(w in STOP or w in matched for w in words):
                        continue
                    matches = self._matches(" ".join(words))
                    if matches:
                        choices.extend(matches)
                        matched.update(words)
        choices = list({row["id"]: row for row in choices}.values())
        report = {
            "subject": subject or category, "choices": choices,
            "unmatched_terms": sorted(set(tokens) - matched - STOP),
            "matched_terms": sorted(matched - STOP),
        }
        if sense and not any(row["id"] == sense for row in choices):
            raise ValueError(
                "Selected meaning no longer matches this topic; look up the topic again"
            )
        if not choices:
            return {**report, "status": "unknown", "message": (
                "No dictionary topic found. Try space, animals, plants, ocean, or another word. "
                + ("" if self.source else "Install local WordNet for broader vocabulary.")
            )}
        selected, selection = self.select(choices, sense, context=phrase)
        report.update(selection=selection, selection_mode=selection["mode"],
                      selection_reason=selection["reason"])
        entries, source = self._entries(selected["id"])
        context = {
            **report, "sense": selected["id"], "label": selected["term"],
            "definition": selected["definition"], "entries": entries, "source": source,
        }
        return {**report, "status": "ready", "context": context,
                "message": f"{len(entries)} usable words linked to the selected meaning."}

    def resolve(self, subject: str, sense: str, category: str) -> dict:
        report = self.lookup(subject, sense, category)
        if report["status"] != "ready":
            raise ValueError(report["message"])
        context = report["context"]
        if len(context["entries"]) < 4:
            raise ValueError(
                "This meaning has fewer than four usable linked words. Try a broader topic."
            )
        return context

    def _entries(self, sense: str) -> tuple[list[dict], dict]:
        if sense.startswith("word:"):
            sense = "pack:" + sense.split(":", 2)[1]
        if sense in self.coverage_entries:
            pack = self.coverage_entries[sense]
            version = pack["id"].split(":", 1)[0]
            metadata = self.coverage["versions"][version]
            entries = [{"word": e["word"], "definition": _clue(e["lemma"], e["definition"]),
                        "sense": pack["id"] + ":" + e["word"].lower(),
                        "path": [pack["id"], "editorial-topic-member:" + e["source_sense"]]}
                       for e in pack["entries"]]
            return entries, coverage_sources.pack_source(pack, metadata)
        if sense.startswith("pack:"):
            pack = sense.removeprefix("pack:")
            entries = [{"word": word, "definition": _clue(word, clue),
                        "sense": f"{sense}:{word.lower()}", "path": [sense]}
                       for word, clue in PACKS[pack]]
            return entries, {
                "name": "BrainBloom authored vocabulary v1", "sha256": digest(PACKS[pack]),
                "license": "Project-authored definitions",
            }
        modern = sense.startswith("oewn2024:")
        synsets = self.oewn_synsets if modern else self.synsets
        queue = deque([(sense, [sense], 0)])
        visited, words, entries = set(), set(), []
        while queue and len(entries) < 80:
            sid, path, depth = queue.popleft()
            if sid in visited or sid not in synsets:
                continue
            visited.add(sid)
            node = synsets[sid]
            for lemma in node["words"]:
                word = lemma.replace("_", "").replace("-", "")
                if WORD.fullmatch(word) and word not in words:
                    words.add(word)
                    entries.append({
                        "word": word.upper(), "definition": _clue(lemma.replace("_", " "),
                                                                   node["definition"]),
                        "sense": sid, "path": path,
                    })
                    if len(entries) == 80:
                        break
            if depth < 2 and not path[-1].startswith("broader-kind:"):
                for relation, target in sorted(node["links"]):
                    # Include direct parents for narrow words, but do not walk into siblings.
                    if relation in RELATIONS or (depth == 0 and relation in ("@", "@i")):
                        label = RELATIONS.get(relation, "broader-kind")
                        queue.append((target, [*path, f"{label}:{target}"], depth + 1))
        return entries, coverage_sources.source() if modern else dict(self.source)


def validate_context(context: object) -> dict:
    """Bound and validate an embedded replay vocabulary, independent of local files."""
    if not isinstance(context, dict):
        raise ValueError("Missing dictionary snapshot")
    for key in ("subject", "sense", "label", "definition"):
        if not isinstance(context.get(key), str) or not 1 <= len(context[key]) <= 2000:
            raise ValueError("Invalid dictionary snapshot text")
    source = context.get("source")
    if not isinstance(source, dict) or any(not isinstance(source.get(k), str) or not source[k]
                                          for k in ("name", "sha256", "license")):
        raise ValueError("Missing dictionary attribution")
    entries = context.get("entries")
    if not isinstance(entries, list) or not 4 <= len(entries) <= 80:
        raise ValueError("Dictionary snapshot must contain 4-80 words")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"word", "definition", "sense", "path"}:
            raise ValueError("Invalid dictionary entry")
        word = entry["word"]
        if not isinstance(word, str) or not re.fullmatch(r"[A-Z]{3,15}", word) or word in seen:
            raise ValueError("Invalid or repeated dictionary word")
        seen.add(word)
        if any(not isinstance(entry[k], str) or not 1 <= len(entry[k]) <= 2000
               for k in ("definition", "sense")):
            raise ValueError("Invalid dictionary definition or sense")
        if (not isinstance(entry["path"], list) or not 1 <= len(entry["path"]) <= 3
                or any(not isinstance(p, str) or len(p) > 100 for p in entry["path"])):
            raise ValueError("Invalid dictionary relationship path")
    if "topics" in context:
        from .topics import validate_topics

        validate_topics(context)
    return context
