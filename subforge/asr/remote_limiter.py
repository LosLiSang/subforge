from __future__ import annotations

from subforge.process_limiter import ProcessFileLimiter


class RemoteAsrRequestLimiter(ProcessFileLimiter):
    """Cross-process semaphore for individual remote ASR requests."""


class LocalAsrModelLimiter(ProcessFileLimiter):
    """Cross-process semaphore: one slot = one loaded local Whisper model."""
