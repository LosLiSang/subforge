import asyncio

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
