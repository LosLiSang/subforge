from __future__ import annotations

from pathlib import Path

import pytest

from subforge.models import SubtitleEntry
from subforge.segment_processing import (
    ExtractedAudio,
    SegmentRequest,
    WhisperSegmentAdapter,
    extract_audio_segment,
)


@pytest.mark.asyncio
async def test_whisper_segment_candidate_offsets_and_clips_timestamps(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"clip")
    calls = []

    def extractor(request):
        assert request.target_start == 10.0
        assert request.target_end == 12.0
        return ExtractedAudio(clip, start=8.0, end=14.0, temporary=False)

    def transcribe(path, **options):
        calls.append((path, options))
        return [
            SubtitleEntry(1, 0.0, 3.0, "包含左侧上下文"),
            SubtitleEntry(2, 3.0, 5.0, "目标内容"),
            SubtitleEntry(3, 5.1, 6.0, "只有右侧上下文"),
        ]

    async def translate(entries, source_language, target_language):
        assert source_language == "ja"
        assert target_language == "zh"
        return [SubtitleEntry(e.index, e.start, e.end, f"译:{e.text}") for e in entries]

    adapter = WhisperSegmentAdapter(
        extractor=extractor,
        transcribe_fn=transcribe,
        translate_fn=translate,
    )
    candidate = await adapter.process(SegmentRequest(
        media_path=tmp_path / "audio.m4a",
        target_start=10.0,
        target_end=12.0,
        source_language="ja",
        target_language="zh",
        asr_options={"model_size": "large-v3"},
    ))

    assert [(e.start, e.end, e.text) for e in candidate.source_entries] == [
        (10.0, 11.0, "包含左侧上下文"),
        (11.0, 12.0, "目标内容"),
    ]
    assert candidate.target_entries[1].text == "译:目标内容"
    assert calls == [(clip, {"model_size": "large-v3", "language": "ja"})]
    assert candidate.processor == "whisper"


@pytest.mark.asyncio
async def test_extraction_failure_never_calls_transcriber(tmp_path):
    called = False

    def extractor(_request):
        raise RuntimeError("ffmpeg failed")

    def transcribe(_path, **_options):
        nonlocal called
        called = True
        return []

    adapter = WhisperSegmentAdapter(extractor=extractor, transcribe_fn=transcribe)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        await adapter.process(SegmentRequest(tmp_path / "audio.m4a", 1.0, 2.0))
    assert called is False


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
