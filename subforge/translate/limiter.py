from __future__ import annotations

from subforge.process_limiter import ProcessFileLimiter


class TranslationRequestLimiter(ProcessFileLimiter):
    """Cross-process file-lock semaphore for outbound LLM requests."""
