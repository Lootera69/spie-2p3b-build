# Crosswords that discover vocabulary

Engine revision 17 discovers less familiar words from the installed English
dictionary for each supplied topic. It does not query the authored answer banks
used by revision 16. A new corpus-supported topic uses the same retrieval method
as an existing topic; adding support does not require writing a word list.

Easy, medium and hard puzzles retain 3, 5 and 7 connected entries. Every level
uses the same vocabulary screen. Revealing a completed grid displays a recap
pairing each answer with its definition, including after resuming a saved puzzle.

## How selection works

1. Resolve the topic to a source-qualified WordNet meaning. Automatic selection
   considers noun suitability, the other supplied topics and usable vocabulary;
   the dictionary's sense order breaks ties. The selected definition is visible
   and the creator can choose another meaning.
2. Traverse that meaning's kinds, instances, parts, members, subject-domain
   members and derived word forms. Field definitions such as “the branch of
   zoology that studies insects” can also identify an indexed subject of study.
   Retrieval visits at most 4,000 nodes through four relationship steps.
   It does not expand unrelated sibling branches through broader parent concepts.
3. Find additional words whose dictionary definitions refer to the topic or a
   specific compound in its branch. Example sentences are excluded. Ambiguous
   references require supporting overlap with the meanings' surrounding lexical
   definitions, weighted by inverse document frequency. Weak matches are omitted.
4. Keep attested, lowercase single-word lemmas of 3–15 ASCII letters with an
   English Zipf frequency of **1.5–3.5**. This applies uniformly, without special
   allowances for authored words. Definitions must be usable as clues and must
   not reveal the answer. Proper names, source initialisms, number spellings,
   and definitions marked obsolete, offensive, abbreviated or taxonomic are
   excluded by the lexical and clue filters.
5. Use the request's seed to sample up to 80 words, balancing word lengths so
   compact boards remain possible. Broad topics can produce different candidate
   vocabulary with different seeds, as well as different layouts. Combined
   topics share the available space and each must contribute an answer.

For example, the installed corpus supplies geology terms such as *esker* and
*geode*, musical terms such as *cadenza*, and neuroscience terms such as *synaptic*.
These illustrate retrieved output; they are not a production whitelist.

Without a supplied topic, crosswords sample uncommon general English dictionary
vocabulary. A common topic word need not appear as an answer. For example,
*dolphin* can lead to less familiar terms within its actual animal meaning.

The topic preview, difficulty checks, board recommendation and generation use
the same seeded snapshot. If the dictionary or chosen board cannot support the
requested puzzle, the creator receives guidance to choose another meaning, a
larger board, a broader topic or an easier level. Everyday or unrelated filler is
not added. Narrow topics and recent technical phrases may have too little
coverage. Automatic lexical matching is a heuristic, and the meaning selector
remains available for ambiguity.

## Local corpus and reproducibility

Install at least one supported corpus once:

```powershell
./.venv/Scripts/python.exe -m spie.questions.brainbloom dictionary-install
./.venv/Scripts/python.exe -m spie.questions.brainbloom oewn-install
```

Princeton WordNet 3.0 and Open English WordNet 2024 are hash-pinned. New crossword
generation uses the configured dictionary or auto-detects these local files when
no native corpus is configured. Generation never downloads a corpus, calls a
language model, or requires an API key. Other puzzle formats retain their existing
dictionary selection behavior.

Exports retain the exact candidate words, definitions, selected meanings,
relationship paths, retrieval seed, source licences and frequency policy. Saved
puzzles replay offline from that snapshot even without an installed dictionary.
Frequency metadata uses integers in hundredths of Zipf units, preserving exact
browser JSON save/replay. Unthemed built-in crosswords now use the dictionary
envelope too, so their vocabulary is also saved.

Revision 16's authored banks remain only for historical generation and replay.
Revisions 1–16 preserve their original outputs. Planning continues to use its
existing revision-15 implementation under the new default revision. Future
changes to retrieval or clue rules require another version to preserve saves.

The pinned frequency table comes from wordfreq 3.1.1 and is CC BY-SA 4.0. Frequency
is a familiarity estimate, not a measurement of a particular player's vocabulary.
See the bundled [source attribution](../src/spie/questions/brainbloom/data/crossword-frequency-attribution.md).
Regenerate the table with `tools/build_crossword_frequency.py` using wordfreq 3.1.1.
