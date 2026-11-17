from __future__ import annotations

import math
import shutil
import subprocess
import wave
from pathlib import Path

_FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _positive_duration(value) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 0.0
    return duration if math.isfinite(duration) and duration > 0 else 0.0


def _audio_duration_seconds(input_path: Path) -> float:
    """Read media duration via WAV header or ffprobe."""
    if input_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(input_path), "rb") as audio:
                frame_rate = audio.getframerate()
                if frame_rate > 0:
                    return audio.getnframes() / frame_rate
        except (OSError, EOFError, wave.Error):
            pass
    ffprobe = shutil.which("ffprobe") or str(Path(_FFMPEG).with_name("ffprobe"))
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
            capture_output=True, text=True, timeout=15,
        )
        return _positive_duration(result.stdout.strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0
