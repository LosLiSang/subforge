"""Auto-extract embedded audio cover art (attached picture) into the library cache.

MP3/M4A/FLAC files often embed cover art in their tags (ID3 APIC, MP4 covr,
FLAC picture block). We extract it once with ffmpeg into
``<library>/.subforge/covers/<item_id>.jpg`` and serve it via ``/covers/{id}``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def covers_dir(library_root: Path) -> Path:
    return library_root / ".subforge" / "covers"


def extract_cover(media_path: Path, cache_path: Path, timeout: float = 30.0) -> Path | None:
    """Extract the first attached picture from an audio file into cache_path.

    Uses ffmpeg's attached-pic handling (``-map 0:v:0``). Returns the cache
    path on success, or None when the file has no cover art / ffmpeg fails.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # -map 0:v:0 selects only the attached picture stream; -frames:v 1 writes one image.
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-i", str(media_path),
        "-map", "0:v:0", "-frames:v", "1",
        "-c:v", "mjpeg", "-q:v", "3",
        str(cache_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Cover extraction failed (%s): %s", type(exc).__name__, exc)
        cache_path.unlink(missing_ok=True)
        return None
    if result.returncode != 0 or not cache_path.exists() or cache_path.stat().st_size == 0:
        cache_path.unlink(missing_ok=True)
        return None
    return cache_path


def cover_for_item(
    library_root: Path,
    item_id: str,
    media_path: Path | None,
) -> Path | None:
    """Return the cached cover path for an item, extracting it on demand.

    Returns None when there is no media file or no embedded cover.
    """
    cache_path = covers_dir(library_root) / f"{item_id}.jpg"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path
    if media_path is None or not media_path.exists():
        return None
    return extract_cover(media_path, cache_path)
