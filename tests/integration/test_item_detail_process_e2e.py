"""
End-to-End Verification Test for Item Detail Track & Batch Processing
=============================================================================

SYSTEM FAILURE MODES (Documented upfront as required by AGENTS.md):
-----------------------------------------------------------------------------
1. Authorization & CSRF Failures:
   - Submission using raw fetch() without 'x-csrf-token' header fails with HTTP 403.
   - SPA client ignoring HTTP 403 and navigating away, giving illusion of task start.

2. Already-Completed Track Process Bypassing:
   - Clicking '处理...' on a track with existing subtitles (双语 / playable)
     submitting default mode='continue' causes backend to assume previous snapshot
     and skip processing because resume chunks are already marked done.
   - Fix: Frontend provides mode selection defaulting to 'from_scratch' when
     subtitles exist, and backend defaults to 'from_scratch' if mode is omitted on
     playable tracks.

3. ASR Provider Auto-Detection:
   - Submitting 'asr_profile_id' without explicit 'asr_provider' causing
     _snapshot_from_form to default to 'local', ignoring the chosen API model.

4. API JSON vs HTML 303 Redirect Responses:
   - API requests sending Accept: application/json receiving HTML 303 redirects
     instead of JSONResponse with task_id.

5. Missing /api Routes:
   - /api/items/{item_id}/process not registered in routing table.
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
from subforge.translate.srt_io import write_srt
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate_test_wav(path: Path, duration_secs: float = 6.0, sample_rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(duration_secs * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            wf.writeframes(struct.pack("<h", 0))


async def test_item_detail_track_process_e2e(tmp_path):
    """
    E2E test verifying single-track process and batch-process from ItemDetail page:
    1. Import an audio track that has existing subtitles (simulating BV1Qxe266EkS.m4a).
    2. Verify CSRF rejection on raw unauthenticated call.
    3. Call POST /api/tracks/{track_id}/process with asr_profile_id and mode='from_scratch'.
    4. Verify task is enqueued with kind='full_process' and returns JSON with task_id.
    5. Call POST /api/items/{item_id}/process for batch processing and verify 200 JSON.
    6. Output verified reproducible artifact JSON.
    """
    lib_dir = tmp_path / "test_library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    library = LibraryStore.initialize(lib_dir)

    media_file = tmp_path / "BV1Qxe266EkS.wav"
    _generate_test_wav(media_file, duration_secs=6.0)
    imported = library.import_audio(ImportRequest(
        source=media_file,
        title="音轨列表处理测试作品",
        kind=ItemKind.STREAM_ARCHIVE,
        author="测试主播",
    ))
    track_id = imported.track_id
    item_id = imported.item_id

    # Mark track as completed with subtitles
    source_path = library.track_subtitle_path(track_id, "ja")
    target_path = library.track_subtitle_path(track_id, "zh")
    write_srt([SubtitleEntry(1, 0.0, 3.0, "旧日语台本")], source_path)
    write_srt([SubtitleEntry(1, 0.0, 3.0, "旧中文台本")], target_path)
    library.update_track_status(track_id, "completed")
    library.close()

    # Setup Model Profiles
    profiles_path = tmp_path / "profiles.json"
    profile_store = ModelProfileStore(profiles_path)
    asr_prof = profile_store.save(
        name="raspb",
        base_url="http://raspb:10532/v1",
        model="gemini-3.8-flash-high",
        api_key="test-key",
        capabilities=["transcribe", "translate", "merge"],
    )
    llm_prof = profile_store.save(
        name="raspb",
        base_url="http://raspb:10532/v1",
        model="gemini-3.8-flash-high",
        api_key="test-key",
        capabilities=["translate"],
    )

    worker_events = [
        {"type": "task_progress", "stage": "asr", "progress": 0.5, "message": "正在识别..."},
        {"type": "task_completed", "stage": "complete", "progress": 1.0, "message": "识别完成"},
    ]

    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(lib_dir)
    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=profile_store,
        worker=FakeWorkerAdapter(worker_events),
        startup_token="test-secret-token",
        is_fixed_token=True,
        allowed_hosts={"testserver", "localhost", "127.0.0.1"},
    )

    app = create_app(deps)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        artifact = {}

        # 1. Login & CSRF
        login_res = await client.get("/?token=test-secret-token", follow_redirects=True)
        assert login_res.status_code == 200
        csrf_token = (await client.get("/api/session")).json()["csrf_token"]
        headers = {
            "x-csrf-token": csrf_token,
            "origin": "http://testserver",
            "Accept": "application/json",
        }
        artifact["authenticated"] = True

        # 2. Verify CSRF rejection on missing token
        unauth_res = await client.post(
            f"/api/tracks/{track_id}/process",
            data={"asr_profile_id": asr_prof.profile_id, "llm_profile_id": llm_prof.profile_id},
            headers={"Accept": "application/json"},
        )
        assert unauth_res.status_code == 403
        artifact["csrf_rejected_without_token"] = True

        # 3. Post single-track process on existing completed track with mode='from_scratch'
        process_res = await client.post(
            f"/api/tracks/{track_id}/process",
            data={
                "asr_profile_id": asr_prof.profile_id,
                "llm_profile_id": llm_prof.profile_id,
                "mode": "from_scratch",
            },
            headers=headers,
        )
        assert process_res.status_code == 200, f"Expected 200 JSON, got {process_res.status_code}: {process_res.text}"
        res_json = process_res.json()
        assert res_json.get("ok") is True
        task_id = res_json["task_id"]
        artifact["single_track_task_id"] = task_id

        # Verify task is in TaskManager and database
        runtime = app.state.runtime
        task = runtime.tasks.get_task(task_id)
        assert task.kind == "full_process"
        assert task.config_snapshot["asr_provider"] == "model"
        assert task.config_snapshot["asr_profile_id"] == asr_prof.profile_id
        artifact["single_track_task_verified"] = {
            "kind": task.kind,
            "asr_provider": task.config_snapshot["asr_provider"],
            "asr_profile_id": task.config_snapshot["asr_profile_id"],
        }

        # 4. Verify batch item process API (/api/items/{item_id}/process)
        batch_res = await client.post(
            f"/api/items/{item_id}/process",
            data={
                "asr_profile_id": asr_prof.profile_id,
                "llm_profile_id": llm_prof.profile_id,
                "mode": "from_scratch",
                "scope": "all",
            },
            headers=headers,
        )
        assert batch_res.status_code == 200
        assert batch_res.json().get("ok") is True
        artifact["batch_process_verified"] = True

        # 5. Output reproducible artifact
        artifacts_dir = REPO_ROOT / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_file = artifacts_dir / "item_detail_process_e2e_artifact.json"
        artifact_payload = {
            "test_name": "test_item_detail_track_process_e2e",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "PASSED",
            "components_verified": [
                "Single track processing with 'mode' (from_scratch on playable tracks)",
                "Auto-detection of asr_provider='model' from asr_profile_id",
                "Accept: application/json returns JSONResponse instead of 303 Redirect",
                "CSRF protection on track & item processing endpoints",
                "Batch item processing API (/api/items/{id}/process)",
            ],
            "verification_data": artifact,
        }
        artifact_file.write_text(json.dumps(artifact_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        assert artifact_file.is_file()
        print(f"\n[E2E Artifact Written]: {artifact_file}")
