"""QLoRA instruction tuning of an existing writer; all output is draft content.

Heavy dependencies are imported only by `train`. Ordinary SPIE and preflight
remain usable without torch, CUDA, transformers, peft, or network access.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
import shutil
import statistics
import time
from pathlib import Path

from spie.forge.contract import TYPES
from spie.forge.corpus import digest
from spie.forge.propose import Brief, intake, training_example, writing_request

from .checkpoint import file_sha256, resume_checkpoint, seal_checkpoint
from .config import model_profile
from .data import accumulation_steps, encode_example, load_corpus, select_splits


def _save(path: Path, data: dict | list) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _parameter_digest(model) -> str:
    result = hashlib.sha256()
    for name, value in sorted(model.named_parameters()):
        if value.requires_grad:
            result.update(name.encode("utf-8"))
            result.update(value.detach().float().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def _preview(model, tokenizer, data, count):
    import torch

    validations = [r for r in data["records"] if r["split"] == "validation"]
    # One per available format first; references remain TRAIN-only. Test stays sealed.
    chosen = []
    for kind in TYPES:
        match = next((r for r in validations if r["item"]["type"] == kind), None)
        if match:
            chosen.append(match)
    previews = []
    model.eval()
    model.gradient_checkpointing_disable()
    model.config.use_cache = True
    for row in chosen[:count]:
        item = row["item"]
        brief = Brief(item["category"], item["type"], item["difficulty"], item["lessonGroup"])
        try:
            request = writing_request(data["records"], brief)
        except ValueError as exc:
            previews.append({"validation_source": row["source"], "error": str(exc)})
            continue
        inputs = tokenizer.apply_chat_template(request["messages"], tokenize=True,
                                               add_generation_prompt=True, return_tensors="pt")
        if inputs.shape[1] > 7168:
            previews.append({"validation_source": row["source"], "error": "prompt exceeds cap"})
            continue
        inputs = inputs.to(model.device)

        def generate(inputs=inputs):
            with torch.inference_mode():
                output = model.generate(
                    inputs, attention_mask=torch.ones_like(inputs), do_sample=False,
                    max_new_tokens=1024, pad_token_id=tokenizer.pad_token_id,
                )
            return tokenizer.decode(output[0, inputs.shape[1]:], skip_special_tokens=True)

        with model.disable_adapter():
            base_text = generate()
        tuned_text = generate()
        entry = {"validation_source": row["source"], "brief": request["brief"],
                 "reference_ids": request["reference_ids"]}
        for name, text in (("base", base_text), ("tuned", tuned_text)):
            try:
                checked = intake(text, data["records"], brief)
            except (ValueError, TypeError) as exc:
                checked = {"parse_error": str(exc), "items": []}
            entry[name] = {"raw": text, "draft_checks": checked}
        previews.append(entry)
    return previews


def train(args) -> None:
    profile = model_profile(args.model)
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ValueError("model revision must be an immutable 40-hex commit")
    if not 512 <= args.max_length <= 4096 or not 0 <= args.preview_count <= 4:
        raise ValueError("max-length must be 512-4096 and preview-count 0-4")
    out = Path(args.out)
    if out.exists() and args.resume is None:
        raise ValueError("output already exists; choose a new training directory")
    data = load_corpus(Path(args.corpus))
    selected = select_splits(data, args.mode)
    accumulation = accumulation_steps(len(selected["train"]))

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        Trainer,
        TrainerCallback,
        TrainingArguments,
        set_seed,
    )

    if not torch.cuda.is_available():
        raise ValueError("CUDA GPU required; standard CPU Actions runners cannot run this job")
    props = torch.cuda.get_device_properties(0)
    free_memory, _ = torch.cuda.mem_get_info(0)
    if (props.total_memory < profile["total_gib"] * 1024**3
            or free_memory < profile["free_gib"] * 1024**3):
        raise ValueError(f"insufficient GPU memory for {args.model}: {profile}")
    if shutil.disk_usage(Path.cwd()).free < profile["disk_gib"] * 1024**3:
        raise ValueError(f"insufficient local disk: need {profile['disk_gib']} GiB")

    software = {p: importlib.metadata.version(p) for p in
                ("torch", "transformers", "peft", "accelerate", "bitsandbytes")}
    code = {p.name: file_sha256(p) for p in Path(__file__).parent.glob("*.py")}
    # Include the target encoder/retriever/contract, not just the training entrypoint.
    import spie.forge

    code.update({f"forge/{p.name}": file_sha256(p)
                 for p in Path(spie.forge.__file__).parent.glob("*.py")})
    settings = {"model": args.model, "revision": args.revision, "mode": args.mode,
                "max_length": args.max_length, "corpus": digest(data),
                "software": software, "code": code}
    signature = digest(settings)
    checkpoint = resume_checkpoint(out, args.resume, signature)
    previous = json.loads((out / "run.json").read_text(encoding="utf-8")) if checkpoint else {}

    set_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(
        args.model, revision=args.revision, trust_remote_code=False,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if tokenizer.pad_token_id is None:
        raise ValueError("tokenizer lacks padding and EOS tokens")
    encoded = {s: [encode_example(tokenizer, row, args.max_length) for row in rows]
               for s, rows in selected.items()}
    # Tokenization is fully checked before the expensive model download/training.
    out.mkdir(parents=True, exist_ok=checkpoint is not None)
    record = {
        "status": "starting", "mode": args.mode, "base_model": args.model,
        "resume_signature": signature, "settings": settings,
        "resumed_from": str(checkpoint) if checkpoint else None,
        "base_revision": args.revision, "corpus_sha256": digest(data),
        "corpus_split_counts": data["manifest"]["splits"],
        "used_split_counts": {s: len(rows) for s, rows in selected.items()},
        "gradient_accumulation_steps": accumulation,
        "training_targets_sha256": digest([training_example(r) for r in selected["train"]]),
        "selection": {s: [r["source"] for r in rows] for s, rows in selected.items()},
        "hardware": {"gpu": props.name, "vram_bytes": props.total_memory},
        "software": software,
        "tokens": {s: {"total": sum(len(r["input_ids"]) for r in rows),
                       "max": max(len(r["input_ids"]) for r in rows)}
                   for s, rows in encoded.items()},
        "quality_status": "not established; previews require independent review",
        "test_set_used": False,
    }
    _save(out / "run.json", record)
    bf16 = torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=args.revision, trust_remote_code=False, use_safetensors=True,
        device_map={"": 0}, torch_dtype=dtype, attn_implementation="sdpa",
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        ),
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        revision=args.revision,
    ))
    before = _parameter_digest(model)
    if checkpoint:
        # Compare against the original seeded initialization, even across resumptions.
        before = previous.get("initial_parameters_sha256", before)
    record["initial_parameters_sha256"] = before
    record["trainable_parameters"] = sum(p.numel() for p in model.parameters() if p.requires_grad)
    _save(out / "run.json", record)

    def collate(batch):
        length = math.ceil(max(len(row["input_ids"]) for row in batch) / 8) * 8
        return {key: torch.tensor([
            row[key] + [pad] * (length - len(row[key])) for row in batch
        ], dtype=torch.long) for key, pad in
            (("input_ids", tokenizer.pad_token_id), ("attention_mask", 0), ("labels", -100))}

    full_rows = data["manifest"]["splits"]["train"]

    class Progress(TrainerCallback):
        def __init__(self):
            self.times = []
            self.last = None

        def on_train_begin(self, args, state, control, **kwargs):
            self.last = time.perf_counter()

        def on_step_end(self, args, state, control, **kwargs):
            now = time.perf_counter()
            self.times.append(now - self.last)
            self.last = now
            if len(self.times) >= 4:
                seconds = statistics.median(self.times[2:])
                progress = {
                    "optimizer_step": state.global_step, "observed_steps": len(self.times),
                    "median_seconds_per_step": seconds,
                    "remaining_training_seconds_estimate":
                        seconds * max(0, state.max_steps - state.global_step),
                    "full_epoch_training_seconds_estimate": seconds * full_rows / accumulation,
                    "scope": "measured estimate; excludes setup/evaluation/previews; GPU may end",
                }
                _save(out / "progress.json", progress)
                if len(self.times) == 4 or state.global_step % 10 == 0:
                    print(json.dumps(progress), flush=True)

        def on_save(self, args, state, control, **kwargs):
            seal_checkpoint(Path(args.output_dir) / f"checkpoint-{state.global_step}", signature)

    config = TrainingArguments(
        output_dir=str(out / "checkpoints"), num_train_epochs=1,
        max_steps=8 if args.mode == "smoke" else len(selected["train"]) // accumulation,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=accumulation, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        learning_rate=2e-4, warmup_ratio=0.03, lr_scheduler_type="cosine",
        optim="paged_adamw_8bit", bf16=bf16, fp16=not bf16, max_grad_norm=0.3,
        logging_steps=1, logging_nan_inf_filter=False,
        save_steps=10, save_total_limit=2, eval_strategy="no", prediction_loss_only=True,
        report_to="none", seed=42, data_seed=42, dataloader_num_workers=0,
    )
    trainer = Trainer(model=model, args=config, train_dataset=encoded["train"],
                      eval_dataset=encoded["validation"], data_collator=collate,
                      callbacks=[Progress()])
    outcome = trainer.train(resume_from_checkpoint=str(checkpoint) if checkpoint else None)
    after = _parameter_digest(model)
    if before == after or trainer.state.global_step < 1 or not math.isfinite(outcome.training_loss):
        raise ValueError("training did not produce finite loss and changed adapter weights")
    if args.mode == "full" and trainer.state.epoch != 1:
        raise ValueError("not exactly one full epoch; refusing to claim the expected row coverage")
    model.save_pretrained(out / "adapter", safe_serialization=True)
    tokenizer.save_pretrained(out / "adapter")
    trainer.save_state()
    record.update({"status": "adapter_saved", "optimizer_steps": trainer.state.global_step,
                   "adapter_sha256": file_sha256(out / "adapter/adapter_model.safetensors"),
                   "epoch": trainer.state.epoch,
                   "initial_parameters_sha256": before, "final_parameters_sha256": after,
                   "train_diagnostics": outcome.metrics,
                   "diagnostic_scope": "token prediction loss, not puzzle correctness or quality"})
    _save(out / "run.json", record)
    metrics = trainer.evaluate()
    if not math.isfinite(metrics["eval_loss"]):
        raise ValueError("non-finite validation loss")
    record["validation_diagnostics"] = metrics
    previews = _preview(model, tokenizer, data, args.preview_count)
    _save(out / "previews.json", previews)
    record["status"] = "smoke_completed" if args.mode == "smoke" else "full_epoch_completed"
    _save(out / "run.json", record)
    (out / "README.md").write_text(
        f"# BrainBloom writer adapter\n\nMode: {args.mode}. Base: {args.model}@{args.revision}.\n\n"
        "Load this PEFT adapter with that exact base revision. The adapter alone is not a model.\n"
        "It proposes unpublished questions. It does not certify answers.\n"
        "Inspect run.json for actual training scope and previews.json for base/tuned drafts.\n"
        "This run does not establish that fine-tuning improves puzzle quality.\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": record["status"], "steps": record["optimizer_steps"],
                      "used_split_counts": record["used_split_counts"]}))
