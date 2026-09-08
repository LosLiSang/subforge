from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from subforge.asr import engine


@pytest.fixture()
def mono_wav(tmp_path: Path) -> Path:
    path = tmp_path / "mono.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x01" * 16000)
    return path


def test_preprocess_audio_returns_output_for_valid_input(mono_wav: Path):
    pytest.importorskip("shutil")
    import shutil

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    result = engine._preprocess_audio(mono_wav)
    try:
        assert result is not None
        assert result != mono_wav
        assert result.is_file()
        with wave.open(str(result), "rb") as audio:
            assert audio.getframerate() == 16000
    finally:
        if result is not None and result != mono_wav:
            result.unlink(missing_ok=True)


def test_transcribe_mono_with_preprocess_does_not_receive_none(mono_wav: Path, monkeypatch):
    """回归：_preprocess_audio 曾在成功路径漏 return，单声道 + ASMR 预设直接崩溃。"""
    pytest.importorskip("shutil")
    import shutil

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")

    received: list[object] = []

    class _FakeModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, path, **_kwargs):
            received.append(path)
            return iter([]), type("Info", (), {"duration": 1.0})()

    monkeypatch.setattr("faster_whisper.WhisperModel", _FakeModel)
    monkeypatch.setattr(engine, "_cuda_available", lambda: False)
    monkeypatch.setattr(engine, "_is_stereo", lambda _path: False)
    engine.transcribe(
        mono_wav, model_size="tiny", language="ja",
        models_dir=Path("/nonexistent"), local_files_only=True,
        preprocess_audio=True,
    )
    assert received and received[0] is not None
