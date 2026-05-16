from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from subforge.models import SubtitleEntry

logger = logging.getLogger(__name__)


def transcribe(
    file_path: Path,
    model_size: str = "medium",
    language: str = "ja",
    models_dir: Path | None = None,
    local_files_only: bool = False,
    progress_callback: Callable[[float], None] | None = None,
) -> list[SubtitleEntry]:
    """Transcribe audio file using faster-whisper.

    Args:
        file_path: Path to the audio/video file.
        model_size: Whisper model size (tiny/base/small/medium/large).
        language: Source language code (e.g. 'ja', 'en').
        models_dir: Directory for model storage. Uses faster-whisper default if None.
        local_files_only: If True, skip HuggingFace Hub network requests.
        progress_callback: Called with 0.0–1.0 progress after each segment.

    Returns:
        List of SubtitleEntry objects with timestamps.
    """
    from faster_whisper import WhisperModel

    kwargs = {}
    if models_dir is not None:
        kwargs["download_root"] = str(models_dir)

    def _load_model(local_only: bool) -> WhisperModel:
        logger.info("ASR: Loading model '%s' (local_files_only=%s)...",
                     model_size, local_only)
        return WhisperModel(
            model_size,
            device="cpu",
            compute_type="default",
            local_files_only=local_only,
            **kwargs,
        )

    model: WhisperModel
    if local_files_only:
        try:
            model = _load_model(True)
        except Exception:
            logger.warning("Local model '%s' load failed (%s), retrying with download.",
                           model_size, models_dir)
            model = _load_model(False)
    else:
        model = _load_model(False)

    logger.info("ASR: Transcribing %s...", file_path.name)
    segments, info = model.transcribe(
        str(file_path),
        language=language,
        beam_size=5,
        vad_filter=True,
    )

    total_duration = info.duration if info and info.duration else 0.0

    entries: list[SubtitleEntry] = []
    for idx, segment in enumerate(segments, start=1):
        entry = SubtitleEntry(
            index=idx,
            start=round(segment.start, 3),
            end=round(segment.end, 3),
            text=segment.text.strip(),
        )
        entries.append(entry)
        if progress_callback and total_duration > 0:
            progress = min(entry.end / total_duration, 1.0)
            progress_callback(progress)

    if progress_callback:
        progress_callback(1.0)

    logger.info("ASR: %d segments transcribed.", len(entries))
    return entries
