import asyncio

from subforge.events import EventType
from subforge.library import ImportRequest, ItemKind, LibraryStore
from subforge.ui.profiles import LlmProfile
from subforge.ui.tasks import FakeWorkerAdapter, ProcessingSnapshot, TaskManager


async def _wait_until(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


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


async def test_restart_marks_transient_track_state_interrupted(tmp_path):
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
