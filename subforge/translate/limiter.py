from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import BinaryIO, AsyncIterator


class TranslationRequestLimiter:
    """Cross-process file-lock semaphore for outbound LLM requests.

    Every media Worker is a separate Python process, so an asyncio.Semaphore in
    one Worker cannot enforce a global provider limit. Each slot is represented
    by a one-byte lock file; the OS releases the lock automatically if a Worker
    exits or crashes.
    """

    def __init__(self, directory: Path | None, limit: int) -> None:
        self.directory = Path(directory) if directory else None
        self.limit = max(0, int(limit))
        if self.directory is not None and self.limit:
            self.directory.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if self.directory is None or self.limit < 1:
            yield
            return

        handle: BinaryIO | None = None
        while handle is None:
            handle = await asyncio.to_thread(self._try_acquire)
            if handle is None:
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            await asyncio.to_thread(self._release, handle)

    def _try_acquire(self) -> BinaryIO | None:
        assert self.directory is not None
        for index in range(self.limit):
            path = self.directory / f"slot-{index}.lock"
            handle = path.open("a+b")
            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return handle
            except (OSError, BlockingIOError):
                handle.close()
        return None

    @staticmethod
    def _release(handle: BinaryIO) -> None:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
