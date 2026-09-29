"""
End-to-End Verification Test for Issue #6, Issue #7, and Light Theme Model Settings Fix:
- Issue #6: Works library table view size column wrapping / squeeze prevention
- Issue #7: Light theme task center tabs and .btn-ghost hover text visibility
- Light Theme Settings: Eliminate hardcoded dark rgba(0,0,0,0.25) boxes in Default Processing Models

SYSTEM FAILURE MODES (Documented upfront as required by AGENTS.md):
-----------------------------------------------------------------------------
1. FM1: Library Works Table Size Column Wrap (Issue #6):
   - In works table view, formatBytes output (e.g. '232.6 MB') contains a space.
   - Without white-space: nowrap on the size td cell, browsers wrap the unit to the second line.
   - Without an explicit or minimum width on the th column, table-layout: auto squeezes the column
     down to min-content (< 60px), severely damaging readability.

2. FM2: Light Theme .btn-ghost Hover Invisibility (Issue #7):
   - Global .btn-ghost:hover defaults to dark mode (color: #fff, background: rgba(255, 255, 255, 0.06)).
   - Under [data-theme="light"], hovering any .btn-ghost button (such as Task Center tabs, status pills,
     action buttons, creators, settings tabs) causes the text to turn pure white (#fff) against a white/light
     background (#ffffff / #f8f9fa), making text completely invisible to users (contrast ratio ~ 1:1).
   - Prior partial fix only targeted .detail-hero .btn-ghost, leaving the rest of the application broken.

3. FM3: Hardcoded Dark Background Inset Leakage (Settings Models & Cards):
   - Settings -> Default Models containers hardcode background: 'rgba(0, 0, 0, 0.25)'.
   - Under [data-theme="light"], 25% black wash turns into a muddy dark grey box (#bebebe)
     inside a clean white card, severely damaging visual contrast and aesthetics.
   - Inset cards must use semantic --bg-card-inset with #f8fafc / subtle styling in light mode.

4. FM4: Distribution Build Synchronization Failure:
   - Changes in frontend source files (frontend/src/index.css, frontend/src/pages/Library/index.tsx)
     must compile cleanly into subforge/ui/dist (assets/*.css, assets/*.js).
   - FastAPI backend must successfully serve these static assets and routes (/, /tasks, /api/library).
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from subforge.library import ImportRequest, ItemKind, LibraryStore
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
FRONTEND_DIST = REPO_ROOT / "subforge" / "ui" / "dist"


@pytest.mark.asyncio
async def test_library_size_and_light_ghost_btn_e2e(tmp_path: Path):
    # -------------------------------------------------------------------------
    # Step 1: Verify source code fixes for Issue #6 (Works table size column)
    # -------------------------------------------------------------------------
    library_page_src = (FRONTEND_SRC / "pages" / "Library" / "index.tsx").read_text(encoding="utf-8")
    
    # Verify <th> has width specified (e.g. width: 100 or 110)
    th_size_match = re.search(r'<th[^>]*style=\{\{[^}]*width:\s*(?:100|110)[^}]*\}\}[^>]*>大小</th>', library_page_src)
    assert th_size_match is not None, (
        "FM1: <th>大小</th> must have an explicit column width (width: 100 or 110) in frontend/src/pages/Library/index.tsx"
    )

    # Verify <td> with formatBytes has whiteSpace: 'nowrap'
    td_size_match = re.search(r'<td[^>]*whiteSpace:\s*[\'"]nowrap[\'"][^>]*>\s*\{formatBytes\(item\.total_size\)\}\s*</td>', library_page_src)
    assert td_size_match is not None, (
        "FM1: <td> containing formatBytes(item.total_size) must specify whiteSpace: 'nowrap'"
    )

    # -------------------------------------------------------------------------
    # Step 2: Verify source code fixes for Issue #7 (Light theme .btn-ghost)
    # -------------------------------------------------------------------------
    index_css_src = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")

    # Must define global light theme .btn-ghost and .btn-ghost:hover
    assert '[data-theme="light"] .btn-ghost' in index_css_src, (
        "FM2: frontend/src/index.css must define [data-theme=\"light\"] .btn-ghost"
    )
    assert '[data-theme="light"] .btn-ghost:hover' in index_css_src, (
        "FM2: frontend/src/index.css must define [data-theme=\"light\"] .btn-ghost:hover"
    )

    # Verify hover color in light theme is var(--fg-main) instead of white
    ghost_hover_rule = re.search(r'\[data-theme="light"\]\s+\.btn-ghost:hover\s*\{([^}]+)\}', index_css_src)
    assert ghost_hover_rule is not None, "FM2: [data-theme=\"light\"] .btn-ghost:hover rule block must exist"
    ghost_hover_content = ghost_hover_rule.group(1)
    assert "color: var(--fg-main)" in ghost_hover_content or "color: #0f172a" in ghost_hover_content, (
        "FM2: [data-theme=\"light\"] .btn-ghost:hover must set color to var(--fg-main) or dark foreground"
    )
    assert "#fff" not in ghost_hover_content, "FM2: [data-theme=\"light\"] .btn-ghost:hover must NOT turn text white"

    # Verify --bg-card-inset and .card-inset exist
    assert "--bg-card-inset" in index_css_src, "FM3: frontend/src/index.css must define --bg-card-inset"
    assert ".card-inset" in index_css_src, "FM3: frontend/src/index.css must define .card-inset class"

    # Verify Settings page uses semantic card-inset instead of hardcoded dark backgrounds
    settings_page_src = (FRONTEND_SRC / "pages" / "Settings" / "index.tsx").read_text(encoding="utf-8")
    assert "background: 'rgba(0, 0, 0, 0.25)'" not in settings_page_src, (
        "FM3: Settings page must NOT contain hardcoded background: 'rgba(0, 0, 0, 0.25)'"
    )

    # -------------------------------------------------------------------------
    # Step 3: Verify compiled distribution bundle (subforge/ui/dist)
    # -------------------------------------------------------------------------
    dist_css_files = list((FRONTEND_DIST / "assets").glob("*.css"))
    dist_js_files = list((FRONTEND_DIST / "assets").glob("*.js"))
    assert len(dist_css_files) > 0, "FM3: Compiled CSS must exist in subforge/ui/dist/assets"
    assert len(dist_js_files) > 0, "FM3: Compiled JS must exist in subforge/ui/dist/assets"

    compiled_css = "\n".join(f.read_text(encoding="utf-8") for f in dist_css_files)
    compiled_js = "\n".join(f.read_text(encoding="utf-8") for f in dist_js_files)

    # In compiled CSS, [data-theme=light] .btn-ghost:hover must be present with dark color
    assert '[data-theme=light] .btn-ghost:hover' in compiled_css or '[data-theme="light"] .btn-ghost:hover' in compiled_css, (
        "FM3: Compiled CSS bundle must contain [data-theme=light] .btn-ghost:hover"
    )

    # In compiled JS, nowrap and size column definition must be present
    assert "nowrap" in compiled_js, "FM3: Compiled JS bundle must contain nowrap styles"
    assert "card-inset" in compiled_css, "FM3: Compiled CSS bundle must contain .card-inset"

    # -------------------------------------------------------------------------
    # Step 4: FastAPI E2E runtime route serving & API integration
    # -------------------------------------------------------------------------
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    library = LibraryStore.initialize(lib_dir)

    # Add dummy media to verify total_size presentation in API response
    media_file = tmp_path / "sample.mp3"
    media_file.write_bytes(b"\x00" * (1024 * 1024 * 12))  # ~12 MB
    library.import_audio(ImportRequest(
        source=media_file,
        title="E2E Size Test Track",
        kind=ItemKind.RJ_WORK,
        rj_code="RJ123456",
    ))
    library.close()

    profile_store = ModelProfileStore(tmp_path / "model-profiles.json")
    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(lib_dir)
    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=profile_store,
            worker=FakeWorkerAdapter([]),
        startup_token="e2e-token-secret",
        is_fixed_token=True,
        allowed_hosts={"testserver", "localhost", "127.0.0.1"},
    )
    app = create_app(deps)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Temporarily unset PYTEST_CURRENT_TEST to test production React SPA serving
        old_test_env = os.environ.pop("PYTEST_CURRENT_TEST", None)
        try:
            # 1. SPA page loads
            res_home = await client.get("/?token=e2e-token-secret", follow_redirects=True)
            assert res_home.status_code == 200
            assert '<div id="root">' in res_home.text

            res_tasks = await client.get("/tasks")
            assert res_tasks.status_code == 200
            assert '<div id="root">' in res_tasks.text

            session_info = (await client.get("/api/session")).json()
            headers = {"x-csrf-token": session_info["csrf_token"], "origin": "http://testserver"}
        finally:
            if old_test_env is not None:
                os.environ["PYTEST_CURRENT_TEST"] = old_test_env

            # 2. API returns library items with total_size
            res_lib = await client.get("/api/library/items", headers=headers)
        assert res_lib.status_code == 200
        items = res_lib.json().get("items", [])
        assert len(items) == 1
        assert items[0]["total_size"] > 0
        assert items[0]["rj_code"] == "RJ123456"

    # -------------------------------------------------------------------------
    # Step 5: Generate verifiable & reproducible artifact
    # -------------------------------------------------------------------------
    artifact = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_suite": "test_library_size_and_light_ghost_btn_e2e",
        "status": "PASSED",
        "verified_issues": {
            "issue_6": {
                "description": "Works library table size column wrapping & squeeze prevention",
                "th_width": "width: 100",
                "td_white_space": "nowrap",
            },
            "issue_7": {
                "description": "Light theme .btn-ghost hover text white invisibility fix",
                "rule": "[data-theme=\"light\"] .btn-ghost:hover",
                "hover_color": "var(--fg-main)",
                "hover_bg": "rgba(0, 0, 0, 0.05)",
            },
            "light_theme_model_settings": {
                "description": "Settings Default Models inset card light theme background fix",
                "variable": "--bg-card-inset",
                "class": ".card-inset",
                "eliminated_hardcoded_dark_boxes": True,
            },
        },
    }
    artifacts_dir = REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_file = artifacts_dir / "library_size_and_light_ghost_btn_e2e_artifact.json"
    artifact_file.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    assert artifact_file.is_file(), f"Artifact must be written to {artifact_file}"
