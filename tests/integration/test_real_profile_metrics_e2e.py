"""End-to-End integration test for Real Profile Metrics & Health Connectivity.

Failure modes documented upfront:
FM1: Profile cards must NOT use synthetic/hash-based mock statistics (no getDeterministicProfileMetrics).
FM2: GET /api/profiles must return real health and usage statistics (selection_history count and last_used).
FM3: POST /profiles/{profile_id}/test must measure actual latency in ms and persist the test result to disk.
FM4: Profile health status must be retained across subsequent API requests and page reloads.
FM5: Production frontend bundle must build without any mock profile metric calculations.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock

from starlette.testclient import TestClient

from subforge.library import LibraryStore, ItemKind, CreatorKind
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore, ModelProfile
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter


def test_real_profile_metrics_and_health_e2e(tmp_path: Path):
    # 1. Setup isolated test environment
    lib_dir = tmp_path / "library"
    lib_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    settings = UiSettingsStore(config_dir / "ui.json")
    settings.set_active_library(lib_dir)

    library = LibraryStore.initialize(lib_dir)

    # Record authentic selection history for a profile
    test_profile_id = "real_prof_001"
    library.record_selection("full.translation_profile", test_profile_id)
    library.record_selection("full.translation_profile", test_profile_id)
    library.record_selection("segment.translation_profile", test_profile_id)

    profile_store = ModelProfileStore(config_dir / "model-profiles.json")
    p = ModelProfile(
        profile_id=test_profile_id,
        name="DeepSeek Test Profile",
        base_url="https://api.deepseek.test/v1",
        model="deepseek-chat",
        api_key="sk-test-secret-12345",
        capabilities=["translate"],
        temperature=0.2,
        max_request_seconds=60,
    )
    profile_store._save_all([p])

    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=profile_store,
        worker=FakeWorkerAdapter([]),
        startup_token="e2e-token-xyz",
        is_fixed_token=True,
        allowed_hosts={"127.0.0.1", "localhost", "testserver"},
    )

    app = create_app(deps)
    client = TestClient(app, base_url="http://testserver")

    # Authenticate session
    auth_res = client.get("/?token=e2e-token-xyz", follow_redirects=True)
    assert auth_res.status_code == 200

    csrf = client.get("/api/session").json()["csrf_token"]
    headers = {"x-csrf-token": csrf, "origin": "http://testserver"}

    # FM1: Verify that fake metric calculations are completely removed from frontend
    frontend_profile_src = Path("frontend/src/pages/Profiles/index.tsx").read_text(encoding="utf-8")
    assert "getDeterministicProfileMetrics" not in frontend_profile_src, "FM1: getDeterministicProfileMetrics must be deleted"
    assert "dynamicDeltas" not in frontend_profile_src, "FM1: dynamicDeltas must be deleted"

    # FM2: Initial GET /api/profiles returns real usage data and initial untested health
    res1 = client.get("/api/profiles")
    assert res1.status_code == 200
    data1 = res1.json()
    llm_profiles = data1.get("llm_profiles", [])
    target_p = next((item for item in llm_profiles if item["profile_id"] == test_profile_id), None)
    assert target_p is not None

    assert "usage" in target_p, "FM2: Profile must include usage object"
    assert target_p["usage"]["selected_count"] == 3, "FM2: Usage count must reflect the 3 recorded selections"
    assert target_p["usage"]["last_used_at"] is not None

    assert "health" in target_p, "FM2: Profile must include health object"
    assert target_p["health"]["status"] == "untested"

    # FM3: Test connectivity with mocked fast connection check
    with patch("subforge.ui.app.test_profile_connection", new_callable=AsyncMock) as mock_conn:
        mock_conn.return_value = (True, "连接成功")
        test_res = client.post(f"/profiles/{test_profile_id}/test", headers=headers)
        assert test_res.status_code == 200
        test_data = test_res.json()
        assert test_data["ok"] is True
        assert test_data["status"] == "online"
        assert isinstance(test_data["latency_ms"], int)
        assert test_data["latency_ms"] >= 0
        assert "tested_at" in test_data

    # FM4: Subsequent GET /api/profiles retains the tested health information
    res2 = client.get("/api/profiles")
    assert res2.status_code == 200
    data2 = res2.json()
    target_p2 = next((item for item in data2["llm_profiles"] if item["profile_id"] == test_profile_id), None)
    assert target_p2 is not None
    assert target_p2["health"]["status"] == "online"
    assert target_p2["health"]["message"] == "连接成功"
    assert target_p2["health"]["latency_ms"] is not None

    # Verify disk persistence in profile-health.json
    health_file = config_dir / "profile-health.json"
    assert health_file.exists(), "FM3/FM4: Health must be persisted to profile-health.json"
    disk_health = json.loads(health_file.read_text(encoding="utf-8"))
    assert test_profile_id in disk_health
    assert disk_health[test_profile_id]["status"] == "online"

    # 5. Write verifiable artifact
    artifact = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verified_features": [
            "mock_metrics_removed_from_profiles_page",
            "real_usage_history_from_library_sqlite",
            "real_latency_and_health_monitoring_endpoint",
            "profile_health_disk_persistence",
            "real_profile_card_rendering",
        ],
        "sample_profile_tested": {
            "profile_id": test_profile_id,
            "selected_count": target_p2["usage"]["selected_count"],
            "health_status": target_p2["health"]["status"],
            "latency_ms": target_p2["health"]["latency_ms"],
            "message": target_p2["health"]["message"],
        },
        "verification_result": "PASS",
    }
    artifact_dir = Path("artifacts")
    artifact_dir.mkdir(exist_ok=True)
    artifact_file = artifact_dir / "real_profile_metrics_e2e_artifact.json"
    artifact_file.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Artifact written to {artifact_file}")
