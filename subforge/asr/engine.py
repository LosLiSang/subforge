from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Callable

from subforge.models import SubtitleEntry

logger = logging.getLogger(__name__)

_FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _preprocess_audio(input_path: Path) -> Path:
    """Normalize audio for VAD: mono, 16kHz, loudness-normalized.

    ASMR whispered audio sits at -40 to -50 dB — VAD can't distinguish it
    from silence. loudnorm with a low target I (-12 LUFS) and tight LRA (7)
    brings whispers up to a level where Silero VAD can work.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out_path = Path(tmp.name)

    # loudnorm: I=-12 LUFS (louder than broadcast -24), TP=-0.5 peak,
    # LRA=7 limits dynamic range so whispers don't get crushed back down
    cmd = [
        _FFMPEG, "-y", "-i", str(input_path),
        "-ac", "1",
        "-ar", "16000",
        "-af", "loudnorm=I=-12:TP=-0.5:LRA=7:linear=true",
        "-f", "wav",
        str(out_path),
    ]
    logger.info("ASR: Preprocessing audio (mono + loudnorm)...")
    try:
        subprocess.run(
            cmd, check=True, capture_output=True,
            encoding="utf-8", errors="replace",
        )
    except subprocess.CalledProcessError as e:
        logger.warning("ASR: ffmpeg preprocessing failed: %s",
                       e.stderr.strip() if e.stderr else str(e))
        out_path.unlink(missing_ok=True)
        return input_path  # fall back to original
    except FileNotFoundError:
        logger.warning("ASR: ffmpeg not found, skipping preprocessing")
        out_path.unlink(missing_ok=True)
        return input_path

    # Verify the output has actual audio content
    size_kb = out_path.stat().st_size / 1024
    logger.info("ASR: Preprocessed audio: %.1f kB", size_kb)
    if size_kb < 10:
        logger.warning("ASR: Preprocessed file too small (%.1f kB), using original", size_kb)
        out_path.unlink(missing_ok=True)
        return input_path


def _extract_channel(input_path: Path, channel: str, tmp_suffix: str = ".wav") -> Path:
    """Extract one channel (FL/FR) as a mono 16kHz wav with loudnorm, like _preprocess_audio."""
    tmp = tempfile.NamedTemporaryFile(suffix=tmp_suffix, delete=False)
    tmp.close()
    out_path = Path(tmp.name)
    cmd = [
        _FFMPEG, "-y", "-i", str(input_path),
        "-map", "0:a:0",
        "-af", f"pan=mono|c0={channel},loudnorm=I=-12:TP=-0.5:LRA=7:linear=true",
        "-ar", "16000",
        "-f", "wav",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, encoding="utf-8", errors="replace")
    except (subprocess.CalledProcessError, FileNotFoundError):
        out_path.unlink(missing_ok=True)
        return input_path
    return out_path


def _merge_stereo_sides(
    left_entries: list[SubtitleEntry],
    right_entries: list[SubtitleEntry],
) -> list[SubtitleEntry]:
    """Merge per-side ASR results into one timeline by picking the speech side.

    ASMR binaural audio often has speech alternating between ears (left ear
    one line, right ear the next). Averaging both channels into mono halves
    the speech energy, so VAD drops whole segments (a 30s speech block can
    disappear entirely). We instead transcribe each channel separately and
    merge per time window:
      - a window where only one side has content uses that side;
      - overlapping windows prefer the side with the longer (more complete)
        text, keeping the other side's whisper when it is identifiable;
      - non-overlapping segments are kept in chronological order.
    """
    segments: list[tuple[float, float, str]] = []  # (start, end, text)

    def _add(side_segments: list[SubtitleEntry], side: str) -> None:
        for e in side_segments:
            if e.text and e.text.strip():
                segments.append((e.start, e.end, e.text.strip()))

    _add(left_entries, "L")
    _add(right_entries, "R")

    if not segments:
        return []

    # Sort by start time; for ties prefer the longer text (more complete side).
    segments.sort(key=lambda s: (s[0], -(len(s[2]))))

    merged: list[tuple[float, float, str]] = []
    for start, end, text in segments:
        if not merged:
            merged.append((start, end, text))
            continue
        prev_start, prev_end, prev_text = merged[-1]
        # Overlap: same time window spoken on both sides — keep the more complete
        # (longer) one; if the new one wins, replace. Slight overlaps from
        # per-side VAD padding are normal.
        if start < prev_end:
            if len(text) > len(prev_text):
                merged[-1] = (min(prev_start, start), max(prev_end, end), text)
            # else keep previous (longer) entry
            continue
        merged.append((start, end, text))

    return [
        SubtitleEntry(index=i + 1, start=round(s, 3), end=round(e, 3), text=t)
        for i, (s, e, t) in enumerate(merged)
    ]


def _cuda_available() -> bool:
    """Detect whether ctranslate2 can use CUDA (device=auto resolves to GPU)."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _is_stereo(input_path: Path) -> bool:
    """Detect whether the audio has more than one channel (needs ffprobe)."""
    ffprobe = shutil.which("ffprobe") or str(Path(_FFMPEG).with_name("ffprobe"))
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=channels", "-of", "csv=p=0", str(input_path)],
            capture_output=True, text=True, timeout=15,
        )
        channels = result.stdout.strip()
        return channels.isdigit() and int(channels) > 1
    except (subprocess.SubprocessError, OSError, ValueError):
        return False


def _positive_duration(value) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 0.0
    return duration if math.isfinite(duration) and duration > 0 else 0.0


def _audio_duration_seconds(input_path: Path) -> float:
    """Read media duration without relying on faster-whisper metadata."""
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


def transcribe(
    file_path: Path,
    model_size: str = "medium",
    language: str = "ja",
    models_dir: Path | None = None,
    local_files_only: bool = False,
    device: str = "cpu",
    compute_type: str = "default",
    vad_filter: bool = True,
    vad_threshold: float = 0.5,
    vad_min_speech_duration_ms: int = 250,
    vad_min_silence_duration_ms: int = 2000,
    vad_speech_pad_ms: int = 400,
    vad_max_speech_duration_s: float = float("inf"),
    condition_on_previous_text: bool = True,
    no_speech_threshold: float = 0.6,
    preprocess_audio: bool = False,
    progress_callback: Callable[[float], None] | None = None,
    model_ready_callback: Callable[[], None] | None = None,
) -> list[SubtitleEntry]:
    """Transcribe audio file using faster-whisper.

    Args:
        file_path: Path to the audio/video file.
        model_size: Whisper model size (tiny/base/small/medium/large).
        language: Source language code (e.g. 'ja', 'en').
        models_dir: Directory for model storage. Uses faster-whisper default if None.
        local_files_only: If True, skip HuggingFace Hub network requests.
        preprocess_audio: If True, run ffmpeg loudnorm + mono before ASR.
            Essential for ASMR whispered audio so VAD can detect speech.
        vad_filter: If True, filter out non-speech with VAD.
        vad_threshold: Speech probability threshold. Lower = more sensitive
            to quiet speech (0.5 default; 0.2–0.3 for ASMR).
        vad_min_speech_duration_ms: Minimum speech chunk in ms. Lower to keep
            short utterances like gasps (250 default; 100 for ASMR).
        vad_min_silence_duration_ms: Minimum silence between chunks in ms.
            Lower to split sentences more finely (2000 default; 300 for ASMR).
        vad_speech_pad_ms: Padding around speech segments in ms. Raise to
            prevent clipping of leading/trailing consonants (400; 600 for ASMR).
        vad_max_speech_duration_s: Max segment duration in seconds. Lower to
            reduce hallucination drift (inf default; 20 for ASMR).
        condition_on_previous_text: If True, use previous segment as prompt.
            MUST be False for ASMR to prevent hallucination propagation.
        no_speech_threshold: Threshold for silence detection in Whisper.
            Lower to be more sensitive (0.6 default; 0.3 for ASMR).
        progress_callback: Called with 0.0–1.0 progress after each segment.
        model_ready_callback: Called after the model is loaded and before transcription.

    Returns:
        List of SubtitleEntry objects with timestamps.
    """
    from faster_whisper import WhisperModel

    kwargs = {}
    if models_dir is not None:
        kwargs["download_root"] = str(models_dir)

    def _load_model(local_only: bool) -> WhisperModel:
        logger.info("ASR: Loading model '%s' device=%s compute=%s (local_files_only=%s)...",
                     model_size, device, compute_type, local_only)
        return WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
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

    if model_ready_callback:
        model_ready_callback()

    # Preprocess audio if requested (essential for ASMR whispered audio)
    working_path = file_path
    if preprocess_audio:
        working_path = _preprocess_audio(file_path)

    def _run_transcribe(
        wav_path: Path,
        *,
        progress_base: float = 0.0,
        progress_span: float = 1.0,
    ) -> list[SubtitleEntry]:
        """Run ASR on one audio file, reporting progress on an absolute 0–1 range."""
        try:
            logger.info("ASR: Transcribing %s...", Path(wav_path).name)
            transcribe_kwargs: dict = {
                "language": language,
                "beam_size": 5,
                "vad_filter": vad_filter,
                "condition_on_previous_text": condition_on_previous_text,
                "no_speech_threshold": no_speech_threshold,
            }
            # Windows GPU 下 ctranslate2 的温度回退会在模型释放时触发 __fastfail
            # （0xC0000409 / 退出码 3221226505，上游 issue SYSTRAN/faster-whisper#71）。
            # 只要 CUDA 可用（含 device=auto 解析到 GPU）就禁回退防崩溃；
            # 纯 CPU 保留默认回退保证识别质量。
            if _cuda_available():
                transcribe_kwargs["temperature"] = 0.0
            if vad_filter:
                transcribe_kwargs["vad_parameters"] = {
                    "threshold": vad_threshold,
                    "min_speech_duration_ms": vad_min_speech_duration_ms,
                    "min_silence_duration_ms": vad_min_silence_duration_ms,
                    "speech_pad_ms": vad_speech_pad_ms,
                    "max_speech_duration_s": vad_max_speech_duration_s,
                }
            segments, info = model.transcribe(str(wav_path), **transcribe_kwargs)
            total_duration = _positive_duration(getattr(info, "duration", 0.0))
            if progress_callback and total_duration <= 0:
                total_duration = _audio_duration_seconds(wav_path)
            side_entries: list[SubtitleEntry] = []
            for idx, segment in enumerate(segments, start=1):
                entry = SubtitleEntry(
                    index=idx,
                    start=round(segment.start, 3),
                    end=round(segment.end, 3),
                    text=segment.text.strip(),
                )
                side_entries.append(entry)
                if progress_callback and total_duration > 0:
                    local_progress = min(max(entry.end / total_duration, 0.0), 1.0)
                    progress_callback(progress_base + local_progress * progress_span)
            return side_entries
        finally:
            if wav_path is not file_path:
                wav_path.unlink(missing_ok=True)

    # 双声道（ASMR binaural）：语音可能在左耳或右耳交替出现。
    # 平均混音会砍半语音能量导致 VAD 整段丢失（实测 30s 语音块直接消失），
    # 因此拆左右声道分别转写，再按时间窗选语音侧合并。
    if preprocess_audio and _is_stereo(file_path):
        logger.info("ASR: Stereo input detected, transcribing channels separately")
        left_path = _extract_channel(file_path, "FL")
        right_path = _extract_channel(file_path, "FR")
        try:
            available_sides = [
                path for path in (left_path, right_path) if path is not file_path
            ]
            side_results: list[list[SubtitleEntry]] = []
            span = 1.0 / len(available_sides) if available_sides else 1.0
            for side_index, side_path in enumerate(available_sides):
                side_results.append(_run_transcribe(
                    side_path,
                    progress_base=side_index * span,
                    progress_span=span,
                ))
            left_entries = side_results[0] if left_path is not file_path and side_results else []
            right_result_index = 1 if left_path is not file_path else 0
            right_entries = (
                side_results[right_result_index]
                if right_path is not file_path and len(side_results) > right_result_index
                else []
            )
        finally:
            if left_path is not file_path:
                left_path.unlink(missing_ok=True)
            if right_path is not file_path:
                right_path.unlink(missing_ok=True)
        entries = _merge_stereo_sides(left_entries, right_entries)
        if progress_callback:
            progress_callback(1.0)
        logger.info("ASR: %d segments transcribed (stereo merged).", len(entries))
        return entries

    entries = _run_transcribe(working_path)
    if progress_callback:
        progress_callback(1.0)

    logger.info("ASR: %d segments transcribed.", len(entries))
    return entries
