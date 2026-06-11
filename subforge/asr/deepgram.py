from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from subforge.models import SubtitleEntry

_MAX_ENTRY_DURATION = 6.0
_MAX_GAP = 0.8
_TERMINAL_PUNCTUATION = ("。", "！", "？", "!", "?")
_MAX_RETRIES = 3
_TIMEOUT = 120.0

logger = logging.getLogger(__name__)


class DeepgramError(Exception):
    """Raised when Deepgram ASR fails."""


class DeepgramAuthError(DeepgramError):
    """Raised when Deepgram authentication is missing or rejected."""


def _mask_key(key: str) -> str:
    if len(key) < 8:
        return "*" * min(len(key), 4)
    return f"{key[:4]}...{key[-4:]}"


def _build_query_params(
    model: str,
    language: str,
    keyterms: list[str] | None = None,
) -> list[tuple[str, str]]:
    params = [
        ("model", model),
        ("language", language),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("paragraphs", "false"),
    ]
    for keyterm in keyterms or []:
        if keyterm:
            params.append(("keyterm", keyterm))
    return params


def _build_url(
    model: str,
    language: str,
    keyterms: list[str] | None = None,
) -> str:
    params = _build_query_params(model, language, keyterms)
    return f"https://api.deepgram.com/v1/listen?{urlencode(params)}"


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".flac":
        return "audio/flac"
    if suffix == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


def _entries_from_words(words: list[dict[str, Any]]) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    current_words: list[str] = []
    current_start: float | None = None
    current_end: float | None = None

    def flush() -> None:
        nonlocal current_words, current_start, current_end
        if current_words and current_start is not None and current_end is not None:
            text = "".join(current_words).strip()
            if text:
                entries.append(SubtitleEntry(
                    index=len(entries) + 1,
                    start=round(current_start, 3),
                    end=round(current_end, 3),
                    text=text,
                ))
        current_words = []
        current_start = None
        current_end = None

    for word in words:
        text = str(word.get("punctuated_word") or word.get("word") or "").strip()
        if not text:
            continue
        start = float(word["start"])
        end = float(word["end"])

        should_flush = False
        if current_start is not None and current_end is not None:
            if start - current_end > _MAX_GAP:
                should_flush = True
            elif end - current_start > _MAX_ENTRY_DURATION:
                should_flush = True

        if should_flush:
            flush()

        if current_start is None:
            current_start = start
        current_words.append(text)
        current_end = end

        if text.endswith(_TERMINAL_PUNCTUATION):
            flush()

    flush()
    return entries


def _entry_from_transcript(transcript: str, duration: float | None) -> SubtitleEntry:
    text = transcript.strip()
    if not text:
        raise DeepgramError("Deepgram produced no transcript")
    end = duration if duration and duration > 0 else 0.001
    return SubtitleEntry(index=1, start=0.0, end=round(end, 3), text=text)


def _parse_response(data: dict[str, Any]) -> list[SubtitleEntry]:
    try:
        alternative = data["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepgramError("Deepgram response did not include alternatives") from exc

    words = alternative.get("words") or []
    if words:
        entries = _entries_from_words(words)
        if entries:
            return entries

    transcript = str(alternative.get("transcript") or "")
    duration = data.get("metadata", {}).get("duration")
    return [_entry_from_transcript(transcript, float(duration) if duration else None)]


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code in (500, 502, 503, 504)


def transcribe(
    file_path: Path,
    api_key: str,
    model: str = "nova-3",
    language: str = "ja",
    keyterms: list[str] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    client: httpx.Client | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[SubtitleEntry]:
    """Transcribe audio with Deepgram's pre-recorded API."""
    if not api_key:
        raise DeepgramAuthError("Deepgram API key is required")

    close_client = False
    if client is None:
        client = httpx.Client(timeout=_TIMEOUT)
        close_client = True

    url = _build_url(model, language, keyterms)
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": _content_type_for_path(file_path),
    }
    masked_key = _mask_key(api_key)
    logger.info("Deepgram ASR: calling model=%s language=%s key=%s file=%s",
                model, language, masked_key, file_path.name)

    last_exception: Exception | None = None
    try:
        audio = file_path.read_bytes()
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = client.post(url, content=audio, headers=headers)
                if response.status_code in (401, 403):
                    raise DeepgramAuthError(
                        f"Deepgram authentication failed ({response.status_code})"
                    )
                if _is_retryable_status(response.status_code):
                    response.raise_for_status()
                response.raise_for_status()
                entries = _parse_response(response.json())
                if progress_callback:
                    progress_callback(1.0)
                logger.info("Deepgram ASR: %d segments transcribed.", len(entries))
                return entries
            except DeepgramAuthError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_exception = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if status is not None and not _is_retryable_status(status):
                    raise DeepgramError(f"Deepgram non-retryable HTTP error: {status}") from exc
                if attempt >= _MAX_RETRIES:
                    break
                wait = 2 ** (attempt - 1)
                logger.warning("Deepgram ASR: retryable error on attempt %d/%d, waiting %ss",
                               attempt, _MAX_RETRIES, wait)
                sleep_fn(wait)
            except Exception as exc:
                last_exception = exc
                raise DeepgramError(f"Deepgram ASR failed: {exc}") from exc
    finally:
        if close_client:
            client.close()

    raise DeepgramError(
        f"Deepgram ASR failed after {_MAX_RETRIES} retries. Last error: {last_exception}"
    ) from last_exception
