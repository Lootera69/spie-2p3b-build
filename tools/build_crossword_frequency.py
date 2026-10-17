"""Build the offline familiarity index with wordfreq==3.1.1 (build-only).

Run with wordfreq on PYTHONPATH. No dictionary or network is needed at runtime.
The derived data is CC BY-SA 4.0; see the adjacent attribution document.
"""

import json
import re
from importlib.metadata import version
from pathlib import Path

from wordfreq import iter_wordlist, zipf_frequency

assert version("wordfreq") == "3.1.1"
scores = {word.upper(): zipf_frequency(word, "en", wordlist="large")
          for word in iter_wordlist("en", wordlist="large")
          if re.fullmatch(r"[a-z]{3,15}", word)}
payload = {"version": 1, "source": "wordfreq 3.1.1 English large",
           "license": "CC BY-SA-4.0", "zipf": scores}
target = (Path(__file__).resolve().parents[1] / "src/spie/questions/brainbloom/data"
          / "crossword-frequency-v1.json")
target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                  encoding="utf-8")
print(f"Wrote {len(scores):,} scores to {target}")
