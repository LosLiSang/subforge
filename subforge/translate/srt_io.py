from __future__ import annotations

from dataclasses import replace

import copy
import re
import threading
from pathlib import Path

from subforge.models import SubtitleEntry

_TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _parse_timestamp(s: str) -> float:
    """Parse an SRT timestamp to seconds."""
    m = _TIMESTAMP_RE.match(s)
    if not m:
        raise ValueError(f"Invalid timestamp: {s}")
    return (
        int(m.group(1)) * 3600
        + int(m.group(2)) * 60
        + int(m.group(3))
        + int(m.group(4)) / 1000
    )


def subtitle_path(media_path: Path, language: str, output_dir: Path | None = None) -> Path:
    """Return the canonical language-tagged SRT path for a media file."""
    if not language or any(char in language for char in ("/", "\\", ".")):
        raise ValueError(f"Invalid language code: {language!r}")
    directory = output_dir if output_dir is not None else media_path.parent
    return directory / f"{media_path.stem}.{language}.srt"


def write_srt(entries: list[SubtitleEntry], path: Path) -> None:
    """Write a list of SubtitleEntries to an SRT file."""
    lines: list[str] = []
    for entry in entries:
        lines.append(str(entry.index))
        start_str = _format_timestamp(entry.start)
        end_str = _format_timestamp(entry.end)
        lines.append(f"{start_str} --> {end_str}")
        # 空文本条目写单个空格；清洗内部多余的双换行，防止打断 SRT 块分隔符
        raw_text = entry.text.strip()
        cleaned_text = re.sub(r"\n\s*\n+", "\n", raw_text) if raw_text else " "
        lines.append(cleaned_text)
        lines.append("")  # blank line separator
    path.write_text("\n".join(lines), encoding="utf-8")


# 进程内 SRT 解析缓存：按 (path, mtime, size) 失效，避免播放页每次请求都重新解析文件。
# 返回深拷贝，避免缓存被调用方原地修改（污染缓存命中）。
_srt_cache: dict[tuple[str, float, int], list[SubtitleEntry]] = {}
_srt_cache_lock = threading.Lock()


def read_srt(path: Path) -> list[SubtitleEntry]:
    """Parse an SRT file into a list of SubtitleEntries."""
    stat = path.stat()
    key = (str(path), stat.st_mtime, stat.st_size)
    with _srt_cache_lock:
        cached = _srt_cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
    content = path.read_text(encoding="utf-8")
    blocks = content.strip("\n").split("\n\n")
    entries: list[SubtitleEntry] = []
    for block in blocks:
        lines = block.split("\n")
        while lines and not lines[-1]:
            lines.pop()
        if len(lines) < 2:
            continue
        try:
            index = int(lines[0].strip())
            timing = lines[1].strip()
            start_str, end_str = timing.split(" --> ")
            start = _parse_timestamp(start_str.strip())
            end = _parse_timestamp(end_str.strip())
            text = "\n".join(lines[2:])
            entries.append(SubtitleEntry(index=index, start=start, end=end, text=text))
        except (ValueError, IndexError):
            if entries and block.strip():
                entries[-1] = replace(entries[-1], text=f"{entries[-1].text}\n{block.strip()}")
            continue
    with _srt_cache_lock:
        _srt_cache[key] = entries
    return copy.deepcopy(entries)
