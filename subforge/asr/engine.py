from __future__ import annotations

import sys
from pathlib import Path

from subforge.models import SubtitleEntry


def transcribe(
    file_path: Path,
    model_size: str = "medium",
    language: str = "ja",
    models_dir: Path | None = None,
) -> list[SubtitleEntry]:
    """Transcribe audio file using faster-whisper.

    Args:
        file_path: Path to the audio/video file.
        model_size: Whisper model size (tiny/base/small/medium/large).
        language: Source language code (e.g. 'ja', 'en').
        models_dir: Directory for model storage. Uses faster-whisper default if None.

    Returns:
        List of SubtitleEntry objects with timestamps.
    """
    from faster_whisper import WhisperModel

    kwargs = {}
    if models_dir is not None:
        kwargs["download_root"] = str(models_dir)

    print(f"ASR: Loading model '{model_size}'...", file=sys.stderr)
    model = WhisperModel(model_size, device="cpu", compute_type="default", **kwargs)

    print(f"ASR: Transcribing {file_path.name}...", file=sys.stderr)
    segments, _info = model.transcribe(
        str(file_path),
        language=language,
        beam_size=5,
        vad_filter=True,
    )

    entries: list[SubtitleEntry] = []
    for idx, segment in enumerate(segments, start=1):
        entry = SubtitleEntry(
            index=idx,
            start=round(segment.start, 3),
            end=round(segment.end, 3),
            text=segment.text.strip(),
        )
        entries.append(entry)

    print(f"ASR: {len(entries)} segments transcribed.", file=sys.stderr)
    return entries
