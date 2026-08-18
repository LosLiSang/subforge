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
        CUDA 可用时必须显式 temperature=0 禁用回退（含 device=auto 解析到 GPU）。"""
        audio_path = tmp_path / "test-temp.wav"
        _generate_silent_wav(audio_path)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())

        with (
            patch("faster_whisper.WhisperModel", return_value=mock_model),
            patch("subforge.asr.engine._cuda_available", return_value=True),
        ):
            transcribe(audio_path, model_size="tiny", language="ja", device="auto")

        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0

    def test_cpu_keeps_temperature_fallback(self, tmp_path):
        """无 CUDA 无崩溃风险，保留默认温度回退以维持识别质量。"""
        audio_path = tmp_path / "test-temp-cpu.wav"
        _generate_silent_wav(audio_path)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())

        with (
            patch("faster_whisper.WhisperModel", return_value=mock_model),
            patch("subforge.asr.engine._cuda_available", return_value=False),
        ):
            transcribe(audio_path, model_size="tiny", language="ja", device="cpu")

        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert "temperature" not in call_kwargs


class TestStereoMerge:
    def test_left_only_content_uses_left(self):
        """左侧有语音、右侧空 → 用左侧内容。"""
        from subforge.asr.engine import _merge_stereo_sides
        left = [SubtitleEntry(1, 10.0, 15.0, "左侧语音")]
        merged = _merge_stereo_sides(left, [])
        assert len(merged) == 1
        assert merged[0].text == "左侧语音"
        assert merged[0].start == 10.0 and merged[0].end == 15.0

    def test_right_only_content_uses_right(self):
        """右侧有语音、左侧空 → 用右侧内容（ASMR 单侧耳语场景）。"""
        from subforge.asr.engine import _merge_stereo_sides
        right = [SubtitleEntry(1, 30.0, 38.0, "右侧语音")]
        merged = _merge_stereo_sides([], right)
        assert len(merged) == 1
        assert merged[0].text == "右侧语音"

    def test_alternating_sides_merge_by_time_window(self):
        """两侧交替说话 → 按时间窗选语音侧，合并为一条连续字幕。"""
        from subforge.asr.engine import _merge_stereo_sides
        left = [SubtitleEntry(1, 0.0, 5.0, "左一句")]
        right = [SubtitleEntry(1, 6.0, 10.0, "右一句")]
        merged = _merge_stereo_sides(left, right)
        assert [e.text for e in merged] == ["左一句", "右一句"]
        assert merged[0].end <= merged[1].start  # 时间不重叠

    def test_overlapping_sides_prefer_side_with_longer_text(self):
        """同一时间窗两侧都有内容 → 取文本更长（更完整）的一侧。"""
        from subforge.asr.engine import _merge_stereo_sides
        left = [SubtitleEntry(1, 0.0, 10.0, "左")]
        right = [SubtitleEntry(1, 0.0, 10.0, "右侧更完整的句子")]
        merged = _merge_stereo_sides(left, right)
        assert len(merged) == 1
        assert merged[0].text == "右侧更完整的句子"

    def test_non_overlapping_same_side_keeps_order(self):
        """同一侧连续多段 → 顺序保持。"""
        from subforge.asr.engine import _merge_stereo_sides
        right = [
            SubtitleEntry(1, 0.0, 5.0, "第一句"),
            SubtitleEntry(2, 5.5, 9.0, "第二句"),
        ]
        merged = _merge_stereo_sides([], right)
        assert [e.text for e in merged] == ["第一句", "第二句"]
