from __future__ import annotations

from subforge.process_limiter import ProcessFileLimiter


class RemoteAsrRequestLimiter(ProcessFileLimiter):
    """Cross-process semaphore for individual remote ASR requests."""
