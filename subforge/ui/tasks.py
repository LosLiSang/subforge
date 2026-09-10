from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import tempfile
from contextlib import asynccontextmanager
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

@asynccontextmanager
async def _maybe_acquire(semaphore: asyncio.Semaphore | None):
    if semaphore is not None:
        await semaphore.acquire()
    try:
        yield
    finally:
        if semaphore is not None:
            semaphore.release()



def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _profile_snapshot(profile) -> dict:
    """把 ModelProfile 转成不含密钥的快照（密钥经环境变量传给 worker）。"""
    data = asdict(profile)
    data.pop("api_key", None)
    return data


@dataclass(frozen=True)
class ProcessingSnapshot:
    asr_provider: str
    scene: str
    whisper_model: str
    llm_profile_id: str
    # 统一模型 Profile：ASR / 合并（翻译继续用 llm_profile_id，保留旧字段兼容）
    asr_profile_id: str = ""
    merge_profile_id: str = ""
    # 网络 ASR 单个请求的任务级分片大小；旧快照缺失时使用 60 秒。
    asr_chunk_seconds: int = 60


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
    kind: str = "full_process"
    payload: dict | None = None
    result: dict | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


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
        asr_api_key = str(request.pop("asr_api_key", ""))
        merge_api_key = str(request.pop("merge_api_key", ""))
        deepgram_api_key = str(request.pop("deepgram_api_key", ""))
        proxy_url = str(request.pop("proxy_url", ""))
        request_root = Path(tempfile.gettempdir()) / "subforge-worker"
        request_root.mkdir(parents=True, exist_ok=True)
        request_path = request_root / f"{task.task_id}.request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        if llm_api_key:
            env["SUBFORGE_WORKER_LLM_API_KEY"] = llm_api_key
        if asr_api_key:
            env["SUBFORGE_WORKER_ASR_API_KEY"] = asr_api_key
        if merge_api_key:
            env["SUBFORGE_WORKER_MERGE_API_KEY"] = merge_api_key
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
            if os.name == "nt" and code != 0:
                import subprocess
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
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
        if os.name == "nt":
            import subprocess
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
        else:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            pass


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
        segment_runner=None,
        remote_asr_concurrency: int = 2,
    ) -> None:
        if media_concurrency is not None:
            asr_concurrency = media_concurrency
        if asr_concurrency < 1:
            raise ValueError("asr_concurrency must be at least 1")
        if remote_asr_concurrency < 1:
            raise ValueError("remote_asr_concurrency must be at least 1")
        if translate_workers < 1:
            raise ValueError("translate_workers must be at least 1")
        self.library = library
        self.worker = worker
        self._max_workers = media_concurrency if media_concurrency is not None else (asr_concurrency + remote_asr_concurrency)
        self._worker_sem = asyncio.Semaphore(self._max_workers)
        self._local_sem = asyncio.Semaphore(asr_concurrency)
        self._remote_sem = asyncio.Semaphore(remote_asr_concurrency)
        self._local_concurrency = asr_concurrency
        self._remote_concurrency = remote_asr_concurrency
        self._translate_workers = translate_workers
        self._translate_workers_resolver = translate_workers_resolver
        self._translation_prompt_resolver = translation_prompt_resolver
        self._profile_resolver = profile_resolver
        self._deepgram_key_resolver = deepgram_key_resolver
        self._proxy_resolver = proxy_resolver
        self._models_dir_resolver = models_dir_resolver
        self._direct_model_resolver = direct_model_resolver
        self._segment_runner = segment_runner
        self._tasks: dict[str, asyncio.Task] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._asr_active: set[str] = set()
        self._restore_unfinished_tasks()

    def _restore_unfinished_tasks(self) -> None:
        """恢复未完成任务；终态任务（含 awaiting_review）永久留存，不再删除。"""
        with self.library._db_lock, self.library._db:
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
            if task.kind == "full_process":
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
            kind="full_process",
            created_at=_now(),
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
        task.started_at = None
        task.finished_at = None
        self._save(task)
        self.library.update_track_status(task.track_id, "queued")
        self._tasks[task.task_id] = asyncio.create_task(self._run(task))
        return task
    async def retry_segment(self, task: TaskRecord) -> TaskRecord:
        task = self.get_task(task.task_id)
        if not task.payload:
            raise ValueError("片段重处理任务缺少原始参数，无法重试")
        task.status = "queued"
        task.stage = "queue"
        task.progress = 0.0
        task.message = "重新排队（重试）"
        task.result = None
        task.started_at = None
        task.finished_at = None
        self._save(task)
        self._tasks[task.task_id] = asyncio.create_task(self._run(task))
        return task

    def _task_domain(self, task: TaskRecord) -> str:
        if task.kind == "segment_reprocess":
            processor_name = str((task.payload or {}).get("processor", "whisper"))
            return "remote" if processor_name == "gemini" else "local"
        provider = str((task.config_snapshot or {}).get("asr_provider", "local"))
        return "local" if provider == "local" else "remote"

    def _semaphore_for(self, task: TaskRecord) -> asyncio.Semaphore:
        return self._local_sem if self._task_domain(task) == "local" else self._remote_sem


    async def enqueue_segment_reprocess(
        self,
        track_id: str,
        payload: dict,
    ) -> TaskRecord:
        """入队一个片段重处理任务；立即返回，候选生成后进入 awaiting_review。"""
        self.library.get_track(track_id)
        task = TaskRecord(
            task_id=uuid4().hex,
            track_id=track_id,
            status="queued",
            stage="queue",
            kind="segment_reprocess",
            payload=payload,
            created_at=_now(),
        )
        self._save(task)
        self._tasks[task.task_id] = asyncio.create_task(self._run(task))
        return task

    async def _run(self, task: TaskRecord) -> None:
        if task.kind == "segment_reprocess":
            await self._run_segment(task)
            return
        try:
            consecutive_failures = 0
            while True:
                semaphore = self._semaphore_for(task)
                if semaphore is not None:
                    await semaphore.acquire()
                asr_slot_held = semaphore is not None
                self._asr_active.add(task.task_id)
                try:
                    task.status = "running"
                    task.stage = "queue"
                    task.started_at = _now()
                    task.finished_at = None
                    task.message = (
                        f"任务失败，自动重试 ({consecutive_failures}/{_TASK_MAX_CONSECUTIVE_RETRIES})"
                        if consecutive_failures else None
                    )
                    self._save(task)
                    self.library.update_track_status(task.track_id, "processing")
                    request = self._build_request(task)
                    completed_at_start = task.completed
                    async for event in self.worker.events(task, request):
                        if event.get("type") in {
                            "asr_completed", "translation_started",
                            "task_completed", "task_no_speech", "task_failed",
                        }:
                            self._asr_active.discard(task.task_id)
                            if asr_slot_held and semaphore is not None:
                                semaphore.release()
                                asr_slot_held = False
                        self._apply_event(task, event)
                        self._save(task)
                        self._publish(task.task_id, event)
                    if task.status == "running":
                        task.status = "failed"
                        task.stage = "worker"
                        task.message = "Worker ended without a final event"
                        self._save(task)
                        self.library.update_track_status(task.track_id, "failed")
                    if task.status in ("completed", "no_speech"):
                        break
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
                finally:
                    if asr_slot_held and semaphore is not None:
                        semaphore.release()
                    self._asr_active.discard(task.task_id)
        except asyncio.CancelledError:
            if task.status != "cancelled":
                task.status = "interrupted"
                self._save(task)
            raise
        except Exception as exc:
            task.status = "failed"
            task.message = str(exc)
            self._save(task)
            self.library.update_track_status(task.track_id, "failed")
        finally:
            self._tasks.pop(task.task_id, None)

    async def _run_segment(self, task: TaskRecord) -> None:
        """片段重处理：后台跑候选生成，完成转 awaiting_review。"""
        if self._segment_runner is None:
            task.status = "failed"
            task.stage = "failed"
            task.message = "片段重处理运行器未配置"
            self._save(task)
            return
        try:
            semaphore = self._semaphore_for(task)
            async with _maybe_acquire(semaphore):
                self._asr_active.add(task.task_id)
                task.status = "running"
                task.stage = "asr"
                task.started_at = _now()
                task.message = None
                self._save(task)

                def report(
                    stage: str,
                    progress: float | None,
                    message: str | None = None,
                    completed: int | None = None,
                    total: int | None = None,
                ) -> None:
                    task.stage = stage
                    if progress is not None:
                        task.progress = max(0.0, min(1.0, progress))
                    if message is not None:
                        task.message = message
                    if completed is not None:
                        task.completed = completed
                    if total is not None:
                        task.total = total
                    self._save(task)
                    self._publish(task.task_id, {
                        "type": "segment_progress",
                        "stage": stage,
                        "progress": task.progress,
                        "completed": task.completed,
                        "total": task.total,
                        "message": message,
                    })

                result = await self._segment_runner(task.track_id, task.payload or {}, report)
                task.result = result
                task.status = "awaiting_review"
                task.stage = "review"
                task.progress = 1.0
                if task.total is None:
                    task.completed = 1
                    task.total = 1
                else:
                    task.completed = task.total
                task.message = "候选已就绪，等待评审"
                self._save(task)
                self._publish(task.task_id, {
                    "type": "segment_candidate_ready",
                    "stage": "review",
                    "status": "awaiting_review",
                    "progress": 1.0,
                    "completed": task.completed,
                    "total": task.total,
                    "message": task.message,
                })
        except asyncio.CancelledError:
            if task.status != "cancelled":
                task.status = "interrupted"
                self._save(task)
            raise
        except Exception as exc:
            task.status = "failed"
            task.stage = "segment"
            task.message = str(exc)
            self._save(task)
        finally:
            self._asr_active.discard(task.task_id)
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
            "asr_chunk_seconds": int(snapshot.get("asr_chunk_seconds", 60)),
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
            "remote_asr_global_workers": self._remote_concurrency,
            "remote_asr_limiter_dir": str(
                (self.library.root / ".subforge" / "remote-asr-slots").resolve()
            ),
        }
        if snapshot.get("scene") == "asmr":
            overrides.update(ASMR_PRESET)
        deepgram_api_key = self._deepgram_key_resolver() if self._deepgram_key_resolver else ""
        proxy_url = self._proxy_resolver() if self._proxy_resolver else ""
        asr_profile = (
            self._profile_resolver(snapshot.get("asr_profile_id"))
            if self._profile_resolver and snapshot.get("asr_profile_id") else None
        )
        merge_profile = (
            self._profile_resolver(snapshot.get("merge_profile_id"))
            if self._profile_resolver and snapshot.get("merge_profile_id") else None
        )
        if asr_profile is not None:
            overrides["asr_profile"] = _profile_snapshot(asr_profile)
        if merge_profile is not None:
            overrides["merge_profile"] = _profile_snapshot(merge_profile)
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
            "asr_api_key": asr_profile.api_key if asr_profile else "",
            "merge_api_key": merge_profile.api_key if merge_profile else "",
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

    async def mark_reviewed(self, task_id: str, *, status: str, message: str | None = None) -> TaskRecord:
        """候选评审结束后更新任务终态（completed / discarded）。"""
        task = self.get_task(task_id)
        task.status = status
        if status == "completed":
            task.stage = "complete"
        elif status == "discarded":
            task.stage = "discarded"
        else:
            task.stage = status
        task.progress = 1.0
        if task.total is not None and task.completed is None:
            task.completed = task.total
        elif task.total is None:
            task.completed = 1
            task.total = 1
        task.finished_at = _now()
        if message is not None:
            task.message = message
        self._save(task)
        self._publish(task.task_id, {
            "type": f"segment_{status}",
            "stage": task.stage,
            "status": task.status,
            "progress": 1.0,
            "completed": task.completed,
            "total": task.total,
            "message": message,
        })
        return task

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
        if task.kind == "full_process":
            self.library.update_track_status(task.track_id, "waiting")
        self._publish(task_id, {"type": "task_cancelled", "stage": "cancelled"})

    def summary(self) -> dict:
        local_running = remote_running = queued = 0
        for task_id in list(self._asr_active):
            try:
                task = self.get_task(task_id)
            except KeyError:
                continue
            if self._task_domain(task) == "local":
                local_running += 1
            else:
                remote_running += 1
        for task_id in list(self._tasks):
            try:
                task = self.get_task(task_id)
            except KeyError:
                continue
            if task.status == "queued":
                queued += 1
        return {
            "local_running": local_running,
            "local_capacity": self._local_concurrency,
            "remote_running": remote_running,
            "remote_capacity": self._remote_concurrency,
            "queued": queued,
        }

    _DELETABLE_STATUSES = {"completed", "no_speech", "failed", "cancelled", "discarded"}

    def delete_task(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task.status not in self._DELETABLE_STATUSES:
            raise ValueError(f"任务状态为 {task.status}，不能删除（终态任务才可删除）")
        if task.task_id in self._tasks:
            raise ValueError("任务仍在运行，不能删除")
        with self.library._db_lock, self.library._db:
            self.library._db.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))

    def get_task(self, task_id: str) -> TaskRecord:
        with self.library._db_lock:
            row = self.library._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._row_to_task(row)

    @staticmethod
    def _row_to_task(row) -> TaskRecord:
        keys = row.keys()
        task = TaskRecord(
            task_id=row["task_id"], track_id=row["track_id"], status=row["status"],
            stage=row["stage"], progress=row["progress"], completed=row["completed"],
            total=row["total"], message=row["message"],
            config_snapshot=json.loads(row["config_snapshot"]) if row["config_snapshot"] else None,
            kind=(row["kind"] if "kind" in keys and row["kind"] else "full_process"),
            payload=json.loads(row["payload_json"]) if "payload_json" in keys and row["payload_json"] else None,
            result=json.loads(row["result_json"]) if "result_json" in keys and row["result_json"] else None,
            created_at=(row["created_at"] if "created_at" in keys else None),
            started_at=(row["started_at"] if "started_at" in keys else None),
            finished_at=(row["finished_at"] if "finished_at" in keys else None),
        )
        if task.kind == "segment_reprocess":
            if task.status == "completed" and task.stage in ("review", "segment"):
                task.stage = "complete"
            elif task.status == "discarded" and task.stage in ("review", "segment"):
                task.stage = "discarded"
            if task.total is None and task.status in ("completed", "awaiting_review", "discarded"):
                parts = 1
                try:
                    payload = task.payload or {}
                    start_t = float(payload.get("start_time", 0))
                    end_t = float(payload.get("end_time", 0))
                    if end_t > start_t:
                        chunk_sec = float(payload.get("asr_chunk_seconds") or 60)
                        parts = max(1, math.ceil((end_t - start_t) / chunk_sec))
                except Exception:
                    parts = 1
                task.total = parts
                task.completed = parts
        return task

    def list_tasks(self, limit: int | None = None) -> list[TaskRecord]:
        with self.library._db_lock:
            if limit is None:
                rows = self.library._db.execute(
                    "SELECT * FROM tasks ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = self.library._db.execute(
                    "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (int(limit),)
                ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def latest_for_track(self, track_id: str) -> TaskRecord | None:
        with self.library._db_lock:
            row = self.library._db.execute(
                "SELECT * FROM tasks WHERE track_id=? ORDER BY updated_at DESC LIMIT 1", (track_id,)
            ).fetchone()
        return self._row_to_task(row) if row else None

    def _save(self, task: TaskRecord) -> None:
        if task.status in {"completed", "no_speech", "failed", "cancelled", "discarded", "awaiting_review"} and task.finished_at is None:
            task.finished_at = _now()
        with self.library._db_lock, self.library._db:
            self.library._db.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_id,track_id,status,stage,progress,completed,total,message,config_snapshot,updated_at,
                    kind,payload_json,result_json,created_at,started_at,finished_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task.task_id, task.track_id, task.status, task.stage, task.progress,
                    task.completed, task.total, task.message,
                    json.dumps(task.config_snapshot) if task.config_snapshot else None, _now(),
                    task.kind,
                    json.dumps(task.payload) if task.payload else None,
                    json.dumps(task.result) if task.result else None,
                    task.created_at, task.started_at, task.finished_at,
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
