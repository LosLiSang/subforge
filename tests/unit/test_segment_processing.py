from __future__ import annotations

import pytest

from subforge.segment_processing import SegmentRequest, extract_audio_segment


def test_extract_audio_segment_expands_context_and_uses_real_ffmpeg(tmp_path):
    pytest.importorskip("subprocess")
    import shutil
    import subprocess
    import wave

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000 * 5)

    extracted = extract_audio_segment(SegmentRequest(
        media_path=source,
        target_start=2.0,
        target_end=3.0,
        context_before=1.5,
        context_after=1.0,
        media_duration=5.0,
    ))
    try:
        assert extracted.start == 0.5
        assert extracted.end == 4.0
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(extracted.path)],
            capture_output=True, text=True, check=True,
        )
        assert float(probe.stdout.strip()) == pytest.approx(3.5, abs=0.1)
    finally:
        extracted.cleanup()
