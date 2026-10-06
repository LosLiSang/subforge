"""并发模型：准入（Admission）与资源池（Resource Pool）分离。

- 准入：TaskManager 决定哪些「大任务」现在可以进入 ASR 阶段（进程内 FIFO）。
- 资源池：跨进程文件锁，只在真正使用稀缺资源的那一行代码处持有。

    设置项                         限制对象
    local_asr            (L)      同时加载的本地 Whisper 模型数（准入 + 跨进程池）
    remote_asr_tasks     (A)      同时处于网络 ASR 阶段的大任务数（准入）
    remote_asr_requests  (R)      全局在途的网络 ASR HTTP 请求数（跨进程池）
    llm_requests         (T)      全局在途的 LLM HTTP 请求数（跨进程池）
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Callable

LOCAL = "local"
REMOTE = "remote"

# 资源池目录（相对 <Library>/.subforge/）
LOCAL_ASR_POOL_DIR = "local-asr-slots"
REMOTE_ASR_POOL_DIR = "remote-asr-slots"
LLM_POOL_DIR = "translation-slots"

# 整轨任务收到这些事件即离开 ASR 阶段，归还准入槽（翻译阶段不占 ASR 准入）。
LEAVES_ASR_PHASE_EVENTS = frozenset({
    "asr_completed", "translation_started",
    "task_completed", "task_no_speech", "task_failed",
})


@dataclass(frozen=True)
class ConcurrencyPolicy:
    local_asr: int = 1
    remote_asr_tasks: int = 20
    remote_asr_requests: int = 20
    llm_requests: int = 20

    def __post_init__(self) -> None:
        for name in ("local_asr", "remote_asr_tasks", "remote_asr_requests", "llm_requests"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be at least 1")

    def admission_limit(self, domain: str) -> int:
        if domain == LOCAL:
            return self.local_asr
        if domain == REMOTE:
            return self.remote_asr_tasks
        raise ValueError(f"unknown concurrency domain: {domain}")


def task_domain(kind: str, asr_provider: str | None = None, processor: str | None = None) -> str:
    """纯函数：任务归属的并发域。"""
    if kind == "segment_reprocess":
        return REMOTE if (processor or "whisper") == "gemini" else LOCAL
    return LOCAL if (asr_provider or "local") == "local" else REMOTE


def chunk_fanout(chunk_count: int, remote_asr_requests: int) -> int:
    """单任务内的分片 worker 数：不超过分片数，也不超过全局请求池（多开只会空等）。"""
    return max(1, min(int(chunk_count), int(remote_asr_requests)))


class AdmissionGate:
    """严格 FIFO 的准入闸；容量每次实时读取，调大后调用 wake() 立即生效。"""

    def __init__(self, limit_fn: Callable[[], int]) -> None:
        self._limit_fn = limit_fn
        self._active = 0
        self._waiters: deque[asyncio.Future] = deque()

    @property
    def active(self) -> int:
        return self._active

    @property
    def waiting(self) -> int:
        return sum(1 for fut in self._waiters if not fut.done())

    def limit(self) -> int:
        return max(1, int(self._limit_fn()))

    async def acquire(self) -> None:
        if not self.waiting and self._active < self.limit():
            self._active += 1
            return
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release()  # 已被授予但随即取消：归还
            else:
                try:
                    self._waiters.remove(fut)
                except ValueError:
                    pass
            raise

    def release(self) -> None:
        self._active = max(0, self._active - 1)
        self.wake()

    def wake(self) -> None:
        limit = self.limit()
        while self._waiters and self._active < limit:
            fut = self._waiters.popleft()
            if fut.done():
                continue
            self._active += 1
            fut.set_result(None)
