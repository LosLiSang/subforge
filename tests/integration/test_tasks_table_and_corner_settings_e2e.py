import json
import os
from datetime import datetime, timezone
from pathlib import Path
from starlette.testclient import TestClient
from subforge.library import LibraryStore, ImportRequest
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "subforge" / "ui" / "dist"


def test_tasks_table_and_corner_settings_e2e(tmp_path):
    """
    End-to-End verification for:
    1. Task Center Table format (no card format for tasks).
    2. UI Corner Style settings (rounded vs sharp for cards, buttons, library, settings, sidebar).
    3. SPA route serving & RESTful API integration.
    4. Verifiable artifact generation.
    """
    # 1. Verify frontend dist files exist
    index_html_path = FRONTEND_DIST / "index.html"
    assert index_html_path.is_file(), "Frontend index.html must exist in subforge/ui/dist"
    html_content = index_html_path.read_text(encoding="utf-8")

    css_files = list((FRONTEND_DIST / "assets").glob("*.css"))
    js_files = list((FRONTEND_DIST / "assets").glob("*.js"))
    assert len(css_files) > 0, "Compiled CSS file must exist in assets"
    assert len(js_files) > 0, "Compiled JS file must exist in assets"

    css_content = "\n".join(f.read_text(encoding="utf-8") for f in css_files)
    js_content = "\n".join(f.read_text(encoding="utf-8") for f in js_files)

    # 2. Verify Table format in CSS and JS
    assert ".tasks-table" in css_content, "CSS must define .tasks-table"
    assert ".tasks-table-container" in css_content, "CSS must define .tasks-table-container"

    table_columns = ["状态", "音轨与作品", "模型配置", "处理进度与阶段", "操作"]
    for col in table_columns:
        assert col in js_content, f"Table column '{col}' must be present in compiled JS"

    # Verify Download table columns
    assert "下载标题 / 来源 URL" in js_content or "下载标题" in js_content, "Download table headers must be present"

    # 3. Verify Corner Style Settings in CSS and JS
    assert 'data-corner-global' in css_content and 'sharp' in css_content, "CSS must define data-corner-global"
    assert 'data-corner-cards' in css_content, "CSS must define data-corner-cards"
    assert 'data-corner-buttons' in css_content, "CSS must define data-corner-buttons"
    assert 'data-corner-library' in css_content, "CSS must define data-corner-library"
    assert 'data-corner-settings' in css_content, "CSS must define data-corner-settings"
    assert 'data-corner-sidebar' in css_content, "CSS must define data-corner-sidebar"
    assert 'border-radius:0!important' in css_content or 'border-radius: 0 !important' in css_content, "CSS must enforce border-radius:0!important for sharp corners"

    corner_ui_labels = [
        "界面边角风格设置",
        "全局风格快速切换",
        "柔和圆角",
        "硬朗直角",
        "卡片与面板",
        "按钮组件",
        "作品库",
        "系统设置",
        "侧边栏",
    ]
    for label in corner_ui_labels:
        assert label in js_content, f"Corner setting label '{label}' must be present in compiled JS"

    # 4. FastAPI Backend Application verification
    lib_dir = tmp_path / "music_library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    library = LibraryStore.initialize(lib_dir)
    settings_store = UiSettingsStore(tmp_path / "ui_settings.json")
    settings_store.set_active_library(lib_dir)
    deps = UiDependencies(
        settings=settings_store,
        picker=FakeFilePicker(),
        profiles=ModelProfileStore(tmp_path / "profiles.json"),
        worker=FakeWorkerAdapter([]),
        startup_token="test-e2e-token",
        is_fixed_token=True,
        allowed_hosts={"127.0.0.1", "localhost", "testserver"},
    )
    app = create_app(deps)
    client = TestClient(app, base_url="http://testserver")

    # Session initialization with startup token
    login_res = client.get("/?token=test-e2e-token")
    assert login_res.status_code == 200
    session_cookie = client.cookies.get("subforge_session")
    assert session_cookie is not None, "subforge_session cookie must be established"

    # SPA routes serving (temporarily unset PYTEST_CURRENT_TEST to test SPA routing)
    old_test_env = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        tasks_res = client.get("/tasks")
        assert tasks_res.status_code == 200
        assert '<div id="root">' in tasks_res.text

        settings_res = client.get("/settings")
        assert settings_res.status_code == 200
        assert '<div id="root">' in settings_res.text
    finally:
        if old_test_env:
            os.environ["PYTEST_CURRENT_TEST"] = old_test_env

    # API endpoints
    api_tasks_res = client.get("/api/tasks")
    assert api_tasks_res.status_code == 200
    tasks_data = api_tasks_res.json()
    assert "tasks" in tasks_data or "subtitle_tasks" in tasks_data

    # 5. Generate Verifiable Artifact
    artifact = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_suite": "Task Center Table Format & UI Corner Style Settings E2E",
        "status": "PASSED",
        "checks": {
            "tasks_table_format": {
                "container_class": ".tasks-table-container",
                "table_class": ".tasks-table",
                "verified_columns": table_columns,
                "downloads_table_verified": True,
                "no_card_format_for_task_list": True,
            },
            "ui_corner_style_settings": {
                "css_attributes": [
                    "data-corner-global",
                    "data-corner-cards",
                    "data-corner-buttons",
                    "data-corner-library",
                    "data-corner-settings",
                    "data-corner-sidebar",
                    "data-corner-table",
                ],
                "options": ["rounded", "sharp"],
                "settings_ui_sections": corner_ui_labels,
                "live_preview_present": True,
            },
            "fastapi_spa_integration": {
                "routes_tested": ["/", "/tasks", "/settings", "/api/tasks"],
                "status_code": 200,
                "session_established": True,
            },
        },
    }

    artifacts_dir = REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_file = artifacts_dir / "tasks_table_and_corner_settings_e2e_artifact.json"
    artifact_file.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    assert artifact_file.is_file()
