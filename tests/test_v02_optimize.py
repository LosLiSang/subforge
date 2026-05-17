"""Tests for v0.2 optimizations: logging, model cache, translation concurrency."""

import logging
import os
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from subforge.config import Config, setup_logging, _DEBUGFilter
from subforge.asr.model_manager import ensure_model
from subforge.models import SubtitleEntry
from subforge.translate.context import (
    build_batches,
    translate_all,
)


# ── Logging ──────────────────────────────────────────────────────────────

class TestSetupLogging:
    def test_creates_log_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        config = Config(log_file=str(log_file), log_level="DEBUG")
        setup_logging(config)

        logger = logging.getLogger("test_creates_file")
        logger.info("hello")
        assert log_file.exists()

    def test_fallback_when_unwritable(self, tmp_path):
        bad_path = tmp_path / "readonly_dir" / "sub.log"
        # Create readonly_dir as a file to break FileHandler
        readonly = tmp_path / "readonly_dir"
        readonly.write_text("block")

        config = Config(log_file=str(bad_path), log_level="INFO")
        # Should not raise
        setup_logging(config)
        # FileHandler should be missing from root handlers (only StreamHandler)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers
                         if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 0

    def test_debug_filter_rejects_debug(self):
        f = _DEBUGFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0, "msg", (), None)
        assert f.filter(record) is False

    def test_debug_filter_allows_info(self):
        f = _DEBUGFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None)
        assert f.filter(record) is True


# ── Model cache detection ────────────────────────────────────────────────

class TestModelCacheDetection:
    def test_cache_hit(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        # try_to_load_from_cache is imported locally inside ensure_model;
        # patch the source module.
        with patch("huggingface_hub.try_to_load_from_cache",
                   return_value=str(models_dir / "config.json")):
            available, local_only = ensure_model("medium", models_dir)
            assert available is True
            assert local_only is True

    def test_cache_miss(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with patch("huggingface_hub.try_to_load_from_cache",
                   return_value=None):
            available, local_only = ensure_model("medium", models_dir)
            assert available is True
            assert local_only is False

    def test_exception_fallback(self, tmp_path):
        """When try_to_load_from_cache raises an exception, fall back to
        local_files_only=False."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with patch("huggingface_hub.try_to_load_from_cache",
                   side_effect=RuntimeError("cache corrupted")):
            available, local_only = ensure_model("medium", models_dir)
            assert available is True
            assert local_only is False


# ── Model load fallback ──────────────────────────────────────────────────

class TestModelLocalLoadFallback:
    def test_fallback_on_local_load_failure(self):
        from subforge.asr.engine import transcribe

        with patch("faster_whisper.WhisperModel") as mock_wm:
            # First call (local_files_only=True) raises
            # Second call (local_files_only=False) succeeds
            mock_model = MagicMock()
            mock_model.transcribe.return_value = ([], MagicMock(duration=0))
            mock_wm.side_effect = [RuntimeError("bad cache"), mock_model]

            result = transcribe(
                __import__("pathlib").Path("fake.mp3"),
                model_size="medium",
                language="ja",
                local_files_only=True,
            )
            assert result == []
            assert mock_wm.call_count == 2
            assert mock_wm.call_args_list[0][1]["local_files_only"] is True
            assert mock_wm.call_args_list[1][1]["local_files_only"] is False


# ── translate_all: ordering & concurrency ────────────────────────────────

class TestTranslateAllConcurrency:
    def _config(self, **kwargs):
        defaults = {
            "source_lang": "ja", "target_lang": "zh",
            "batch_size": 10, "context_size": 5,
            "translate_workers": 8,
        }
        defaults.update(kwargs)
        return Config(**defaults)

    def _entries(self, n: int) -> list[SubtitleEntry]:
        return [
            SubtitleEntry(index=i + 1, start=i * 2.0, end=i * 2.0 + 1.5,
                          text=f"Entry {i + 1}")
            for i in range(n)
        ]

    async def test_result_ordering(self):
        """Translation results must be ordered by entry.index regardless of
        which batch finished first."""
        config = self._config(batch_size=10, context_size=0)
        entries = self._entries(25)  # 3 batches

        mock_translate = AsyncMock()
        mock_translate.side_effect = [
            "\n".join(f"[{i}] tr-{i}" for i in range(1, 11)),
            "\n".join(f"[{i}] tr-{i}" for i in range(11, 21)),
            "\n".join(f"[{i}] tr-{i}" for i in range(21, 26)),
        ]

        result = await translate_all(entries, config, mock_translate)
        assert len(result) == 25
        for i, entry in enumerate(result):
            assert entry.index == i + 1
            assert entry.text == f"tr-{i + 1}"

    async def test_serial_fallback(self):
        """workers=1 should work identically to v0.1 serial behavior."""
        config = self._config(translate_workers=1)
        entries = self._entries(25)

        mock_translate = AsyncMock()
        mock_translate.side_effect = [
            "\n".join(f"[{i}] x{i}" for i in range(1, 11)),
            "\n".join(f"[{i}] x{i}" for i in range(11, 21)),
            "\n".join(f"[{i}] x{i}" for i in range(21, 26)),
        ]

        result = await translate_all(entries, config, mock_translate)
        assert len(result) == 25
        assert mock_translate.call_count == 3

    async def test_progress_callback(self):
        config = self._config(batch_size=10, context_size=0)
        entries = self._entries(15)  # 2 batches

        mock_translate = AsyncMock()
        mock_translate.side_effect = [
            "\n".join(f"[{i}] t{i}" for i in range(1, 11)),
            "\n".join(f"[{i}] t{i}" for i in range(11, 16)),
        ]

        progress_calls: list[tuple[int, int]] = []
        def _cb(done: int, total: int) -> None:
            progress_calls.append((done, total))

        result = await translate_all(
            entries, config, mock_translate,
            progress_callback=_cb,
        )
        assert len(result) == 15
        total_batches = 2
        assert len(progress_calls) == total_batches
        assert progress_calls[-1] == (2, 2)
