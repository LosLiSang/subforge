from pathlib import Path
from unittest.mock import MagicMock, patch

from subforge.asr.model_manager import cached_models, ensure_model
from subforge.asr.engine import transcribe


def test_cached_models_detects_huggingface_snapshot_directories(tmp_path):
    (tmp_path / "models--Systran--faster-whisper-base" / "snapshots" / "abc").mkdir(parents=True)
    (tmp_path / "models--Systran--faster-whisper-large-v3" / "snapshots" / "def").mkdir(parents=True)
    (tmp_path / "models--Systran--faster-whisper-medium" / "snapshots").mkdir(parents=True)

    assert cached_models(tmp_path, ["base", "medium", "large-v3"]) == {"base", "large-v3"}


class TestModelCacheDetection:
    def test_cache_hit(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with patch("huggingface_hub.try_to_load_from_cache", return_value=str(models_dir / "config.json")):
            available, local_only = ensure_model("medium", models_dir)
            assert available is True
            assert local_only is True

    def test_cache_miss(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with patch("huggingface_hub.try_to_load_from_cache", return_value=None):
            available, local_only = ensure_model("medium", models_dir)
            assert available is True
            assert local_only is False

    def test_exception_fallback(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with patch("huggingface_hub.try_to_load_from_cache", side_effect=RuntimeError("cache corrupted")):
            available, local_only = ensure_model("medium", models_dir)
            assert available is True
            assert local_only is False


class TestModelLocalLoadFallback:
    def test_fallback_on_local_load_failure(self):
        with patch("faster_whisper.WhisperModel") as mock_wm:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = ([], MagicMock(duration=0))
            mock_wm.side_effect = [RuntimeError("bad cache"), mock_model]

            result = transcribe(
                Path("fake.mp3"),
                model_size="medium",
                language="ja",
                local_files_only=True,
            )
            assert result == []
            assert mock_wm.call_count == 2
            assert mock_wm.call_args_list[0][1]["local_files_only"] is True
            assert mock_wm.call_args_list[1][1]["local_files_only"] is False
