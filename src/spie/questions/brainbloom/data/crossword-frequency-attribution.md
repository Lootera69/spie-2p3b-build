# English word familiarity data

`crossword-frequency-v1.json` is derived from the English large word list in
[wordfreq 3.1.1](https://github.com/rspeer/wordfreq), by Robyn Speer. Changes:
retained only 3–15 ASCII-letter entries, uppercased keys, and exported Zipf scores
as JSON using `tools/build_crossword_frequency.py`. This derived data is licensed
under [Creative Commons Attribution-ShareAlike 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
The wordfreq software is Apache-2.0; it is a build dependency, not bundled runtime code.

Credit: Robyn Speer (2022), *rspeer/wordfreq: v3.0 (v3.0.2)*,
[Zenodo](https://doi.org/10.5281/zenodo.7199437), the citation supplied by wordfreq.

Underlying sources credited by wordfreq include:

- [Google Books Ngrams](http://books.google.com/ngrams) and
  [Syntactic Ngrams](http://commondatastorage.googleapis.com/books/syntactic-ngrams/index.html).
- [Leeds Internet Corpus](http://corpus.leeds.ac.uk/list.html), University of Leeds
  Centre for Translation Studies.
- [Wikipedia](https://www.wikipedia.org/) and [ParaCrawl](https://paracrawl.eu/).
- [OPUS OpenSubtitles 2018](http://opus.nlpl.eu/OpenSubtitles.php), originating from
  [OpenSubtitles](https://www.opensubtitles.org/).
- **Marc Brysbaert et al.**, authors of SUBTLEX-US, SUBTLEX-UK, SUBTLEX-CH,
  SUBTLEX-DE and SUBTLEX-NL. **SUBTLEX is freely available data**, available from
  [Ghent University's subtitle frequencies](http://crr.ugent.be/programs-data/subtitle-frequencies).
  English references: Brysbaert & New (2009), *Behavior Research Methods* 41(4),
  977–990; van Heuven, Mandera, Keuleers & Brysbaert (2014), *Quarterly Journal of
  Experimental Psychology* 67(6), 1176–1190.

Wordfreq also incorporates aggregate statistics from Twitter; no tweets are
included here. Corpus frequency estimates familiarity, not a player's knowledge
or a word's educational value. Authored definitions are separate project content.
