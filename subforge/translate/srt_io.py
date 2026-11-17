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


_FLEX_TIMESTAMP_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
)
_LRC_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")
_VTT_TAG_RE = re.compile(r"</?(?:c|v|b|i|u|ruby|rt|lang)[^>]*>")


def _parse_flex_timestamp(raw: str) -> float:
    m = _FLEX_TIMESTAMP_RE.match(raw.strip())
    if not m:
        raise ValueError(f"Invalid timestamp: {raw}")
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2))
    seconds = int(m.group(3))
    frac = m.group(4)
    millis = int(frac.ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def _parse_ass_timestamp(raw: str) -> float:
    parts = raw.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid ASS timestamp: {raw}")
    hours = int(parts[0])
    minutes = int(parts[1])
    sec_parts = parts[2].split(".")
    seconds = int(sec_parts[0])
    centis = int((sec_parts[1] if len(sec_parts) > 1 else "0").ljust(2, "0")[:2])
    return hours * 3600 + minutes * 60 + seconds + centis / 100.0


def parse_subtitle_text(raw: str, ext: str) -> list[SubtitleEntry]:
    """Parse .srt, .vtt, .lrc, or .ass/.ssa subtitle text into normalized SubtitleEntries."""
    text = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    fmt = ext.lower().lstrip(".")
    entries: list[SubtitleEntry] = []

    if fmt in {"srt", "vtt"}:
        blocks = re.split(r"\n\s*\n+", text.strip())
        for block in blocks:
            lines = [line for line in block.split("\n") if line.strip() != ""]
            if not lines:
                continue
            if fmt == "vtt":
                head = lines[0].strip()
                if head.startswith("WEBVTT") or head.startswith(("NOTE", "STYLE", "REGION")):
                    continue
            cue_idx = None
            for idx, line in enumerate(lines):
                if "-->" in line:
                    cue_idx = idx
                    break
            if cue_idx is None:
                continue
            timing = lines[cue_idx]
            start_part, end_rest = timing.split("-->", 1)
            end_part = end_rest.strip().split(" ", 1)[0]
            try:
                start = _parse_flex_timestamp(start_part)
                end = _parse_flex_timestamp(end_part)
            except ValueError:
                continue
            if end <= start:
                continue
            cue_text = "\n".join(lines[cue_idx + 1:]).strip()
            if fmt == "vtt":
                cue_text = _VTT_TAG_RE.sub("", cue_text).strip()
            if cue_text:
                entries.append(SubtitleEntry(len(entries) + 1, round(start, 3), round(end, 3), cue_text))
        return entries

    if fmt == "lrc":
        timed_lines: list[tuple[float, str]] = []
        for line in text.split("\n"):
            matches = list(_LRC_TAG_RE.finditer(line))
            if not matches:
                continue
            lyric = _LRC_TAG_RE.sub("", line).strip()
            if not lyric:
                continue
            for m in matches:
                mins = int(m.group(1))
                secs = int(m.group(2))
                frac = m.group(3) or "0"
                millis = int(frac.ljust(3, "0")[:3]) if len(frac) == 3 else int(frac.ljust(2, "0")[:2]) * 10
                timed_lines.append((mins * 60 + secs + millis / 1000.0, lyric))
        timed_lines.sort(key=lambda item: item[0])
        for i, (start, lyric) in enumerate(timed_lines):
            next_start = timed_lines[i + 1][0] if i + 1 < len(timed_lines) else start + 5.0
            end = next_start if next_start > start else start + 3.0
            entries.append(SubtitleEntry(i + 1, round(start, 3), round(end, 3), lyric))
        return entries

    if fmt in {"ass", "ssa"}:
        in_events = False
        fields = ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_events = stripped.lower() == "[events]"
                continue
            if not in_events:
                continue
            if stripped.lower().startswith("format:"):
                fields = [f.strip() for f in stripped.split(":", 1)[1].split(",")]
                continue
            if not stripped.lower().startswith("dialogue:"):
                continue
            payload = stripped.split(":", 1)[1].lstrip()
            parts = payload.split(",", len(fields) - 1)
            if len(parts) < len(fields):
                continue
            row = dict(zip(fields, parts))
            try:
                start = _parse_ass_timestamp(row["Start"])
                end = _parse_ass_timestamp(row["End"])
            except (KeyError, ValueError):
                continue
            if end <= start:
                continue
            cue_text = _ASS_TAG_RE.sub("", row.get("Text", ""))
            cue_text = cue_text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ").strip()
            if cue_text:
                entries.append(SubtitleEntry(len(entries) + 1, round(start, 3), round(end, 3), cue_text))
        return entries

    raise ValueError(f"Unsupported subtitle format: {ext}")


def _format_vtt_timestamp(seconds: float) -> str:
    return _format_timestamp(seconds).replace(",", ".")


def format_vtt(entries: list[SubtitleEntry]) -> str:
    lines = ["WEBVTT", ""]
    for entry in entries:
        lines.append(f"{_format_vtt_timestamp(entry.start)} --> {_format_vtt_timestamp(entry.end)}")
        cleaned = re.sub(r"\n\s*\n+", "\n", entry.text.strip()) if entry.text.strip() else " "
        lines.append(cleaned)
        lines.append("")
    return "\n".join(lines)


def format_lrc(entries: list[SubtitleEntry]) -> str:
    lines: list[str] = []
    for entry in entries:
        total_mins = int(entry.start // 60)
        secs = int(entry.start % 60)
        centis = int(round((entry.start - int(entry.start)) * 100))
        if centis == 100:
            secs += 1
            centis = 0
        text = " ".join(part.strip() for part in entry.text.splitlines() if part.strip())
        if text:
            lines.append(f"[{total_mins:02d}:{secs:02d}.{centis:02d}]{text}")
    return "\n".join(lines) + ("\n" if lines else "")
