from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_FW_REPO_ID = "Systran/faster-whisper-{model_size}"


def ensure_model(model_size: str, models_dir: Path) -> tuple[bool, bool]:
    """Check for cached model files and determine whether to skip network.

    Returns (available, local_files_only):
    - available: True if the model can be loaded (cached or downloadable).
    - local_files_only: True if model files exist locally — the engine should
      skip HuggingFace Hub requests.

    R4.1: When model files exist locally, skip download.
    R4.2: When not cached, let the engine download normally.
    R4.3 / R4.4: Log the outcome.
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Model directory: %s", models_dir)

    repo_id = _FW_REPO_ID.format(model_size=model_size)

    # Use huggingface_hub cache API to check if model files exist locally.
    # We check for the config.json file as a canonical marker that the model
    # snapshot is fully cached.
    try:
        from huggingface_hub import try_to_load_from_cache

        cached_path = try_to_load_from_cache(
            repo_id=repo_id,
            filename="config.json",
            cache_dir=str(models_dir),
        )
    except Exception:
        cached_path = None

    if cached_path is not None:
        logger.info("Model %s found locally, skipping download.", model_size)
        return True, True
    else:
        logger.info("Model %s not cached, will download from HuggingFace Hub.", model_size)
        return True, False
