"""Allowlisted writer configurations; no GPU imports or implicit paid services."""

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
COLAB_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
MODEL_PROFILES = {
    DEFAULT_MODEL: {"total_gib": 14, "free_gib": 12, "disk_gib": 30},
    COLAB_MODEL: {"total_gib": 8, "free_gib": 6, "disk_gib": 12},
}


def model_profile(model: str) -> dict:
    if model not in MODEL_PROFILES:
        raise ValueError("model is not in the reviewed allowlist")
    return dict(MODEL_PROFILES[model])
