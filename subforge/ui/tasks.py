from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator, Protocol
from uuid import uuid4

from subforge.library import LibraryStore
from subforge.presets import ASMR_PRESET

logger = logging.getLogger(__name__)

# 任务级自动重试：连续失败达此次数才彻底结束（任一次成功即重置/结束）。
_TASK_MAX_CONSECUTIVE_RETRIES = 3


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ProcessingSnapshot:
    asr_provider: str
    scene: str
    whisper_model: str
    llm_profile_id: str


@dataclass
class TaskRecord:
    task_id: str
    track_id: str
    status: str
    stage: str | None = None
    progress: float = 0.0
    completed: int | None = None
    total: int | None = None
    message: str | None = None
    config_snapshot: dict | None = None


class WorkerAdapter(Protocol):
    async def events(self, task: TaskRecord, request: dict) -> AsyncIterator[dict]: ...
    async def cancel(self, task_id: str) -> None: ...


class FakeWorkerAdapter:
    def __init__(self, events: list[dict], wait_forever: bool = False) -> None:
        self._events = events
        self._wait_forever = wait_forever
        self._cancelled = asyncio.Event()

    async def events(self, task: TaskRecord, request: dict) -> AsyncIterator[dict]:
        for event in self._events:
            await asyncio.sleep(0)
            yield {"job_id": task.task_id, **event}
        if self._wait_forever:
            await self._cancelled.wait()

    async def cancel(self, task_id: str) -> None:
        self._cancelled.set()


class SubprocessWorkerAdapter:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._requests: dict[str, Path] = {}
        self._stderr: dict[str, asyncio.subprocess.Process] = {}

    def _stderr_log_path(self, library_root: Path | str, task_id: str) -> Path:
        """Worker stderr 落盘位置：<library_root>/.subforge/logs/worker-<task_id>.log"""
        safe_id = "".join(c for c in task_id if c.isalnum() or c in "-_")[:64]
        return Path(library_root) / ".subforge" / "logs" / f"worker-{safe_id}.log"

    async def events(self, task: TaskRecord, request: dict) -> AsyncIterator[dict]:
        request = dict(request)
        llm_api_key = str(request.pop("llm_api_key", ""))
        deepgram_api_key = str(request.pop("deepgram_api_key", ""))
        proxy_url = str(request.pop("proxy_url", ""))
        request_root = Path(tempfile.gettempdir()) / "subforge-worker"
        request_root.mkdir(parents=True, exist_ok=True)
        request_path = request_root / f"{task.task_id}.request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        if llm_api_key:
            env["SUBFORGE_WORKER_LLM_API_KEY"] = llm_api_key
        if deepgram_api_key:
            env["SUBFORGE_WORKER_DEEPGRAM_API_KEY"] = deepgram_api_key
        if proxy_url:
            env["HTTP_PROXY"] = proxy_url
            env["HTTPS_PROXY"] = proxy_url
            env["ALL_PROXY"] = proxy_url
        self._requests[task.task_id] = request_path
        # stderr 落盘：原生崩溃（如 0xC0000409 栈溢出）不走 Python 异常，
        # 只有 stderr 能留下现场。写到库目录 .subforge/logs/，崩溃后仍保留。
        library_root = str(request.get("library_root") or ".")
        stderr_path = self._stderr_log_path(library_root, task.task_id)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_file = open(stderr_path, "wb")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "subforge.worker",
            "--request",
            str(request_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_file,
            env=env,
        )
        self._processes[task.task_id] = process
        assert process.stdout is not None
        try:
            while line := await process.stdout.readline():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Ignoring malformed worker event")
            code = await process.wait()
            stderr_file.close()
            if code and process.returncode not in (-15, 1):
                crash_hint = ""
                if code >= 0x80000000:
                    crash_hint = (f" (0x{code & 0xFFFFFFFF:08X})；崩溃现场已保存到 {stderr_path}")
                yield {
                    "type": "task_failed",
                    "stage": "worker",
                    "error_type": "WorkerExit",
                    "message": f"Worker exited with code {code}{crash_hint}",
                }
        finally:
            self._processes.pop(task.task_id, None)
            self._requests.pop(task.task_id, None)
            if not stderr_file.closed:
                stderr_file.close()
            request_path.unlink(missing_ok=True)

    async def cancel(self, task_id: str) -> None:
        process = self._processes.get(task_id)
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()


class TaskManager:
    def __init__(
        self,
        library: LibraryStore,
        worker: WorkerAdapter,
        asr_concurrency: int = 1,
        profile_resolver=None,
        deepgram_key_resolver=None,
        proxy_resolver=None,
        models_dir_resolver=None,
        direct_model_resolver=None,
        translate_workers: int = 8,
        translate_workers_resolver=None,
        translation_prompt_resolver=None,
        media_concurrency: int | None = None,
    ) -> None:
        if media_concurrency is not None:
            asr_concurrency = media_concurrency
        if asr_concurrency < 1:
            raise ValueError("asr_concurrency must be at least 1")
        if translate_workers < 1:
            raise ValueError("translate_workers must be at least 1")
        self.library = library
        self.worker = worker
        self._semaphore = asyncio.Semaphore(asr_concurrency)
        self._translate_workers = translate_workers
        self._translate_workers_resolver = translate_workers_resolver
        self._translation_prompt_resolver = translation_prompt_resolver
        self._profile_resolver = profile_resolver
        self._deepgram_key_resolver = deepgram_key_resolver
        self._proxy_resolver = proxy_resolver
        self._models_dir_resolver = models_dir_resolver
        self._direct_model_resolver = direct_model_resolver
        self._tasks: dict[str, asyncio.Task] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._restore_unfinished_tasks()

    def _restore_unfinished_tasks(self) -> None:
        """Resume unfinished tasks and discard terminal history from older sessions."""
        with self.library._db_lock, self.library._db:
            self.library._db.execute(
                "DELETE FROM tasks WHERE status IN ('completed','no_speech','failed','cancelled')"
            )
            rows = self.library._db.execute(
                "SELECT task_id,track_id FROM tasks WHERE status IN ('queued','running','interrupted') ORDER BY updated_at"
            ).fetchall()
        active_track_ids: set[str] = set()
        for row in rows:
            task = self.get_task(row["task_id"])
            task.status = "queued"
            task.stage = "queue"
            task.message = "应用重启后恢复任务"
            self._save(task)
            self.library.update_track_status(task.track_id, "queued")
            self._tasks[task.task_id] = asyncio.create_task(self._run(task))
            active_track_ids.add(task.track_id)
        for item in self.library.list_items():
            for track in item.tracks:
                if track.status in {"queued", "processing"} and track.track_id not in active_track_ids:
                    self.library.update_track_status(track.track_id, "interrupted")

    async def enqueue(
        self,
        track_id: str,
        snapshot: ProcessingSnapshot,
        mode: str = "continue",
    ) -> TaskRecord:
        self.library.get_track(track_id)
        self.library.prepare_processing(track_id, mode)
        task = TaskRecord(
            task_id=uuid4().hex,
            track_id=track_id,
            status="queued",
            stage="queue",
            config_snapshot=asdict(snapshot),
        )
        self._save(task)
        self.library.update_track_status(track_id, "queued")
        self._tasks[task.task_id] = asyncio.create_task(self._run(task))
        return task

    async def retry(self, task: TaskRecord) -> TaskRecord:
        """重试失败任务：复用同一条任务记录（同一 task_id），从断点继续。

        这样在任务中心只有一行，点击重试后该行由 failed 转回 running，
        不会另起一行新任务。
        """
        self.library.prepare_processing(task.track_id, "continue")
        task = self.get_task(task.task_id)  # 重新读取，确保拿到最新 completed 等字段
        task.status = "queued"
        task.stage = "queue"
        task.message = "重新排队（重试）"
        self._save(task)
        self.library.update_track_status(task.track_id, "queued")
        self._tasks[task.task_id] = asyncio.create_task(self._run(task))
        return task

    async def _run(self, task: TaskRecord) -> None:
        try:
            async with self._semaphore:
                consecutive_failures = 0
                while True:
                    task.status = "running"
                    task.stage = "queue"
                    task.message = (
                        f"任务失败，自动重试 ({consecutive_failures}/{_TASK_MAX_CONSECUTIVE_RETRIES})"
                        if consecutive_failures else None
                    )
                    self._save(task)
                    self.library.update_track_status(task.track_id, "processing")
                    request = self._build_request(task)
                    completed_at_start = task.completed
                    async for event in self.worker.events(task, request):
                        self._apply_event(task, event)
                        self._save(task)
                        self._publish(task.task_id, event)
                    if task.status == "running":
                        task.status = "failed"
                        task.stage = "worker"
                        task.message = "Worker ended without a final event"
                        self._save(task)
                        self.library.update_track_status(task.track_id, "failed")
                    # 成功（或检测到无语音）即结束；失败则累计连续失败次数。
                    if task.status in ("completed", "no_speech"):
                        break
                    # 本轮取得进展（翻译完成批次前进）视为“成功”，重置连续失败计数；
                    # 只有连续无进展的失败累计到上限才彻底结束。
                    if task.completed is not None and task.completed != completed_at_start:
                        consecutive_failures = 0
                    consecutive_failures += 1
                    if consecutive_failures >= _TASK_MAX_CONSECUTIVE_RETRIES:
                        break
                    self._publish(task.task_id, {
                        "type": "task_retrying",
                        "stage": "retry",
                        "message": (
                            f"任务失败，自动重试 ({consecutive_failures}/{_TASK_MAX_CONSECUTIVE_RETRIES})"
                        ),
                    })
        except asyncio.CancelledError:
            if task.status != "cancelled":
                task.status = "interrupted"
                self._save(task)
            raise
        except Exception as exc:
            task.status = "failed"
            task.stage = "worker"
            task.message = str(exc)
            self._save(task)
            self.library.update_track_status(task.track_id, "failed")
        finally:
            # 终态后从 _tasks 移除：asyncio.Task 协程帧、config_snapshot、
            # 失败异常及其 traceback 若滞留字典会随任务数无上界累积（内存泄露）。
            self._tasks.pop(task.task_id, None)

    def _build_request(self, task: TaskRecord) -> dict:
        item, track = self.library.get_track(task.track_id)
        snapshot = task.config_snapshot or {}
        resume_dir = self.library.track_resume_dir(task.track_id)
        output_dir = self.library.root / item.directory / "subtitles"
        output_dir.mkdir(parents=True, exist_ok=True)
        profile = self._profile_resolver(snapshot.get("llm_profile_id")) if self._profile_resolver else None
        model_name = snapshot.get("whisper_model", "medium")
        model_path = self._direct_model_resolver(model_name) if self._direct_model_resolver else None
        models_dir = self._models_dir_resolver() if self._models_dir_resolver else None
        translate_workers = (
            self._translate_workers_resolver()
            if self._translate_workers_resolver is not None
            else self._translate_workers
        )
        if not isinstance(translate_workers, int) or translate_workers < 1:
            raise ValueError("translate_workers must be at least 1")
        translation_prompt = (
            self._translation_prompt_resolver()
            if self._translation_prompt_resolver is not None
            else ""
        )
        if not isinstance(translation_prompt, str):
            raise ValueError("translation_prompt must be a string")
        overrides = {
            "asr_provider": snapshot.get("asr_provider", "local"),
            "model": model_name,
            "device": "auto",
            "compute_type": "auto",
            "output_dir": str(output_dir),
            "models_dir": str(Path(models_dir).resolve()) if models_dir else None,
            "jobs_dir": str(resume_dir),
            "llm_base_url": profile.base_url if profile else None,
            "llm_model": profile.model if profile else None,
            "llm_proxy_url": profile.proxy_url if profile else "",
            "llm_verify_tls": profile.verify_tls if profile else True,
            "llm_ca_bundle": profile.ca_bundle if profile else "",
            "translate_workers": translate_workers,
            "translation_global_workers": translate_workers,
            "translation_prompt": translation_prompt,
            "translation_limiter_dir": str(
                (self.library.root / ".subforge" / "translation-slots").resolve()
            ),
        }
        if snapshot.get("scene") == "asmr":
            overrides.update(ASMR_PRESET)
        deepgram_api_key = self._deepgram_key_resolver() if self._deepgram_key_resolver else ""
        proxy_url = self._proxy_resolver() if self._proxy_resolver else ""
        return {
            "job_id": task.task_id,
            "track_id": task.track_id,
            "library_root": str(self.library.root),
            "media_path": str(self.library.track_media_path(task.track_id)),
            "source_lang": track.source_language,
            "target_lang": track.target_language,
            "model": snapshot.get("whisper_model", "medium"),
            "resume_dir": str(resume_dir),
            "config_overrides": overrides,
            "llm_api_key": profile.api_key if profile else "",
            "deepgram_api_key": deepgram_api_key,
            "proxy_url": proxy_url,
            "model_path": str(Path(model_path).resolve()) if model_path else "",
        }

    def _apply_event(self, task: TaskRecord, event: dict) -> None:
        event_type = event.get("type")
        if event.get("stage") is not None:
            task.stage = event["stage"]
        if event.get("progress") is not None:
            task.progress = float(event["progress"])
        if event.get("completed") is not None:
            task.completed = int(event["completed"])
        if event.get("total") is not None:
            task.total = int(event["total"])
        if event.get("message") is not None:
            task.message = event["message"]
        if event_type == "task_completed":
            task.status = "completed"
            self.library.update_track_status(task.track_id, "playable")
        elif event_type == "task_no_speech":
            task.status = "no_speech"
            self.library.update_track_status(task.track_id, "no_speech")
        elif event_type == "task_failed":
            task.status = "failed"
            self.library.update_track_status(task.track_id, "failed")

    async def cancel(self, task_id: str) -> None:
        task = self.get_task(task_id)
        await self.worker.cancel(task_id)
        running = self._tasks.get(task_id)
        if running:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        task.status = "cancelled"
        task.stage = "cancelled"
        self._save(task)
        self.library.update_track_status(task.track_id, "waiting")
        self._publish(task_id, {"type": "task_cancelled", "stage": "cancelled"})

    def get_task(self, task_id: str) -> TaskRecord:
        with self.library._db_lock:
            row = self.library._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return TaskRecord(
            task_id=row["task_id"], track_id=row["track_id"], status=row["status"],
            stage=row["stage"], progress=row["progress"], completed=row["completed"],
            total=row["total"], message=row["message"],
            config_snapshot=json.loads(row["config_snapshot"]) if row["config_snapshot"] else None,
        )

    def list_tasks(self) -> list[TaskRecord]:
        with self.library._db_lock:
            rows = self.library._db.execute(
                "SELECT task_id FROM tasks ORDER BY updated_at DESC"
            ).fetchall()
        return [self.get_task(row["task_id"]) for row in rows]

    def latest_for_track(self, track_id: str) -> TaskRecord | None:
        with self.library._db_lock:
            row = self.library._db.execute(
                "SELECT task_id FROM tasks WHERE track_id=? ORDER BY updated_at DESC LIMIT 1", (track_id,)
            ).fetchone()
        return self.get_task(row["task_id"]) if row else None

    def _save(self, task: TaskRecord) -> None:
        with self.library._db_lock, self.library._db:
            self.library._db.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_id,track_id,status,stage,progress,completed,total,message,config_snapshot,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    task.task_id, task.track_id, task.status, task.stage, task.progress,
                    task.completed, task.total, task.message,
                    json.dumps(task.config_snapshot) if task.config_snapshot else None, _now(),
                ),
            )

    async def subscribe(self, task_id: str) -> AsyncIterator[dict]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(task_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.get(task_id, set()).discard(queue)

    def _publish(self, task_id: str, event: dict) -> None:
        for queue in self._subscribers.get(task_id, set()):
            queue.put_nowait(event)

    async def close(self) -> None:
        for task_id, task in list(self._tasks.items()):
            if not task.done():
                await self.worker.cancel(task_id)
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
