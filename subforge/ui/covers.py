"""Auto-extract embedded audio cover art (attached picture) into the library cache.

MP3/M4A/FLAC files often embed cover art in their tags (ID3 APIC, MP4 covr,
FLAC picture block). We extract it once with ffmpeg into
``<library>/.subforge/covers/<item_id>.jpg`` and serve it via ``/covers/{id}``.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def covers_dir(library_root: Path) -> Path:
    return library_root / ".subforge" / "covers"


def autocrop_black_borders(image_path: Path, timeout: float = 10.0) -> None:
    """Detect and crop letterboxed black borders/bars from a cover image if present."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or not image_path.is_file():
        return
    try:
        detect_cmd = [
            ffmpeg, "-y", "-loglevel", "info",
            "-loop", "1", "-t", "0.1",
            "-i", str(image_path),
            "-vf", "cropdetect=24:16:0",
            "-f", "null", "-",
        ]
        proc = subprocess.run(detect_cmd, capture_output=True, text=True, timeout=timeout)
        crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", proc.stderr)
        if not crops:
            return
        w, h, x, y = map(int, crops[-1])
        if x > 10 or y > 10:
            tmp_path = image_path.with_name(f".{image_path.stem}.cropped.jpg")
            crop_cmd = [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", str(image_path),
                "-vf", f"crop={w}:{h}:{x}:{y}",
                "-c:v", "mjpeg", "-q:v", "3",
                str(tmp_path),
            ]
            crop_res = subprocess.run(crop_cmd, capture_output=True, timeout=timeout)
            if crop_res.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
                tmp_path.replace(image_path)
            else:
                tmp_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("Cover autocrop skipped: %s", exc)


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
    autocrop_black_borders(cache_path, timeout=timeout)
    return cache_path


def replace_cover(library_root: Path, item_id: str, source: Path) -> Path:
    """Normalize a user-selected JPG/PNG/WebP image into the cover cache."""
    source = source.resolve()
    if not source.is_file() or source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("cover must be a JPG, PNG, or WebP image")
    destination = covers_dir(library_root) / f"{item_id}.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    (covers_dir(library_root) / f"{item_id}.nocover").unlink(missing_ok=True)
    if source.suffix.lower() in {".jpg", ".jpeg"}:
        temporary = destination.with_name(f".{destination.stem}.tmp.jpg")
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
        autocrop_black_borders(destination)
        return destination
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ValueError("ffmpeg is required to convert PNG/WebP covers")
    temporary = destination.with_name(f".{destination.stem}.tmp.jpg")
    result = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-frames:v", "1", str(temporary)],
        capture_output=True,
    )
    if result.returncode != 0 or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise ValueError("failed to convert cover image")
    temporary.replace(destination)
    autocrop_black_borders(destination)
    return destination


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
    no_cover_sentinel = covers_dir(library_root) / f"{item_id}.nocover"
    if no_cover_sentinel.exists():
        return None
    if media_path is None or not media_path.exists():
        return None
    result = extract_cover(media_path, cache_path)
    if result is None:
        try:
            no_cover_sentinel.touch(exist_ok=True)
        except OSError:
            pass
    return result


def is_valid_image_bytes(content: bytes, filename: str = "") -> bool:
    if len(content) < 8:
        return False
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if content.startswith(b"\xff\xd8\xff"):
        return True
    if content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return True
    if content.startswith(b"GIF8"):
        return True
    head = content[:256].strip()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head:
        return True
    return False


def parse_multipart_data(body: bytes, content_type: str) -> tuple[bytes, str, dict[str, str]]:
    fields: dict[str, str] = {}
    file_bytes = b""
    filename = "cover.png"
    if "boundary=" not in content_type:
        return file_bytes, filename, fields
    boundary = content_type.split("boundary=")[1].split(";")[0].strip().strip('"').encode("latin-1")
    delimiter = b"--" + boundary
    parts = body.split(delimiter)
    for part in parts:
        part = part.strip()
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_header, raw_content = part.split(b"\r\n\r\n", 1)
        raw_content = raw_content.rstrip(b"\r\n")
        header_text = raw_header.decode("utf-8", errors="ignore")
        name_match = re.search(r'name=["\']?([^"\';\r\n]+)["\']?', header_text)
        if not name_match:
            continue
        field_name = name_match.group(1)
        file_match = re.search(r'filename=["\']?([^"\';\r\n]+)["\']?', header_text)
        if file_match:
            filename = file_match.group(1)
            file_bytes = raw_content
        else:
            fields[field_name] = raw_content.decode("utf-8", errors="ignore")
    return file_bytes, filename, fields


def get_preset_cover_svg(preset: str = "default") -> str:
    preset = (preset or "default").lower().strip()
    if preset == "headphones":
        bg_start, bg_end = "#1e1433", "#090710"
        accent = "#a855f7"
        title = "ASMR VOICE"
        icon_path = (
            f'<path d="M120 280 C120 180, 180 120, 250 120 C320 120, 380 180, 380 280" fill="none" stroke="{accent}" stroke-width="20" stroke-linecap="round"/>'
            f'<rect x="100" y="270" width="40" height="90" rx="20" fill="{accent}"/>'
            f'<rect x="360" y="270" width="40" height="90" rx="20" fill="{accent}"/>'
            f'<circle cx="250" cy="270" r="30" fill="{accent}" opacity="0.4"/>'
        )
    elif preset == "wave":
        bg_start, bg_end = "#081c24", "#061218"
        accent = "#06b6d4"
        title = "BINAURAL STEREO"
        icon_path = (
            f'<line x1="130" y1="250" x2="130" y2="250" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="160" y1="210" x2="160" y2="290" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="190" y1="170" x2="190" y2="330" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="220" y1="230" x2="220" y2="270" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="250" y1="130" x2="250" y2="370" stroke="{accent}" stroke-width="16" stroke-linecap="round"/>'
            f'<line x1="280" y1="200" x2="280" y2="300" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="310" y1="160" x2="310" y2="340" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="340" y1="220" x2="340" y2="280" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="370" y1="250" x2="370" y2="250" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
        )
    elif preset == "studio":
        bg_start, bg_end = "#261908", "#0c0803"
        accent = "#f59e0b"
        title = "STUDIO RECORDING"
        icon_path = (
            f'<rect x="215" y="140" width="70" height="130" rx="35" fill="none" stroke="{accent}" stroke-width="16"/>'
            f'<line x1="215" y1="200" x2="285" y2="200" stroke="{accent}" stroke-width="8"/>'
            f'<path d="M185 220 C185 295, 315 295, 315 220" fill="none" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
            f'<line x1="250" y1="295" x2="250" y2="350" stroke="{accent}" stroke-width="14"/>'
            f'<line x1="200" y1="350" x2="300" y2="350" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>'
        )
    else:  # default SubForge ASMR aesthetic
        bg_start, bg_end = "#121824", "#080b10"
        accent = "#38bdf8"
        title = "SUBFORGE AUDIO"
        icon_path = (
            f'<circle cx="250" cy="235" r="105" fill="none" stroke="{accent}" stroke-width="4" stroke-dasharray="8 8" opacity="0.4"/>'
            f'<path d="M150 250 C150 160, 200 120, 250 120 C300 120, 350 160, 350 250" fill="none" stroke="{accent}" stroke-width="18" stroke-linecap="round"/>'
            f'<rect x="135" y="235" width="36" height="75" rx="16" fill="{accent}"/>'
            f'<rect x="329" y="235" width="36" height="75" rx="16" fill="{accent}"/>'
            f'<path d="M225 240 L245 220 L245 260 Z" fill="{accent}"/>'
            f'<path d="M255 225 C265 235, 265 245, 255 255" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>'
            f'<path d="M265 215 C280 230, 280 250, 265 265" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500" width="500" height="500">'
        f'<defs>'
        f'<radialGradient id="cardBg" cx="50%" cy="40%" r="60%">'
        f'<stop offset="0%" stop-color="{bg_start}"/>'
        f'<stop offset="100%" stop-color="{bg_end}"/>'
        f'</radialGradient>'
        f'<filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
        f'<feGaussianBlur stdDeviation="15" result="blur"/>'
        f'<feComposite in="SourceGraphic" in2="blur" operator="over"/>'
        f'</filter>'
        f'</defs>'
        f'<rect width="500" height="500" fill="url(#cardBg)"/>'
        f'<rect x="2" y="2" width="496" height="496" rx="24" fill="none" stroke="{accent}" stroke-width="2" opacity="0.18"/>'
        f'<g filter="url(#glow)">{icon_path}</g>'
        f'<g transform="translate(250, 420)">'
        f'<rect x="-100" y="-18" width="200" height="36" rx="18" fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.12)" stroke-width="1"/>'
        f'<text text-anchor="middle" y="6" fill="{accent}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="12" font-weight="700" letter-spacing="2">{title}</text>'
        f'</g>'
        f'</svg>'
    )
