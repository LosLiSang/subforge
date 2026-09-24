import asyncio

import pytest

from subforge.events import EventType
from subforge.library import ImportRequest, ItemKind, LibraryStore
from subforge.ui.profiles import LlmProfile
from subforge.ui.tasks import FakeWorkerAdapter, ProcessingSnapshot, TaskManager


async def _wait_until(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class _RetryWorker(FakeWorkerAdapter):
    """每次调用 events() 依次消耗 outcomes；最后一份循环复用。"""

    def __init__(self, outcomes):
        self._outcomes = outcomes
        self._calls = 0

    async def events(self, task, request):
        self._calls += 1
        idx = min(self._calls - 1, len(self._outcomes) - 1)
        for event in self._outcomes[idx]:
            await asyncio.sleep(0)
            yield {"job_id": task.task_id, **event}

    async def cancel(self, task_id):
        pass


async def _auto_retry_manager(tmp_path, outcomes, title="W", rj="RJ00000109"):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title=title, rj_code=rj
    ))
    worker = _RetryWorker(outcomes)
    manager = TaskManager(store, worker)
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="profile"
    ))
    return store, manager, task, worker


async def test_task_auto_retries_then_completes_after_transient_failures(tmp_path):
    """任务失败后自动重试；连续失败 < 3 后成功则完成。"""
    store, manager, task, worker = await _auto_retry_manager(tmp_path, [
        [{"type": "task_failed", "stage": "translation", "message": "HTTP 429"}],
        [{"type": "task_failed", "stage": "translation", "message": "HTTP 502"}],
        [{"type": "task_completed", "stage": "complete"}],
    ])
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")
    assert worker._calls == 3  # 失败 2 次 + 成功 1 次
    assert store.get_track(task.track_id)[1].status == "playable"
    await manager.close()


async def test_task_gives_up_after_three_consecutive_failures(tmp_path):
    """连续失败 3 次后任务彻底失败，不再自动重试。"""
    store, manager, task, worker = await _auto_retry_manager(tmp_path, [
        [{"type": "task_failed", "stage": "translation", "message": "HTTP 429"}],
        [{"type": "task_failed", "stage": "translation", "message": "HTTP 502"}],
        [{"type": "task_failed", "stage": "translation", "message": "HTTP 503"}],
    ])
    await _wait_until(lambda: manager.get_task(task.task_id).status == "failed")
    assert worker._calls == 3
    assert store.get_track(task.track_id)[1].status == "failed"
    await manager.close()


async def test_task_completes_on_first_attempt_without_retry(tmp_path):
    """首次即成功的任务不做多余重试。"""
    store, manager, task, worker = await _auto_retry_manager(tmp_path, [
        [{"type": "task_completed", "stage": "complete"}],
    ])
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")
    assert worker._calls == 1
    await manager.close()


async def test_task_progress_resets_consecutive_failure_counter(tmp_path):
    """失败但取得进展（批次前进）会重置连续失败计数，不会因 3 次有进展失败而放弃。"""
    store, manager, task, worker = await _auto_retry_manager(tmp_path, [
        [{"type": "task_failed", "stage": "translation", "completed": 0, "total": 5}],
        [{"type": "task_failed", "stage": "translation", "completed": 2, "total": 5}],
        [{"type": "task_failed", "stage": "translation", "completed": 4, "total": 5}],
        [{"type": "task_completed", "stage": "complete", "completed": 5, "total": 5}],
    ])
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")
    # 3 次有进展失败（各自重置计数）后仍未放弃，第 4 次完成
    assert worker._calls == 4
    assert store.get_track(task.track_id)[1].status == "playable"
    await manager.close()


async def test_asr_capacity_is_released_before_translation_finishes(tmp_path):
    """ASR 槽在 ASR 完成后释放，翻译期间可让下一个任务进入 ASR。"""
    store = LibraryStore.initialize(tmp_path / "Library")
    tracks = []
    for index in range(2):
        audio = tmp_path / f"audio-{index}.m4a"
        audio.write_bytes(b"audio")
        imported = store.import_audio(ImportRequest(
            source=audio, kind=ItemKind.RJ_WORK, title=f"Work {index}",
            rj_code=f"RJ00000{120 + index}",
        ))
        tracks.append(imported.track_id)

    first_translation_gate = asyncio.Event()
    second_asr_started = asyncio.Event()

    class _StageWorker:
        def __init__(self):
            self.calls = 0

        async def events(self, task, request):
            self.calls += 1
            is_first = self.calls == 1
            yield {"type": "asr_started", "stage": "asr"}
            yield {"type": "asr_completed", "stage": "asr", "progress": 1.0}
            if is_first:
                await first_translation_gate.wait()
            else:
                second_asr_started.set()
            yield {"type": "task_completed", "stage": "complete"}

        async def cancel(self, task_id):
            first_translation_gate.set()

    worker = _StageWorker()
    manager = TaskManager(store, worker, asr_concurrency=1, remote_asr_concurrency=1)
    snapshot = ProcessingSnapshot(
        asr_provider="deepgram", scene="normal", whisper_model="medium", llm_profile_id="p"
    )
    first = await manager.enqueue(tracks[0], snapshot)
    await _wait_until(lambda: manager.get_task(first.task_id).stage == "asr")
    second = await manager.enqueue(tracks[1], snapshot)
    await asyncio.wait_for(second_asr_started.wait(), timeout=2)

    first_translation_gate.set()
    await _wait_until(lambda: manager.get_task(first.task_id).status == "completed")
    await _wait_until(lambda: manager.get_task(second.task_id).status == "completed")
    await manager.close()


async def test_failure_event_does_not_erase_known_translation_totals(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000106"
    ))
    worker = FakeWorkerAdapter([
        {"type": "translation_started", "stage": "translation", "completed": 0, "total": 3},
        {"type": "translation_progress", "stage": "translation", "completed": 1, "total": 3, "progress": 1 / 3},
        {"type": "task_failed", "stage": "translation", "completed": None, "total": None, "progress": None, "message": "network"},
    ])
    manager = TaskManager(store, worker)

    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "failed")

    saved = manager.get_task(task.task_id)
    assert saved.completed == 1
    assert saved.total == 3
    assert saved.progress == 1 / 3
    await manager.close()


async def test_no_speech_event_sets_distinct_track_status(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "silent.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Silent", rj_code="RJ00000108"
    ))
    manager = TaskManager(store, FakeWorkerAdapter([
        {"type": "task_no_speech", "stage": "no_speech", "progress": 1.0,
         "message": "未识别到可生成字幕的语音"},
    ]))

    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="asmr", whisper_model="medium", llm_profile_id="profile"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "no_speech")

    assert store.get_track(imported.track_id)[1].status == "no_speech"
    await manager.close()


async def test_task_manager_persists_events_and_completes_track(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000100"
    ))
    worker = FakeWorkerAdapter([
        {"type": EventType.ASR_STARTED.value, "stage": "asr"},
        {"type": EventType.ASR_PROGRESS.value, "stage": "asr", "progress": 0.5},
        {"type": EventType.TRANSLATION_PROGRESS.value, "stage": "translation", "completed": 1, "total": 2, "progress": 0.5},
        {"type": EventType.TASK_COMPLETED.value, "stage": "complete"},
    ])
    manager = TaskManager(store, worker, media_concurrency=1)

    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="asmr", whisper_model="medium", llm_profile_id="profile"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")

    saved = manager.get_task(task.task_id)
    assert saved.stage == "complete"
    assert saved.config_snapshot["scene"] == "asmr"
    assert store.get_track(imported.track_id)[1].status == "playable"
    await manager.close()


async def test_task_request_uses_translate_workers_independent_of_asr_concurrency(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000109"
    ))
    captured = {}

    class CaptureWorker(FakeWorkerAdapter):
        async def events(self, task, request):
            captured.update(request)
            async for event in super().events(task, request):
                yield event

    manager = TaskManager(
        store,
        CaptureWorker([{"type": "task_completed", "stage": "complete"}]),
        asr_concurrency=1,
        translate_workers=6,
    )
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")

    overrides = captured["config_overrides"]
    assert overrides["translate_workers"] == 6
    assert overrides["translation_global_workers"] == 6
    assert overrides["translation_limiter_dir"] == str(
        (store.root / ".subforge" / "translation-slots").resolve()
    )
    await manager.close()


async def test_task_request_reads_translate_workers_for_each_new_task(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio_a = tmp_path / "audio-a.m4a"
    audio_b = tmp_path / "audio-b.m4a"
    audio_a.write_bytes(b"audio-a")
    audio_b.write_bytes(b"audio-b")
    imported_a = store.import_audio(ImportRequest(
        source=audio_a, kind=ItemKind.RJ_WORK, title="Work A", rj_code="RJ00000110"
    ))
    imported_b = store.import_audio(ImportRequest(
        source=audio_b, kind=ItemKind.RJ_WORK, title="Work B", rj_code="RJ00000111"
    ))
    captured = []
    current_workers = 6

    class CaptureWorker(FakeWorkerAdapter):
        async def events(self, task, request):
            captured.append(request["config_overrides"]["translate_workers"])
            async for event in super().events(task, request):
                yield event

    manager = TaskManager(
        store,
        CaptureWorker([{"type": "task_completed", "stage": "complete"}]),
        translate_workers=6,
        translate_workers_resolver=lambda: current_workers,
    )
    task_a = await manager.enqueue(imported_a.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task_a.task_id).status == "completed")

    current_workers = 1
    task_b = await manager.enqueue(imported_b.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task_b.task_id).status == "completed")

    assert captured == [6, 1]
    await manager.close()


async def test_task_request_uses_direct_model_path_when_configured(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000105"
    ))
    captured = {}
    direct = tmp_path / "large-v3"
    direct.mkdir()

    class CaptureWorker(FakeWorkerAdapter):
        async def events(self, task, request):
            captured.update(request)
            async for event in super().events(task, request):
                yield event

    manager = TaskManager(
        store, CaptureWorker([{"type": "task_completed", "stage": "complete"}]),
        models_dir_resolver=lambda: tmp_path / "cache",
        direct_model_resolver=lambda model: direct if model == "large-v3" else None,
    )
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="large-v3", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")

    assert captured["model_path"] == str(direct.resolve())
    assert captured["config_overrides"]["models_dir"] == str((tmp_path / "cache").resolve())
    await manager.close()


async def test_task_request_passes_configured_proxy_to_worker(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000104"
    ))
    captured = {}

    class CaptureWorker(FakeWorkerAdapter):
        async def events(self, task, request):
            captured.update(request)
            async for event in super().events(task, request):
                yield event

    manager = TaskManager(
        store, CaptureWorker([{"type": "task_completed", "stage": "complete"}]),
        proxy_resolver=lambda: "http://127.0.0.1:7890",
    )
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")

    assert captured["proxy_url"] == "http://127.0.0.1:7890"
    await manager.close()


async def test_task_request_passes_profile_proxy_and_tls_to_worker(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000105"
    ))
    captured = {}

    class CaptureWorker(FakeWorkerAdapter):
        async def events(self, task, request):
            captured.update(request)
            async for event in super().events(task, request):
                yield event

    profile = LlmProfile(
        profile_id="p", name="Internal", base_url="https://api.internal/v1",
        model="chat", api_key="secret", proxy_url="", verify_tls=False,
        ca_bundle="C:/ca.pem",
    )
    manager = TaskManager(
        store, CaptureWorker([{"type": "task_completed", "stage": "complete"}]),
        profile_resolver=lambda pid: profile if pid == "p" else None,
    )
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")

    overrides = captured["config_overrides"]
    assert overrides["llm_base_url"] == "https://api.internal/v1"
    assert overrides["llm_proxy_url"] == ""
    assert overrides["llm_verify_tls"] is False
    assert overrides["llm_ca_bundle"] == "C:/ca.pem"
    assert captured["llm_api_key"] == "secret"
    await manager.close()


async def test_asmr_task_request_uses_full_shared_preset(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000102"
    ))
    captured = {}

    class CaptureWorker(FakeWorkerAdapter):
        async def events(self, task, request):
            captured.update(request)
            async for event in super().events(task, request):
                yield event

    manager = TaskManager(store, CaptureWorker([{"type": "task_completed", "stage": "complete"}]))
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="asmr", whisper_model="large-v3", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")

    overrides = captured["config_overrides"]
    assert overrides["device"] == "auto"
    assert overrides["compute_type"] == "auto"
    assert overrides["vad_threshold"] == 0.2
    assert overrides["condition_on_previous_text"] is False
    assert overrides["preprocess_audio"] is True
    await manager.close()


async def test_restart_restores_persisted_unfinished_task(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000107"
    ))
    snapshot = '{"asr_provider":"local","scene":"normal","whisper_model":"medium","llm_profile_id":"p"}'
    with store._db_lock, store._db:
        store._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("restore-me", imported.track_id, "running", "translation", 0.5, snapshot, "now"),
        )
    store.update_track_status(imported.track_id, "processing")

    manager = TaskManager(store, FakeWorkerAdapter([
        {"type": "task_completed", "stage": "complete", "progress": 1.0},
    ]))
    await _wait_until(lambda: manager.get_task("restore-me").status == "completed")

    assert store.get_track(imported.track_id)[1].status == "playable"
    await manager.close()


async def test_restart_marks_orphan_transient_track_state_interrupted(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000103"
    ))
    store.update_track_status(imported.track_id, "processing")

    manager = TaskManager(store, FakeWorkerAdapter([]))

    assert store.get_track(imported.track_id)[1].status == "interrupted"
    await manager.close()


async def test_cancel_keeps_track_and_marks_task_cancelled(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000101"
    ))
    worker = FakeWorkerAdapter([], wait_forever=True)
    manager = TaskManager(store, worker)
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "running")

    await manager.cancel(task.task_id)

    assert manager.get_task(task.task_id).status == "cancelled"
    assert store.track_media_path(imported.track_id).exists()
    await manager.close()


async def test_task_request_carries_asr_and_merge_profile_snapshots(tmp_path):
    """统一模型 Profile：ASR / 合并快照进入 config_overrides，密钥经环境变量通道。"""
    from subforge.ui.model_profiles import ModelProfile

    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000106"
    ))
    captured = {}

    class CaptureWorker(FakeWorkerAdapter):
        async def events(self, task, request):
            captured.update(request)
            async for event in super().events(task, request):
                yield event

    asr = ModelProfile(
        profile_id="asr1", name="Gemini", base_url="https://g/v1", model="gemini-flash",
        api_key="asr-secret", protocol="openai_compatible",
        capabilities=["transcribe", "translate"], max_request_seconds=45,
    )
    merge = ModelProfile(
        profile_id="merge1", name="Big", base_url="https://big/v1", model="big-model",
        api_key="merge-secret", capabilities=["merge"], merge_prompt="校对",
    )
    by_id = {"asr1": asr, "merge1": merge}
    manager = TaskManager(
        store, CaptureWorker([{"type": "task_completed", "stage": "complete"}]),
        profile_resolver=lambda pid: by_id.get(pid),
    )
    task = await manager.enqueue(imported.track_id, ProcessingSnapshot(
        asr_provider="model", scene="normal", whisper_model="medium", llm_profile_id="asr1",
        asr_profile_id="asr1", merge_profile_id="merge1",
    ))
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")

    overrides = captured["config_overrides"]
    assert overrides["asr_provider"] == "model"
    assert overrides["asr_profile"]["model"] == "gemini-flash"
    assert overrides["asr_profile"]["max_request_seconds"] == 45
    assert "api_key" not in overrides["asr_profile"]  # 密钥不入请求文件
    assert overrides["merge_profile"]["model"] == "big-model"
    assert overrides["merge_profile"]["merge_prompt"] == "校对"
    assert captured["asr_api_key"] == "asr-secret"
    assert captured["merge_api_key"] == "merge-secret"
    await manager.close()


async def test_terminal_tasks_survive_restart(tmp_path):
    """终态任务（含 awaiting_review）在重启后留存，不再被删除。"""
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000108"
    ))
    with store._db_lock, store._db:
        store._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("done-1", imported.track_id, "completed", "complete", 1.0, "{}", "2020-01-01T00:00:00Z"),
        )
        store._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("review-1", imported.track_id, "awaiting_review", "review", 1.0, "{}", "2020-01-02T00:00:00Z"),
        )
    store.close()

    reopened = LibraryStore.open(tmp_path / "Library")
    manager = TaskManager(reopened, FakeWorkerAdapter([]))
    statuses = {task.task_id: task.status for task in manager.list_tasks()}
    assert statuses.get("done-1") == "completed"
    assert statuses.get("review-1") == "awaiting_review"
    # 未完成任务没有被错误地重新入队（本测试里没有 queued/running 项）
    assert all(task_id not in manager._tasks for task_id in ("done-1", "review-1"))
    await manager.close()


def test_task_columns_migrate_idempotently(tmp_path):
    """旧库升级时幂等补齐新增列，且不会重复报错。"""
    store = LibraryStore.initialize(tmp_path / "Library")
    columns = {row[1] for row in store._db.execute("PRAGMA table_info(tasks)").fetchall()}
    assert {"kind", "payload_json", "result_json", "created_at", "started_at", "finished_at"} <= columns
    # 再次迁移应无副作用
    store._migrate_task_columns()
    columns2 = {row[1] for row in store._db.execute("PRAGMA table_info(tasks)").fetchall()}
    assert columns2 == columns
    store.close()


async def test_segment_reprocess_task_persists_result_and_discard(tmp_path):
    """片段候选结果写入 SQLite，重启后仍可读取；放弃只改任务状态，不动字幕。"""
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000109"
    ))
    candidate = {
        "processor": "whisper", "target_start": 0.0, "target_end": 2.0,
        "warnings": [], "source_entries": [{"index": 1, "start": 0.0, "end": 2.0, "text": "候选"}],
        "target_entries": [{"index": 1, "start": 0.0, "end": 2.0, "text": "译文"}],
        "current_source": [], "current_target": [],
    }

    async def runner(track_id, payload, report):
        report("segment", 0.5, "生成中")
        return candidate

    manager = TaskManager(store, FakeWorkerAdapter([]), segment_runner=runner)
    task = await manager.enqueue_segment_reprocess(imported.track_id, {"start_index": "1", "end_index": "1"})
    await _wait_until(lambda: manager.get_task(task.task_id).status == "awaiting_review")
    assert manager.get_task(task.task_id).result == candidate
    await manager.close()
    store.close()

    reopened = LibraryStore.open(tmp_path / "Library")
    manager2 = TaskManager(reopened, FakeWorkerAdapter([]))
    persisted = manager2.get_task(task.task_id)
    assert persisted.status == "awaiting_review"
    assert persisted.result == candidate
    assert persisted.kind == "segment_reprocess"
    assert persisted.payload == {"start_index": "1", "end_index": "1"}

    await manager2.mark_reviewed(task.task_id, status="discarded", message="候选已放弃")
    assert manager2.get_task(task.task_id).status == "discarded"
    await manager2.close()


def _segment_candidate() -> dict:
    return {
        "processor": "whisper", "target_start": 0.0, "target_end": 2.0,
        "warnings": [],
        "source_entries": [{"index": 1, "start": 0.0, "end": 2.0, "text": "候选"}],
        "target_entries": [{"index": 1, "start": 0.0, "end": 2.0, "text": "译文"}],
        "current_source": [], "current_target": [],
    }


def _make_store(tmp_path, title, rj):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / f"{rj}.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title=title, rj_code=rj
    ))
    return store, imported


async def test_segment_retry_reuses_task_id_and_reaches_review(tmp_path):
    """失败的片段任务可手动重试：同一 task_id、复用 payload、不动音轨状态。"""
    store, imported = _make_store(tmp_path, "RetrySeg", "RJ00000111")
    status_before = store.get_track(imported.track_id)[1].status
    calls = {"n": 0}

    async def runner(track_id, payload, report):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return _segment_candidate()

    manager = TaskManager(store, FakeWorkerAdapter([]), segment_runner=runner)
    task = await manager.enqueue_segment_reprocess(
        imported.track_id, {"start_index": "1", "end_index": "1"}
    )
    await _wait_until(lambda: manager.get_task(task.task_id).status == "failed")
    failed = manager.get_task(task.task_id)
    assert failed.finished_at is not None

    retried = await manager.retry_segment(failed)
    assert retried.task_id == task.task_id
    assert retried.status == "queued"
    assert retried.finished_at is None
    assert retried.result is None

    await _wait_until(lambda: manager.get_task(task.task_id).status == "awaiting_review")
    assert calls["n"] == 2
    assert manager.get_task(task.task_id).result == _segment_candidate()
    # 片段重试不触碰音轨处理状态
    assert store.get_track(imported.track_id)[1].status == status_before
    await manager.close()


async def test_segment_retry_without_payload_is_rejected(tmp_path):
    """没有 payload 的片段任务不能重试（fail-closed）。"""
    store, imported = _make_store(tmp_path, "NoPayload", "RJ00000112")

    async def runner(track_id, payload, report):
        raise RuntimeError("bad range")

    manager = TaskManager(store, FakeWorkerAdapter([]), segment_runner=runner)
    task = await manager.enqueue_segment_reprocess(imported.track_id, {})
    await _wait_until(lambda: manager.get_task(task.task_id).status == "failed")
    with pytest.raises(ValueError):
        await manager.retry_segment(manager.get_task(task.task_id))
    await manager.close()


async def test_started_at_set_on_run_and_reset_on_manual_retry(tmp_path):
    """started_at 记录本次开始时间；手动重试时重置 started_at 并清 finished_at。"""
    store, manager, task, worker = await _auto_retry_manager(tmp_path, [
        [{"type": "task_failed", "stage": "asr", "message": "boom"}],
    ])
    await _wait_until(lambda: manager.get_task(task.task_id).status == "failed")
    failed = manager.get_task(task.task_id)
    assert failed.started_at is not None
    assert failed.finished_at is not None
    old_started = failed.started_at

    worker._outcomes = [[{"type": "task_completed", "stage": "complete"}]]
    retried = await manager.retry(failed)
    assert retried.started_at is None
    assert retried.finished_at is None

    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")
    again = manager.get_task(task.task_id)
    assert again.started_at is not None
    assert again.started_at >= old_started
    await manager.close()


async def test_auto_retry_clears_stale_finished_at(tmp_path):
    """自动重试进入新一轮时会清掉上一轮失败残留的 finished_at。"""
    store, manager, task, worker = await _auto_retry_manager(tmp_path, [
        [{"type": "task_failed", "stage": "asr", "message": "boom"}],
        [{"type": "task_failed", "stage": "asr", "message": "boom2"}],
        [{"type": "task_completed", "stage": "complete"}],
    ])
    await _wait_until(lambda: manager.get_task(task.task_id).status == "completed")
    final = manager.get_task(task.task_id)
    # finished_at 是最终完成时间，必须不早于最后一次开始的 started_at；
    # 若残留首轮失败的时间戳，则会早于最后一次 started_at
    assert final.finished_at >= final.started_at
    await manager.close()


class _GatedWorker(FakeWorkerAdapter):
    """每个任务发出一个事件后在 gate 上等待，保持 running 状态。"""

    def __init__(self):
        self.started: list[str] = []
        self.gate = asyncio.Event()

    async def events(self, task, request):
        self.started.append(task.task_id)
        yield {"job_id": task.task_id, "type": "asr_progress", "stage": "asr", "progress": 0.1}
        await self.gate.wait()

    async def cancel(self, task_id):
        self.gate.set()


async def test_summary_splits_local_and_remote_worker_counts(tmp_path):
    """Worker 摘要按本地/网络 ASR 分域计数；本地占满时网络任务照常运行。"""
    store = LibraryStore.initialize(tmp_path / "Library")
    tracks = []
    for index in range(4):
        audio = tmp_path / f"a{index}.m4a"
        audio.write_bytes(b"audio")
        imported = store.import_audio(ImportRequest(
            source=audio, kind=ItemKind.RJ_WORK,
            title=f"W{index}", rj_code=f"RJ0000020{index}",
        ))
        tracks.append(imported.track_id)

    worker = _GatedWorker()

    async def runner(track_id, payload, report):
        await worker.gate.wait()
        return _segment_candidate()

    manager = TaskManager(
        store, worker,
        asr_concurrency=1, remote_asr_concurrency=2, segment_runner=runner,
    )
    local_full = await manager.enqueue(tracks[0], ProcessingSnapshot(
        asr_provider="local", scene="normal", whisper_model="medium", llm_profile_id="p"))
    remote_full = await manager.enqueue(tracks[1], ProcessingSnapshot(
        asr_provider="deepgram", scene="normal", whisper_model="medium", llm_profile_id="p"))
    seg_whisper = await manager.enqueue_segment_reprocess(
        tracks[2], {"processor": "whisper", "start_index": "1", "end_index": "1"})
    seg_gemini = await manager.enqueue_segment_reprocess(
        tracks[3], {"processor": "gemini", "start_index": "1", "end_index": "1"})

    def _statuses():
        return {
            task.task_id: manager.get_task(task.task_id).status
            for task in (local_full, remote_full, seg_whisper, seg_gemini)
        }

    # 本地全轨 running、网络全轨 running、网络片段 running、本地片段排队
    await _wait_until(lambda: _statuses() == {
        local_full.task_id: "running",
        remote_full.task_id: "running",
        seg_whisper.task_id: "queued",
        seg_gemini.task_id: "running",
    })
    summary = manager.summary()
    assert summary["local_running"] == 1
    assert summary["local_capacity"] == 1
    assert summary["remote_running"] == 2
    assert summary["remote_capacity"] == 2
    assert summary["queued"] == 1  # whisper 片段任务在等本地信号量
    worker.gate.set()
    await manager.close()


async def test_segment_reprocess_stage_and_batch_progress(tmp_path):
    """片段重处理的分片进度与终态阶段正确同步（complete / discarded）。"""
    store, imported = _make_store(tmp_path, "SegProg", "RJ00000115")

    async def runner(track_id, payload, report):
        report("asr", 0.5, "转写中", completed=1, total=2)
        return _segment_candidate()

    manager = TaskManager(store, FakeWorkerAdapter([]), segment_runner=runner)
    task = await manager.enqueue_segment_reprocess(
        imported.track_id,
        {"processor": "gemini", "start_time": 20.0, "end_time": 140.0, "asr_chunk_seconds": 60},
    )
    await _wait_until(lambda: manager.get_task(task.task_id).status == "awaiting_review")
    awaiting = manager.get_task(task.task_id)
    assert awaiting.stage == "review"
    assert awaiting.completed == 2
    assert awaiting.total == 2

    completed = await manager.mark_reviewed(task.task_id, status="completed", message="候选已接受并替换")
    assert completed.status == "completed"
    assert completed.stage == "complete"
    assert completed.completed == 2
    assert completed.total == 2
    await manager.close()
    store.close()


async def test_segment_task_failure_keeps_history(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000110"
    ))

    async def runner(track_id, payload, report):
        raise RuntimeError("provider down")

    manager = TaskManager(store, FakeWorkerAdapter([]), segment_runner=runner)
    task = await manager.enqueue_segment_reprocess(imported.track_id, {})
    await _wait_until(lambda: manager.get_task(task.task_id).status == "failed")
    failed = manager.get_task(task.task_id)
    assert failed.message == "provider down"
    assert failed.finished_at is not None
    await manager.close()
    store.close()


async def test_delete_removes_terminal_task_row_only(tmp_path):
    """终态任务可删除并从列表消失；非终态与待评审任务拒绝删除。"""
    store, imported = _make_store(tmp_path, "DelSeg", "RJ00000113")
    candidate = _segment_candidate()

    async def runner(track_id, payload, report):
        return candidate

    manager = TaskManager(store, FakeWorkerAdapter([]), segment_runner=runner)
    done = await manager.enqueue_segment_reprocess(imported.track_id, {"start_index": "1", "end_index": "1"})
    await _wait_until(lambda: manager.get_task(done.task_id).status == "awaiting_review")

    # awaiting_review 不可删（须先评审）
    with pytest.raises(ValueError):
        manager.delete_task(done.task_id)
    await manager.mark_reviewed(done.task_id, status="discarded", message="候选已放弃")
    # 终态（discarded）可删
    manager.delete_task(done.task_id)
    with pytest.raises(KeyError):
        manager.get_task(done.task_id)
    assert all(task.task_id != done.task_id for task in manager.list_tasks())
    await manager.close()


async def test_delete_rejected_for_running_task(tmp_path):
    """非终态任务不能删除。"""
    store, imported = _make_store(tmp_path, "DelRun", "RJ00000114")
    worker = _GatedWorker()

    async def runner(track_id, payload, report):
        await worker.gate.wait()
        return _segment_candidate()

    manager = TaskManager(store, worker, segment_runner=runner)
    task = await manager.enqueue_segment_reprocess(
        imported.track_id, {"processor": "whisper", "start_index": "1", "end_index": "1"}
    )
    await _wait_until(lambda: manager.get_task(task.task_id).status == "running")
    with pytest.raises(ValueError):
        manager.delete_task(task.task_id)
    worker.gate.set()
    await manager.close()
