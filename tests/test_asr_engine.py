import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from subforge.asr.engine import transcribe
from subforge.asr.model_manager import ensure_model
from subforge.models import SubtitleEntry


def _generate_silent_wav(path: Path, duration_secs: float = 3.0, sample_rate: int = 16000):
    """Generate a near-silent WAV file for testing."""
    n_samples = int(duration_secs * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            wf.writeframes(struct.pack("<h", 0))


class TestModelManager:
    def test_ensure_model_creates_dir(self, tmp_path):
        models_dir = tmp_path / "models"
        available, local_only = ensure_model("tiny", models_dir)
        assert available is True
        assert isinstance(local_only, bool)
        assert models_dir.exists()


class TestTranscribe:
    def test_transcribe_with_mock(self, tmp_path):
        """Unit test: verify transcribe returns correct SubtitleEntry list
        using a mocked WhisperModel."""
        audio_path = tmp_path / "test.wav"
        _generate_silent_wav(audio_path)

        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 2.5
        mock_segment.text = " こんにちは "

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [mock_segment, mock_segment],
            MagicMock(language="ja"),
        )

        with patch(
            "faster_whisper.WhisperModel",
            return_value=mock_model,
        ):
            entries = transcribe(
                audio_path,
                model_size="tiny",
                language="ja",
            )

        assert len(entries) == 2
        assert isinstance(entries[0], SubtitleEntry)
        assert entries[0].index == 1
        assert entries[0].start == 0.0
        assert entries[0].end == 2.5
        assert entries[0].text == "こんにちは"
        assert entries[1].index == 2

    def test_transcribe_monotonic_timestamps(self, tmp_path):
        """Unit test: verify timestamps are monotonic in output."""
        audio_path = tmp_path / "test2.wav"
        _generate_silent_wav(audio_path)

        segments = []
        for i in range(5):
            seg = MagicMock()
            seg.start = float(i)
            seg.end = float(i) + 0.8
            seg.text = f"text {i}"
            segments.append(seg)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (segments, MagicMock())

        with patch(
            "faster_whisper.WhisperModel",
            return_value=mock_model,
        ):
            entries = transcribe(audio_path, model_size="tiny", language="ja")

        for i in range(1, len(entries)):
            assert entries[i].start >= entries[i - 1].start
            assert entries[i].end >= entries[i].start

    def test_transcribe_passes_model_dir(self, tmp_path):
        """Unit test: verify models_dir is passed to WhisperModel."""
        audio_path = tmp_path / "test3.wav"
        _generate_silent_wav(audio_path)
        models_dir = tmp_path / "my_models"

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())

        with patch(
            "faster_whisper.WhisperModel",
            return_value=mock_model,
        ) as mock_whisper:
            transcribe(audio_path, model_size="medium", language="ja", models_dir=models_dir)

        # Verify WhisperModel was called with download_root
        call_kwargs = mock_whisper.call_args.kwargs
        assert call_kwargs["download_root"] == str(models_dir)

    def test_vad_filter_enabled(self, tmp_path):
        """Unit test: verify VAD filter is enabled during transcription."""
        audio_path = tmp_path / "test4.wav"
        _generate_silent_wav(audio_path)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())

        with patch(
            "faster_whisper.WhisperModel",
            return_value=mock_model,
        ):
            transcribe(audio_path, model_size="tiny", language="ja")

        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["vad_filter"] is True
        assert call_kwargs["beam_size"] == 5


class TestWindowsGpuCrashWorkaround:
    def test_cuda_temperature_zero_disables_fallback(self, tmp_path):
        """Windows GPU 下 ctranslate2 温度回退导致 0xC0000409 崩溃（上游 issue #71）。
        device=cuda 时必须显式 temperature=0 禁用回退。"""
        audio_path = tmp_path / "test-temp.wav"
        _generate_silent_wav(audio_path)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())

        with patch(
            "faster_whisper.WhisperModel",
            return_value=mock_model,
        ):
            transcribe(audio_path, model_size="tiny", language="ja", device="cuda")

        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0

    def test_cpu_keeps_temperature_fallback(self, tmp_path):
        """CPU 无崩溃风险，保留默认温度回退以维持识别质量。"""
        audio_path = tmp_path / "test-temp-cpu.wav"
        _generate_silent_wav(audio_path)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())

        with patch(
            "faster_whisper.WhisperModel",
            return_value=mock_model,
        ):
            transcribe(audio_path, model_size="tiny", language="ja", device="cpu")

        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert "temperature" not in call_kwargs
