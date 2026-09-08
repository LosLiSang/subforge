from __future__ import annotations

import asyncio
import inspect
import math
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from subforge.asr.engine import _audio_duration_seconds, transcribe
from subforge.models import SubtitleEntry

_FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


class SegmentProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class SegmentRequest:
    media_path: Path
    target_start: float
    target_end: float
    context_before: float = 2.0
    context_after: float = 2.0
    source_language: str = "ja"
    target_language: str = "zh"
    processing_mode: str = "transcribe_then_translate"
    recognition_prompt: str = ""
    media_duration: float | None = None
    asr_options: dict = field(default_factory=dict)


@dataclass
class ExtractedAudio:
    path: Path
    start: float
    end: float
    temporary: bool = True

    def cleanup(self) -> None:
        if self.temporary:
            self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class SegmentCandidate:
    source_entries: list[SubtitleEntry]
    target_entries: list[SubtitleEntry]
    processor: str
    target_start: float
    target_end: float
    warnings: tuple[str, ...] = ()


class SegmentProcessor(Protocol):
    async def process(self, request: SegmentRequest) -> SegmentCandidate: ...


def extract_audio_segment(
    request: SegmentRequest,
    *,
    duration_resolver: Callable[[Path], float] = _audio_duration_seconds,
) -> ExtractedAudio:
    """Extract a mono 16 kHz WAV including bounded context around the target."""
    target_start = float(request.target_start)
    target_end = float(request.target_end)
    if not math.isfinite(target_start) or not math.isfinite(target_end) or target_start < 0 or target_start >= target_end:
        raise ValueError("片段时间范围无效")
    duration = request.media_duration
    if duration is None:
        duration = duration_resolver(request.media_path)
    if duration and target_end > duration + 0.001:
        raise ValueError("片段结束时间超过媒体时长")
    clip_start = max(0.0, target_start - max(0.0, request.context_before))
    clip_end = target_end + max(0.0, request.context_after)
    if duration:
        clip_end = min(duration, clip_end)

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    handle.close()
    output = Path(handle.name)
    command = [
        _FFMPEG, "-y",
        "-ss", f"{clip_start:.3f}",
        "-i", str(request.media_path),
        "-t", f"{clip_end - clip_start:.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(output),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
        )
    except (OSError, subprocess.SubprocessError) as exc:
        output.unlink(missing_ok=True)
        raise SegmentProcessingError(f"音频片段截取失败：{type(exc).__name__}") from exc
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 44:
        output.unlink(missing_ok=True)
        detail = (result.stderr or "ffmpeg failed").strip().splitlines()[-1][:300]
        raise SegmentProcessingError(f"音频片段截取失败：{detail}")
    return ExtractedAudio(output, round(clip_start, 3), round(clip_end, 3))


TranslateFn = Callable[[list[SubtitleEntry], str, str], Awaitable[list[SubtitleEntry]] | list[SubtitleEntry]]


class WhisperSegmentAdapter:
    def __init__(
        self,
        *,
        extractor: Callable[[SegmentRequest], ExtractedAudio] = extract_audio_segment,
        transcribe_fn: Callable = transcribe,
        translate_fn: TranslateFn | None = None,
    ) -> None:
        self._extractor = extractor
        self._transcribe = transcribe_fn
        self._translate = translate_fn

    async def process(self, request: SegmentRequest) -> SegmentCandidate:
        extracted = await asyncio.to_thread(self._extractor, request)
        try:
            options = dict(request.asr_options)
            options.setdefault("language", request.source_language)
            entries = await asyncio.to_thread(self._transcribe, extracted.path, **options)
            source: list[SubtitleEntry] = []
            for entry in entries:
                absolute_start = extracted.start + float(entry.start)
                absolute_end = extracted.start + float(entry.end)
                if absolute_end <= request.target_start or absolute_start >= request.target_end:
                    continue
                start = max(request.target_start, absolute_start)
                end = min(request.target_end, absolute_end)
                text = entry.text.strip()
                if text and start < end:
                    source.append(SubtitleEntry(len(source) + 1, round(start, 3), round(end, 3), text))
            if not source:
                raise SegmentProcessingError("片段 ASR 未产生可用文本")

            target: list[SubtitleEntry] = []
            if self._translate is not None:
                translated = self._translate(source, request.source_language, request.target_language)
                target = await translated if inspect.isawaitable(translated) else translated
                if len(target) != len(source) or any(not entry.text.strip() for entry in target):
                    raise SegmentProcessingError("片段翻译未返回完整结果")
                target = [
                    SubtitleEntry(index, source[index - 1].start, source[index - 1].end, entry.text.strip())
                    for index, entry in enumerate(target, start=1)
                ]
            return SegmentCandidate(
                source_entries=source,
                target_entries=target,
                processor="whisper",
                target_start=request.target_start,
                target_end=request.target_end,
            )
        finally:
            extracted.cleanup()
