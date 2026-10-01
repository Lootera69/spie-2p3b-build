"""Dictionary-fed construction with explicit, independently checked letter rules."""

from __future__ import annotations

import math
from collections import Counter

from ...forge.contract import XP
from ...forge.corpus import digest
from .catalog import DIFFICULTIES, Request, lesson_group
from .crossword import construct
from .lexicon import validate_context
from .topics import representatives, sample_words

LESSON = "\n".join((
    "Read the stated letter rule and the supplied word bank before solving.",
    "Use the dictionary clue as support, keeping the selected meaning in mind.",
    "Check every letter and every position rather than relying on a guess.",
    "The uniqueness check applies to the supplied words; definitions come from the cited source.",
    "Share this: explain which constraint ruled out the closest alternative.",
))


def candidate(request: Request, rng, context: dict) -> tuple[dict, dict]:
    validate_context(context)
    level = DIFFICULTIES[request.difficulty]
    entries = context["entries"]
    item = {
        "type": request.qtype, "category": request.category, "difficulty": request.difficulty,
        "title": f"{context['label'].title()} · {request.qtype}", "choices": [],
        "lessonGroup": lesson_group(request.category, "dictionary"),
        "xpReward": XP[request.difficulty], "lessonContent": LESSON,
    }
    prefix = (f"Topic: {context['label']}. "
              "For compound entries, spaces and hyphens are omitted.\n")
    proof = {
        "dictionary_sha256": digest(context), "selected_sense": context["sense"],
        "source": context["source"]["name"],
        "scope": ("letter constraints within the supplied word bank; dictionary meanings "
                  "are sourced, not formally proven"),
    }
    if request.qtype == "crossword":
        topics = context.get("topics", [])
        data, checks = construct(request.category, 2 * level + 1, rng,
                                 [(e["word"], e["definition"]) for e in entries],
                                 [t["words"] for t in topics],
                                 [t["anchor"] for t in topics if t["anchor"]],
                                 board_size=request.crossword_size)
        item.update({
            "question": (prefix + "Use the dictionary clues to fill this "
                         f"{len(data['clues'])}-entry connected crossword."),
            "crosswordData": data, "correctAnswer": ", ".join(c["answer"] for c in data["clues"]),
            "correctExplanation": (
                "The dictionary entries fill every clued run with matching crossing letters."
            ),
            "incorrectExplanation": (
                "Compare each clue and word length, then check the crossing letters."
            ),
        })
        proof.update({"method": "dictionary-and-independent-crossword-reconstruction",
                      "grid_checks": checks,
                      "scope": ("connected grid, numbering and crossings; clue meanings "
                                "come from the cited dictionary"),
                       "steps": [f"{c['number']} {c['direction']}: {c['answer']} — {c['clue']}"
                                 for c in data["clues"]]})
        return item, proof

    if request.qtype == "wonder" and "topics" in context:
        words = representatives(context, rng)
        totals, independent, steps = [], [], []
        for word in words:
            counts = Counter(word)
            total = math.factorial(len(word)) // math.prod(math.factorial(n)
                                                          for n in counts.values())
            remaining, other = len(word), 1
            for n in counts.values():
                other *= math.comb(remaining, n)
                remaining -= n
            totals.append(total)
            independent.append(other)
            steps.append(f"{word} has {total:,} distinct letter arrangements, "
                         "after accounting for repeated letters.")
        if totals != independent:
            raise RuntimeError("Combined word-arrangement counters disagree")
        total = math.prod(totals)
        insight = " ".join(steps) + f" Choosing one arrangement per word gives {total:,} "
        insight += ("combinations: multiply the individual counts. "
                    "These need not be meaningful words.")
        item.update({
            "question": prefix + f"Take one word from each topic: {', '.join(words)}. "
                        "Rearrange each word's letters independently, keeping words separate. "
                        "How many combinations result if you choose one arrangement for each word? "
                        "How much do repeated letters reduce the number?",
            "correctAnswer": insight, "correctExplanation": insight,
            "incorrectExplanation": "This is an unscored reflection. " + insight,
            "lessonContent": insight, "xpReward": 0,
            "sharePrompt": "Which word contributes the most possibilities? Explain why.",
        })
        proof.update({"method": "factorials-and-independent-binomial-counting",
                      "words": words, "arrangements_per_word": totals,
                      "independent_counts": independent, "arrangements": total,
                      "scope": "independent letter arrangements of every supplied topic word",
                      "steps": [*steps, insight]})
        return item, proof

    # Length bands are structural difficulty controls, not learned player scores.
    bank = None
    if "topics" in context:
        bank = sample_words(context, min(len(entries), 4 + 2 * level), rng)
    ordered = sorted((e for e in entries if bank is None or e["word"] in bank),
                     key=lambda e: (len(e["word"]), e["word"]))
    band = ordered[(level - 1) * len(ordered) // 3:level * len(ordered) // 3]
    target = rng.choice(band)
    answer = target["word"]
    if request.qtype == "wonder":
        counts = Counter(answer)
        total = math.factorial(len(answer)) // math.prod(math.factorial(n) for n in counts.values())
        remaining, independent = len(answer), 1
        for n in counts.values():
            independent *= math.comb(remaining, n)
            remaining -= n
        if total != independent:
            raise RuntimeError("Letter arrangement counters disagree")
        insight = (f"{answer} has {len(answer)} letters. "
                   f"There are {total:,} distinct arrangements: "
                   f"{len(answer)}! divided by ("
                   + " × ".join(f"{n}!" for n in counts.values())
                   + "). Repeated copies of a letter are indistinguishable. "
                   "These are letter arrangements, not necessarily dictionary words.")
        item.update({
            "question": prefix + f"Consider {answer}: {target['definition']}. "
                        "How many distinct arrangements could its letters make, "
                        "whether or not they form words? "
                        "How do repeated letters change your estimate?",
            "correctAnswer": insight, "correctExplanation": insight,
            "incorrectExplanation": "This reflection is unscored. " + insight,
            "lessonContent": insight, "xpReward": 0,
            "sharePrompt": ("Compare this word with another of the same length. "
                            "Would their arrangement counts match?"),
        })
        proof.update({"method": "factorials-and-independent-binomial-counting",
                      "counts": dict(counts),
                      "arrangements": total, "independent_count": independent,
                      "scope": ("distinct permutations of a specified letter multiset, "
                                "not counts of meaningful words"),
                      "steps": [f"Count the letters: {dict(counts)}.", insight]})
        return item, proof

    others = [e["word"] for e in entries if e["word"] != answer]
    if bank is None:
        bank = [answer, *rng.sample(others, min(len(others), 3 + 2 * level))]
        rng.shuffle(bank)
    variation = request.variation
    if variation == "auto":
        variation = (
            "word-order" if request.category == "logic"
            else rng.choice(("anagram", "missing-letters"))
        )
    if variation == "word-order":
        sorted_bank = sorted(bank)
        position = sorted_bank.index(answer) + 1
        rule = f"Sort the word bank alphabetically (A to Z). Which word is in position {position}?"
        survivors = [w for w in bank if 1 + sum(other < w for other in bank) == position]
        independent = [sorted_bank[position - 1]]
        constraints = {"position": position}
    elif variation == "anagram":
        letters = list(answer)
        rng.shuffle(letters)
        if "".join(letters) == answer:
            letters = letters[1:] + letters[:1]
        scrambled = "".join(letters)
        prefix_length = 0
        survivors = [w for w in bank if sorted(w) == sorted(scrambled)]
        while len(survivors) > 1:
            prefix_length += 1
            survivors = [w for w in survivors if w.startswith(answer[:prefix_length])]
        rule = f"Rearrange all these letters exactly once: {scrambled}."
        if prefix_length:
            rule += f" The answer starts with {answer[:prefix_length]}."
        rule += f" Dictionary clue: {target['definition']}. Which word fits?"
        independent = [w for w in bank if Counter(w) == Counter(scrambled)
                       and w.startswith(answer[:prefix_length])]
        constraints = {"letters": scrambled, "prefix": answer[:prefix_length]}
    else:
        positions = rng.sample(range(len(answer)), max(1, len(answer) // (level + 1)))
        def fits(word):
            return len(word) == len(answer) and all(word[i] == answer[i] for i in positions)
        survivors = [w for w in bank if fits(w)]
        for i in rng.sample(range(len(answer)), len(answer)):
            if len(survivors) == 1:
                break
            if i not in positions:
                positions.append(i)
                survivors = [w for w in survivors if fits(w)]
        pattern = "".join(c if i in positions else "_" for i, c in enumerate(answer))
        rule = (f"Fill the missing letters: {' '.join(pattern)} ({len(answer)} letters). "
                f"Dictionary clue: {target['definition']}. Which word fits?")
        independent = [w for w in bank if len(w) == len(pattern)
                       and all(p == "_" or p == c for p, c in zip(pattern, w, strict=True))]
        constraints = {"pattern": pattern}
    if survivors != [answer] or independent != [answer]:
        raise RuntimeError("Dictionary puzzle did not have one independently checked answer")
    stem = prefix + "Word bank: " + ", ".join(bank) + ".\n" + rule
    if request.qtype == "riddle":
        stem = prefix + "I am a word in this bank: " + ", ".join(bank) + ".\n" + rule
    explanation = (f"{answer} is the only word in this bank satisfying the stated rule. "
                   f"Dictionary meaning: {target['definition']}.")
    item.update({"question": stem, "correctAnswer": answer, "correctExplanation": explanation,
                 "incorrectExplanation": "Check the complete rule. " + explanation})
    # Similar lengths/letter sets make plausible alternatives, but every alternative
    # has already been excluded by the exact rule, rather than assumed semantically false.
    wrongs = sorted((w for w in bank if w != answer),
                    key=lambda w: (abs(len(w) - len(answer)), -len(set(w) & set(answer)), w))[:3]
    if request.qtype == "multiple-choice":
        choices = [answer, *wrongs]
        rng.shuffle(choices)
        item["choices"] = choices
    elif request.qtype == "true-false":
        truth = bool(rng.randrange(2))
        claim = answer if truth else rng.choice(wrongs)
        item.update({"question": stem + f"\nTrue or False: {claim} satisfies this puzzle's rule.",
                     "choices": ["True", "False"], "correctAnswer": str(truth),
                     "correctExplanation": f"The claim is {str(truth).lower()}. " + explanation})
        proof.update({"claim": claim, "claim_holds": claim in survivors})
    else:
        item["acceptedAnswers"] = [answer, "the word is " + answer, "answer: " + answer]
        if request.qtype == "riddle":
            item["hintText"] = (
                "Work only with words in the given bank.\n"
                "Check letter counts and positions against every part of the rule."
            )
    proof.update({"method": "dictionary-and-independent-finite-constraint-checks",
                  "variation": variation,
                  "word_bank": bank, "constraints": constraints, "survivors": survivors,
                  "independent_survivors": independent, "answer_sense": target["sense"],
                  "relationship_path": target["path"], "steps": [rule, explanation]})
    return item, proof
