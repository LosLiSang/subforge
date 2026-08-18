from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
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

    return out_path


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

    try:
        logger.info("ASR: Transcribing %s...", file_path.name)
        transcribe_kwargs: dict = {
            "language": language,
            "beam_size": 5,
            "vad_filter": vad_filter,
            "condition_on_previous_text": condition_on_previous_text,
            "no_speech_threshold": no_speech_threshold,
        }
        # Windows GPU 下 ctranslate2 的温度回退会在模型释放时触发 __fastfail
        # （0xC0000409 / 退出码 3221226505，上游 issue SYSTRAN/faster-whisper#71）。
        # GPU 禁回退防崩溃；CPU 保留默认回退保证识别质量。
        if device == "cuda":
            transcribe_kwargs["temperature"] = 0.0
        if vad_filter:
            transcribe_kwargs["vad_parameters"] = {
                "threshold": vad_threshold,
                "min_speech_duration_ms": vad_min_speech_duration_ms,
                "min_silence_duration_ms": vad_min_silence_duration_ms,
                "speech_pad_ms": vad_speech_pad_ms,
                "max_speech_duration_s": vad_max_speech_duration_s,
            }
        segments, info = model.transcribe(str(working_path), **transcribe_kwargs)
    finally:
        if working_path is not file_path:
            working_path.unlink(missing_ok=True)

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
