"""Optional real-library CPU check of resume semantics, NOT question-writer training.

Run only in the isolated training-test environment; the ordinary engine has no
torch dependency. This uses a tiny random synthetic model, not downloaded weights.
"""

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("peft")
pytest.importorskip("accelerate")


def test_pinned_trainer_resumes_complete_update_groups(tmp_path):
    from peft import LoraConfig, get_peft_model
    from tools.forge_train.checkpoint import resume_checkpoint, seal_checkpoint
    from tools.forge_train.data import accumulation_steps
    from transformers import (
        Qwen2Config,
        Qwen2ForCausalLM,
        Trainer,
        TrainerCallback,
        TrainingArguments,
        set_seed,
    )

    torch.set_num_threads(1)
    output = tmp_path / "synthetic"
    output.mkdir()
    (output / "run.json").write_text(json.dumps({"resume_signature": "synthetic-only"}))
    records = [{"input_ids": [2, i + 3, 30, 31], "labels": [-100, -100, 30, 31],
                "attention_mask": [1, 1, 1, 1]} for i in range(26)]
    checkpoints = output / "checkpoints"

    class Seal(TrainerCallback):
        def on_save(self, args, state, control, **kwargs):
            seal_checkpoint(checkpoints / f"checkpoint-{state.global_step}", "synthetic-only")

    def fit(resume=None):
        set_seed(42)
        model = get_peft_model(Qwen2ForCausalLM(Qwen2Config(
            vocab_size=64, hidden_size=16, intermediate_size=32, num_hidden_layers=1,
            num_attention_heads=2, num_key_value_heads=2, max_position_embeddings=32,
            bos_token_id=0, eos_token_id=1, pad_token_id=0,
        )), LoraConfig(r=2, target_modules=["q_proj"], task_type="CAUSAL_LM"))
        config = TrainingArguments(
            output_dir=str(checkpoints), use_cpu=True, max_steps=2,
            per_device_train_batch_size=1, gradient_accumulation_steps=accumulation_steps(26),
            save_steps=1, report_to="none", disable_tqdm=True, seed=42, data_seed=42,
            learning_rate=0.01, optim="adamw_torch", save_safetensors=True,
        )
        trainer = Trainer(model=model, args=config, train_dataset=records, callbacks=[Seal()])
        trainer.train(resume_from_checkpoint=resume)
        assert trainer.state.epoch == 1.0 and trainer.state.global_step == 2
        return {n: p.detach().clone() for n, p in model.named_parameters() if p.requires_grad}

    original = fit()
    checkpoint = resume_checkpoint(output, str(checkpoints / "checkpoint-1"), "synthetic-only")
    resumed = fit(str(checkpoint))
    assert original.keys() == resumed.keys()
    for name in original:
        assert torch.equal(original[name], resumed[name]), name
