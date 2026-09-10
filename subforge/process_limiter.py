from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Iterator


class ProcessFileLimiter:
    """Cross-process file-lock semaphore for concurrent external requests.

    Each worker or process acquires a slot represented by a locked file (slot-0.lock, etc.).
    If a process exits or crashes unexpectedly, the OS automatically releases the file lock.
    """

    def __init__(self, directory: Path | str | None, limit: int) -> None:
        self.directory = Path(directory) if directory else None
        self.limit = max(0, int(limit))
        if self.directory is not None and self.limit > 0:
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

    @contextmanager
    def sync_slot(self) -> Iterator[None]:
        if self.directory is None or self.limit < 1:
            yield
            return

        handle: BinaryIO | None = None
        while handle is None:
            handle = self._try_acquire()
            if handle is None:
                time.sleep(0.05)
        try:
            yield
        finally:
            self._release(handle)

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
