"""Generate unpublished drafts from a completed adapter, without a hosted API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spie.forge.corpus import digest
from spie.forge.propose import Brief, intake, writing_request

from .checkpoint import file_sha256
from .config import model_profile
from .data import load_corpus


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--type", required=True)
    parser.add_argument("--difficulty", required=True)
    parser.add_argument("--topic", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise ValueError("draft output already exists; choose a new filename")
    run = Path(args.run)
    record = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if record["status"] not in {"smoke_completed", "full_epoch_completed"}:
        raise ValueError("training run has not completed")
    if file_sha256(run / "adapter/adapter_model.safetensors") != record.get("adapter_sha256"):
        raise ValueError("adapter integrity check failed")
    profile = model_profile(record["base_model"])
    data = load_corpus(Path(args.corpus))
    if digest(data) != record["corpus_sha256"]:
        raise ValueError("corpus differs from training")
    brief = Brief(args.category, args.type, args.difficulty, args.topic)
    request = writing_request(data["records"], brief)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise ValueError("this notebook inference configuration requires a CUDA GPU")
    if torch.cuda.get_device_properties(0).total_memory < profile["total_gib"] * 1024**3:
        raise ValueError("insufficient GPU memory for this inference configuration")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer = AutoTokenizer.from_pretrained(run / "adapter", trust_remote_code=False)
    base = AutoModelForCausalLM.from_pretrained(
        record["base_model"], revision=record["base_revision"], trust_remote_code=False,
        use_safetensors=True, device_map={"": 0}, torch_dtype=dtype,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        ),
    )
    model = PeftModel.from_pretrained(base, run / "adapter", is_trainable=False)
    model.eval()
    inputs = tokenizer.apply_chat_template(
        request["messages"], tokenize=True, add_generation_prompt=True, return_tensors="pt",
    ).to(model.device)
    if inputs.shape[1] > 7168:
        raise ValueError("generation prompt exceeds context cap")
    with torch.inference_mode():
        output = model.generate(inputs, attention_mask=torch.ones_like(inputs), do_sample=False,
                                max_new_tokens=1024, pad_token_id=tokenizer.pad_token_id)
    text = tokenizer.decode(output[0, inputs.shape[1]:], skip_special_tokens=True)
    try:
        checks = intake(text, data["records"], brief)
    except (ValueError, TypeError) as exc:
        checks = {"parse_error": str(exc), "items": []}
    result = {"base_model": record["base_model"], "base_revision": record["base_revision"],
              "training_mode": record["mode"], "brief": request["brief"],
              "reference_ids": request["reference_ids"], "raw": text, "draft_checks": checks,
              "answer_correctness": "unverified", "published": False}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
