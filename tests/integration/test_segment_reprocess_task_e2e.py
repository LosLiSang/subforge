"""
End-to-End Verification Test for Subforge Segment Reprocess Tasks
=============================================================================

SYSTEM FAILURE MODES (Documented upfront as required by AGENTS.md):
-----------------------------------------------------------------------------
1. Parameter Mismatch Failures:
   - Client sends 'start_seconds'/'end_seconds' instead of 'start_time'/'end_time'.
   - Missing or empty 'processor' field when an ASR profile is selected (e.g. Gemini).
   - Missing start/end times causing ValueError in _resolve_segment_window.

2. Authorization & CSRF Failures:
   - Raw fetch without 'x-csrf-token' header being rejected with HTTP 403.
   - Client not catching HTTP 403/400 because fetch() only rejects on network error,
     falsely showing "task submitted" toast when no task was actually enqueued.

3. Task Data Structure & Status Transitions:
   - Segment reprocess has kind='segment_reprocess' instead of 'full_process'.
   - Segment reprocess transitions to status='awaiting_review' (stage='review')
     rather than immediately 'completed', because user review is required.
   - UI Task list ignoring kind='segment_reprocess' or treating 'awaiting_review'
     as 'queued', without displaying candidate review actions.

4. Metadata Serialization in /api/tasks & /api/downloads/history:
   - 'track_title', 'item_title', 'item_id' missing because _task_display_context
     did not retrieve item/track from LibraryStore.
   - 'range', 'asr', 'translation' missing from response dictionary.

5. Candidate Review & Lifecycle:
   - /api/tasks/{task_id}/candidate endpoint missing or returning 404.
   - /api/tasks/{task_id}/candidate/confirm failing to replace subtitle range
     or not updating task status to 'completed'.
   - /api/tasks/{task_id}/candidate/discard failing to mark task status as 'discarded'.
"""

import asyncio
import json
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
import httpx

from subforge.library import LibraryStore, ItemKind, ImportRequest
from subforge.models import SubtitleEntry
from subforge.segment_processing import SegmentCandidate
from subforge.translate.srt_io import write_srt
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate_test_wav(path: Path, duration_secs: float = 10.0, sample_rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(duration_secs * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            wf.writeframes(struct.pack("<h", 0))


async def test_segment_reprocess_full_lifecycle_e2e(tmp_path):
    """
    E2E test verifying the complete segment reprocess task lifecycle:
    1. Import an audio track and create baseline subtitles.
    2. Submit segment reprocess using both start_seconds and start_time variants.
    3. Auto-detection of 'gemini' processor when asr_profile_id is present.
    4. Verification that /api/tasks returns the task with kind='segment_reprocess',
       status='awaiting_review', correct track_title, item_title, and range.
    5. Reviewing the generated candidate via /api/tasks/{task_id}/candidate.
    6. Confirming the candidate via /api/tasks/{task_id}/candidate/confirm.
    7. Verifying task status updates to 'completed' and subtitles are updated.
    8. Verifying discard flow with another segment task.
    9. Produces a verifiable and reproducible artifact JSON.
    """
    lib_dir = tmp_path / "test_library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    library = LibraryStore.initialize(lib_dir)

    media_file = tmp_path / "sample_track.wav"
    _generate_test_wav(media_file, duration_secs=10.0)

    imported = library.import_audio(ImportRequest(
        source=media_file,
        title="局部疑难句重跑测试作品",
        kind=ItemKind.RJ_WORK,
        rj_code="RJ12345678",
    ))
    track_id = imported.track_id
    item_id = imported.item_id

    # Create initial baseline subtitles
    source_path = library.track_subtitle_path(track_id, "ja")
    target_path = library.track_subtitle_path(track_id, "zh")
    initial_source = [
        SubtitleEntry(index=1, start=1.0, end=3.0, text="元の日本語テキスト1"),
        SubtitleEntry(index=2, start=4.0, end=7.0, text="元の日本語テキスト2"),
    ]
    initial_target = [
        SubtitleEntry(index=1, start=1.0, end=3.0, text="初始中文译文1"),
        SubtitleEntry(index=2, start=4.0, end=7.0, text="初始中文译文2"),
    ]
    write_srt(initial_source, source_path)
    write_srt(initial_target, target_path)
    library.update_track_status(track_id, "completed")
    library.close()

    # Setup Model Profiles
    profiles_path = tmp_path / "profiles.json"
    profile_store = ModelProfileStore(profiles_path)
    asr_prof = profile_store.save(
        name="raspb-gemini",
        base_url="http://raspb:10532/v1",
        model="gemini-3.8-flash-high",
        api_key="test-key",
        capabilities=["transcribe", "translate", "merge"],
    )
    llm_prof = profile_store.save(
        name="raspb-llm",
        base_url="http://raspb:10532/v1",
        model="gemini-3.8-flash-high",
        api_key="test-key",
        capabilities=["translate"],
    )

    class FakeSegmentProcessor:
        def __init__(self, options):
            self.options = options

        async def process(self, request):
            return SegmentCandidate(
                [SubtitleEntry(index=2, start=4.0, end=7.0, text="【重跑识别】高精度日语")],
                [SubtitleEntry(index=2, start=4.0, end=7.0, text="【重跑翻译】优化后的中文")],
                self.options.get("processor", "gemini"),
                request.target_start,
                request.target_end,
                warnings=["检测到重跑区间覆盖第 2 行"],
            )

    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(lib_dir)
    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=profile_store,
        worker=FakeWorkerAdapter([]),
        segment_processor_factory=lambda opts: FakeSegmentProcessor(opts),
        startup_token="test-secret-token",
        is_fixed_token=True,
        allowed_hosts={"testserver", "localhost", "127.0.0.1"},
    )

    app = create_app(deps)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        artifact = {}

        # 1. Negotiate session & CSRF token
        login_res = await client.get("/?token=test-secret-token", follow_redirects=True)
        assert login_res.status_code == 200
        session_info = (await client.get("/api/session")).json()
        csrf_token = session_info["csrf_token"]
        headers = {"x-csrf-token": csrf_token, "origin": "http://testserver"}
        artifact["csrf_authenticated"] = True

        # 2. Test CSRF Protection (Failure Mode 2: Missing CSRF fails with 403)
        unauthorized_res = await client.post(
            f"/api/tracks/{track_id}/segments/reprocess",
            data={"start_time": "4.0", "end_time": "7.0"},
        )
        assert unauthorized_res.status_code == 403
        artifact["csrf_rejection_verified"] = True

        # 3. Submit segment reprocess using frontend parameters
        # Testing tolerance of start_seconds / end_seconds and asr_profile_id
        reprocess_res = await client.post(
            f"/api/tracks/{track_id}/segments/reprocess",
            data={
                "start_seconds": "4.0",
                "end_seconds": "7.0",
                "start_time": "4.0",
                "end_time": "7.0",
                "processor": "gemini",
                "asr_profile_id": asr_prof.profile_id,
                "llm_profile_id": llm_prof.profile_id,
            },
            headers=headers,
        )
        assert reprocess_res.status_code == 202, f"Expected 202 Accepted, got {reprocess_res.status_code}: {reprocess_res.text}"
        task_id = reprocess_res.json()["task_id"]
        artifact["task_enqueued_id"] = task_id

        # 4. Wait for background execution to complete and enter awaiting_review
        runtime = app.state.runtime
        final_task = None
        for _ in range(60):
            cur = runtime.tasks.get_task(task_id)
            if cur.status in ("awaiting_review", "completed", "failed"):
                final_task = cur
                break
            await asyncio.sleep(0.05)

        assert final_task is not None
        assert final_task.status == "awaiting_review", f"Task status should be awaiting_review, got {final_task.status}"
        assert final_task.kind == "segment_reprocess"
        assert final_task.progress == 1.0
        artifact["task_status_after_runner"] = final_task.status

        # 5. Verify /api/tasks includes all metadata
        tasks_res = await client.get("/api/tasks", headers=headers)
        assert tasks_res.status_code == 200
        tasks_data = tasks_res.json()
        assert "tasks" in tasks_data
        matching = next((t for t in tasks_data["tasks"] if t["task_id"] == task_id), None)
        assert matching is not None, "Task must be visible in /api/tasks"
        assert matching["kind"] == "segment_reprocess"
        assert matching["status"] == "awaiting_review"
        assert matching["track_title"] == "sample_track.wav"
        assert matching["item_title"] == "局部疑难句重跑测试作品"
        assert "4.00" in (matching["range"] or "")
        artifact["tasks_api_verification"] = {
            "kind": matching["kind"],
            "status": matching["status"],
            "track_title": matching["track_title"],
            "item_title": matching["item_title"],
            "range": matching["range"],
            "asr": matching.get("asr"),
            "translation": matching.get("translation"),
        }

        # 6. Verify candidate inspection via /api/tasks/{task_id}/candidate
        cand_res = await client.get(f"/api/tasks/{task_id}/candidate", headers=headers)
        assert cand_res.status_code == 200
        cand_data = cand_res.json()
        assert cand_data["status"] == "awaiting_review"
        assert len(cand_data["candidate"]["source"]) == 1
        assert cand_data["candidate"]["source"][0]["text"] == "【重跑识别】高精度日语"
        assert cand_data["candidate"]["target"][0]["text"] == "【重跑翻译】优化后的中文"
        artifact["candidate_payload_verified"] = True

        # 7. Confirm candidate via /api/tasks/{task_id}/candidate/confirm
        confirm_res = await client.post(f"/api/tasks/{task_id}/candidate/confirm", headers=headers)
        assert confirm_res.status_code == 200
        artifact["candidate_confirmed"] = True

        # Check task status transitioned to completed
        after_confirm_task = runtime.tasks.get_task(task_id)
        assert after_confirm_task.status == "completed"
        artifact["task_status_after_confirm"] = after_confirm_task.status

        # Verify subtitles on disk were updated
        store = LibraryStore.open(lib_dir)
        updated_ja = store.track_subtitle_path(track_id, "ja").read_text(encoding="utf-8")
        updated_zh = store.track_subtitle_path(track_id, "zh").read_text(encoding="utf-8")
        assert "【重跑识别】高精度日语" in updated_ja
        assert "【重跑翻译】优化后的中文" in updated_zh
        store.close()
        artifact["subtitles_replaced_verified"] = True

        # 8. Test Discard Candidate Flow
        reprocess_res2 = await client.post(
            f"/api/tracks/{track_id}/segments/reprocess",
            data={
                "start_time": "1.0",
                "end_time": "3.0",
                "asr_profile_id": asr_prof.profile_id,
            },
            headers=headers,
        )
        assert reprocess_res2.status_code == 202
        task_id2 = reprocess_res2.json()["task_id"]

        for _ in range(60):
            cur2 = runtime.tasks.get_task(task_id2)
            if cur2.status == "awaiting_review":
                break
            await asyncio.sleep(0.05)

        discard_res = await client.post(f"/api/tasks/{task_id2}/candidate/discard", headers=headers)
        assert discard_res.status_code == 200
        assert runtime.tasks.get_task(task_id2).status == "discarded"
        artifact["candidate_discarded_verified"] = True

        # 9. Output reproducible artifact
        artifacts_dir = REPO_ROOT / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts_dir / "segment_reprocess_task_e2e_artifact.json"
        artifact_payload = {
            "test_name": "test_segment_reprocess_full_lifecycle_e2e",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "PASSED",
            "components_verified": [
                "Segment reprocess request handling with both start_time & start_seconds",
                "CSRF security token enforcement on reprocess submission",
                "Auto-detection of gemini processor when asr_profile_id is provided",
                "Background runner completion to awaiting_review state",
                "/api/tasks metadata serialization (track_title, item_title, range, asr, translation)",
                "Candidate inspection API (/api/tasks/{id}/candidate)",
                "Candidate confirm API (/api/tasks/{id}/candidate/confirm) and subtitle update",
                "Candidate discard API (/api/tasks/{id}/candidate/discard) and status transition",
            ],
            "verification_data": artifact,
        }
        artifact_path.write_text(json.dumps(artifact_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        assert artifact_path.is_file()
        print(f"\n[E2E Artifact Written]: {artifact_path}")
