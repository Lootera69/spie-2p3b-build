"""CPU tokenizer audit only; no model weights, GPU or held-out test inputs used."""

import argparse
import json
from pathlib import Path

from .config import COLAB_MODEL, model_profile
from .data import encode_example, load_corpus, select_splits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=COLAB_MODEL)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--max-length", type=int, default=2048)
    args = parser.parse_args()
    model_profile(args.model)
    if args.out.exists():
        raise ValueError("audit output already exists")
    selected = select_splits(load_corpus(args.corpus), "full")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision,
                                             trust_remote_code=False)
    report = {"model": args.model, "revision": args.revision, "test_set_used": False,
              "trained": False, "max_length": args.max_length, "splits": {}}
    for split, rows in selected.items():
        encoded = [encode_example(tokenizer, row, args.max_length) for row in rows]
        lengths = [len(r["input_ids"]) for r in encoded]
        report["splits"][split] = {
            "rows": len(rows), "total_tokens": sum(lengths), "max_tokens": max(lengths),
            "assistant_tokens": sum(sum(t != -100 for t in r["labels"]) for r in encoded),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
