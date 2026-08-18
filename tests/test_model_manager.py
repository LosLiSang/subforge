from pathlib import Path

from subforge.asr.model_manager import cached_models


def test_cached_models_detects_huggingface_snapshot_directories(tmp_path):
    (tmp_path / "models--Systran--faster-whisper-base" / "snapshots" / "abc").mkdir(parents=True)
    (tmp_path / "models--Systran--faster-whisper-large-v3" / "snapshots" / "def").mkdir(parents=True)
    (tmp_path / "models--Systran--faster-whisper-medium" / "snapshots").mkdir(parents=True)

    assert cached_models(tmp_path, ["base", "medium", "large-v3"]) == {"base", "large-v3"}
