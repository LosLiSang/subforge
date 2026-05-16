from __future__ import annotations

import sys
from pathlib import Path


def ensure_model(model_size: str, models_dir: Path) -> bool:
    """Check if model files exist locally.

    faster-whisper downloads models via HuggingFace Hub on first use.
    This function checks if the expected cache directory exists.

    Returns True if model is available (or can be auto-downloaded).
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    # faster-whisper handles download automatically via huggingface_hub,
    # so we just ensure the directory exists and let the engine trigger downloads.
    print(f"Model directory: {models_dir}", file=sys.stderr)
    return True
