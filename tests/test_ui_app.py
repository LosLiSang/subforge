import asyncio
import json
import re
import shutil
import time
from dataclasses import asdict

import httpx
import pytest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from subforge.library import CreatorKind, ImportRequest, ItemKind, LibraryStore
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.picker import FakeFilePicker
from subforge.ui.profiles import LlmProfileStore
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter, ProcessingSnapshot


def _authenticated_client(tmp_path, *, audio=None, library=None, worker=None):
    settings = UiSettingsStore(tmp_path / "ui.json")
    if library:
        LibraryStore.initialize(library).close()
        settings.set_active_library(library)
    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(audio=audio, directory=library),
        profiles=LlmProfileStore(tmp_path / "profiles.json"),
        worker=worker or FakeWorkerAdapter([]),
        startup_token="startup-secret",
        open_browser=False,
        allowed_hosts={"testserver"},
    )
    client = TestClient(create_app(deps))
    response = client.get("/?token=startup-secret", follow_redirects=False)
    assert response.status_code == 303
    csrf = client.get("/api/session").json()["csrf_token"]
    headers = {"x-csrf-token": csrf, "origin": "http://testserver"}
    # 真实浏览器中页面由外壳 iframe 加载（Sec-Fetch-Dest: iframe），
    # 测试模拟 iframe 内请求以断言内页内容而非顶层外壳。
    _frame_headers = {"sec-fetch-dest": "iframe"}
    original_get = client.get

    def _get(url, **kwargs):
        kwargs.setdefault("headers", {})
        kwargs["headers"] = {**_frame_headers, **kwargs["headers"]}
        return original_get(url, **kwargs)

    client.get = _get
    return client, headers


async def test_http_remains_responsive_while_background_worker_is_running(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "busy.mp3"
    audio.write_bytes(b"audio")
    store = LibraryStore.initialize(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Busy", rj_code="RJ00000801"
    ))
    store.close()
    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(library)
    app = create_app(UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=LlmProfileStore(tmp_path / "profiles.json"),
        worker=FakeWorkerAdapter([], wait_forever=True),
        startup_token="",
        open_browser=False,
        allowed_hosts={"testserver"},
    ))
    runtime = app.state.runtime
    runtime.sessions["session"] = "csrf"
    runtime.open_active_library()
    assert runtime.tasks is not None
    await runtime.tasks.enqueue(
        imported.track_id,
        ProcessingSnapshot("local", "normal", "medium", "missing-profile"),
    )
    await asyncio.sleep(0)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
        cookies={"subforge_session": "session"},
    ) as client:
        started = time.monotonic()
        response = await client.get("/downloads", headers={"sec-fetch-dest": "iframe"})
        elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 0.5
    await runtime.close()


def test_write_request_requires_authenticated_session_csrf_and_origin(tmp_path):
    app = create_app(UiDependencies(
        settings=UiSettingsStore(tmp_path / "ui.json"),
        picker=FakeFilePicker(),
        profiles=LlmProfileStore(tmp_path / "profiles.json"),
        worker=FakeWorkerAdapter([]),
        startup_token="token",
        open_browser=False,
        allowed_hosts={"testserver"},
    ))
    client = TestClient(app)

    assert client.get("/").status_code == 401
    assert client.post("/library/select").status_code == 401
    client.get("/?token=token")
    assert client.post("/library/select").status_code == 403


def test_first_run_selects_and_initializes_library(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    # Clear the preconfigured setting to exercise the first-run route.
    UiSettingsStore(tmp_path / "ui.json").path.unlink()

    response = client.post("/library/select", headers=headers, follow_redirects=False)

    assert response.status_code == 303
    assert (library / "library.json").exists()
    assert UiSettingsStore(tmp_path / "ui.json").get_active_library() == library.resolve()


def test_import_flow_never_exposes_server_path_and_lists_waiting_item(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "secret-source" / "audio.m4a"
    audio.parent.mkdir()
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, audio=audio, library=library)

    selected = client.post("/picker/audio", headers=headers).json()
    assert "selection_id" in selected
    assert str(audio) not in str(selected)

    response = client.post("/items/import", headers=headers, data={
        "selection_id": selected["selection_id"],
        "kind": "rj_work",
        "rj_code": "RJ00000200",
        "title": "测试作品",
    }, follow_redirects=False)

    assert response.status_code == 303
    page = client.get("/")
    assert "测试作品" in page.text
    assert "status-waiting" in page.text
    assert str(audio.parent) not in page.text


def test_profiles_page_renders_list_and_dialog_layout(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    profiles = LlmProfileStore(tmp_path / "profiles.json")
    profiles.save("DeepSeek", "https://api.example/v1", "chat", "sk-test")

    response = client.get("/profiles")

    assert response.status_code == 200
    html = response.text
    # 列表 + 弹窗布局：页面头带新增按钮，配置收成紧凑行，表单在 dialog 里
    assert 'class="page-head"' in html
    assert 'data-open-dialog="profile-dialog"' in html
    assert 'id="profile-dialog"' in html
    assert "<dialog" in html
    # 每个配置一行：名称/模型/端点摘要 + 操作（测试/编辑/删除）
    assert 'data-profile-row="DeepSeek"' in html
    deepseek_row = html[html.index('data-profile-row="DeepSeek"'):html.index('</article>')]
    assert 'data-test-endpoint="/profiles/' in deepseek_row
    assert "data-edit-profile='" in deepseek_row
    assert 'data-delete-profile="/profiles/' in deepseek_row
    # 编辑表单在弹窗里，字段名不变
    assert 'name="base_url"' in html
    assert 'name="verify_tls"' in html
    assert 'name="ca_bundle"' in html
    assert 'name="profile_id"' in html


def test_profiles_page_dialog_prefills_edit_values(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    profiles = LlmProfileStore(tmp_path / "profiles.json")
    profile = profiles.save("DeepSeek", "https://api.example/v1", "chat", "sk-test")

    response = client.get("/profiles")

    html = response.text
    # 编辑按钮携带完整配置 JSON，点击后回填弹窗表单（无 Key 回填）
    import json as _json
    start = html.index("data-edit-profile='")
    end = html.index("'>编辑", start)  # 单引号属性内的双引号无需转义，直接解析
    payload = _json.loads(html[start + len("data-edit-profile='"):end])
    assert payload["profile_id"] == profile.profile_id
    assert payload["name"] == "DeepSeek"
    assert payload["base_url"] == "https://api.example/v1"
    assert payload["model"] == "chat"
    assert "api_key" not in payload or payload.get("api_key") == ""


def test_profiles_page_renders_one_row_per_profile(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    profiles = LlmProfileStore(tmp_path / "profiles.json")
    profiles.save("DeepSeek", "https://api.example/v1", "chat", "sk-test")
    profiles.save("OpenAI", "https://api.openai.com/v1", "gpt", "sk-2")

    response = client.get("/profiles")

    html = response.text
    assert 'data-profile-row="DeepSeek"' in html
    assert 'data-profile-row="OpenAI"' in html
    # 每行独立包含自己的测试/编辑/删除，且不泄漏 Key
    deepseek_start = html.index('data-profile-row="DeepSeek"')
    openai_start = html.index('data-profile-row="OpenAI"')
    first_chunk, second_chunk = sorted([deepseek_start, openai_start])
    first, second = html[first_chunk:second_chunk], html[second_chunk:]
    for chunk in (first, second):
        assert chunk.count('data-test-endpoint') == 1
        assert chunk.count('data-delete-profile') == 1
        assert chunk.count('data-edit-profile=') == 1
    assert "sk-test" not in html and "sk-2" not in html


def test_profile_connection_test_reports_success_without_exposing_key(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    profiles = LlmProfileStore(tmp_path / "profiles.json")
    profile = profiles.save("Local", "http://127.0.0.1:1234/v1", "model", "secret-key-value")

    with patch("subforge.ui.app.test_profile_connection", return_value=(True, "连接成功")):
        response = client.post(f"/profiles/{profile.profile_id}/test", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "连接成功"}
    assert "secret-key-value" not in response.text


def test_settings_page_renders_dashboard_sections(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    response = client.get("/settings")

    assert response.status_code == 200
    html = response.text
    # Tab 布局：顶部 Tab 导航 + 每个分区仍保留原有全部控件（功能行为不变）
    assert 'class="page-head"' in html
    assert 'class="tab-bar"' in html
    assert 'data-tab="models"' in html
    assert 'data-tab="network"' in html
    assert 'data-tab="concurrency"' in html
    assert html.count("dash-section") >= 3
    assert html.count("data-pick-directory") == 3
    assert html.count("data-test-endpoint") == 2


def test_settings_model_check_reports_cached_and_uncached_models(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    with patch("subforge.ui.app.check_model_configuration", return_value=(True, "模型已缓存")):
        response = client.post("/settings/models/medium/check", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "模型已缓存"}

    response = client.post("/settings/models/unknown/check", headers=headers)
    assert response.status_code == 404


def test_profile_key_can_only_be_deleted_by_explicit_action(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    profiles = LlmProfileStore(tmp_path / "profiles.json")
    profile = profiles.save("DeepSeek", "https://api.example/v1", "chat", "sk-secret-value-1234")

    response = client.post(f"/profiles/{profile.profile_id}/delete-key", headers=headers)

    assert response.status_code == 200
    assert profiles.resolve(profile.profile_id).api_key == ""


def test_deepgram_key_can_only_be_deleted_by_explicit_action(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_deepgram_api_key("dg-secret-value-1234")
    page = client.get("/settings").text
    assert "data-delete-deepgram" in page
    assert "删除 Deepgram Key" not in page

    response = client.post("/settings/deepgram/delete-key", headers=headers)

    assert response.status_code == 200
    assert settings.get_deepgram_api_key() == ""


def test_failed_task_page_shows_actionable_error(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, audio=audio, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000201"
    ))
    store.close()
    client.get("/")
    runtime = client.app.state.runtime
    with runtime.library._db_lock, runtime.library._db:
        runtime.library._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,message,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            ("failed-task", imported.track_id, "failed", "asr", 0, "Model download timed out", "{}", "now"),
        )

    page = client.get(f"/items/{imported.item_id}")

    assert "Model download timed out" in page.text
    assert "任务失败" in page.text


def test_profile_page_masks_secret(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    client.post("/profiles", headers=headers, data={
        "name": "DeepSeek",
        "base_url": "https://api.example/v1",
        "model": "chat",
        "api_key": "sk-secret-value-1234",
    })
    page = client.get("/profiles")

    assert "sk-s" in page.text
    assert "1234" in page.text
    assert "sk-secret-value-1234" not in page.text


def test_delete_profile_endpoint_removes_profile(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    profiles = LlmProfileStore(tmp_path / "profiles.json")
    profile = profiles.save("DeepSeek", "https://api.example/v1", "chat", "sk-test")

    response = client.post(f"/profiles/{profile.profile_id}/delete", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert profiles.list_public() == []

    missing = client.post("/profiles/nonexistent/delete", headers=headers)
    assert missing.status_code == 404


def test_index_renders_work_card_grid_like_asmr_one(tmp_path):
    """index 页：作品卡片网格（封面占位 + 标题 + 作者/RJ 徽章 + 状态徽章）。"""
    library = tmp_path / "Library"
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, audio=audio, library=library)
    store = LibraryStore.open(library)
    store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="测试作品", rj_code="RJ00000201",
    ))
    store.close()

    page = client.get("/")
    html = page.text
    assert 'class="works-grid"' in html
    assert 'class="work-card' in html
    assert "RJ00000201" in html          # RJ 徽章
    assert "测试作品" in html
    assert "RJ00000201" in html          # 作者/RJ 徽章
    # 保留原功能 hooks：导入按钮、类型/标题/RJ 字段、重新扫描
    assert 'id="pick-audio"' in html
    assert 'name="kind"' in html
    assert 'name="title"' in html
    assert 'name="rj_code"' in html
    assert '/library/rescan' in html
    assert 'class="library-toolbar"' in html
    assert 'class="works-search"' in html
    assert 'class="library-menu"' in html
    assert '/library/rescan' in html
    css = (Path(__file__).parents[1] / "subforge" / "ui" / "static" / "app.css").read_text(encoding="utf-8")
    assert '.library-toolbar .works-actions>button{height:34px}' in css
    assert '.library-toolbar .creator-picker-control{height:34px;min-height:34px' in css


def test_rj_work_card_shows_total_item_directory_size(tmp_path):
    library = tmp_path / "Library"
    one = tmp_path / "one.mp3"
    two = tmp_path / "two.mp3"
    one.write_bytes(b"a" * 1048576)
    two.write_bytes(b"b" * 2097152)
    client, _headers = _authenticated_client(tmp_path, library=library)
    store = LibraryStore.open(library)
    first = store.import_audio(ImportRequest(
        source=one, kind=ItemKind.RJ_WORK, title="Size work", rj_code="RJ00000202",
    ))
    store.import_audio(ImportRequest(
        source=two, kind=ItemKind.RJ_WORK, title="Size work", rj_code="RJ00000202",
    ))
    item = store.get_item(first.item_id)
    item_dir = store.item_directory(item.item_id)
    expected = f"{round(sum(path.stat().st_size for path in item_dir.rglob('*') if path.is_file()) / 1048576, 1)} MB"
    store.close()

    page = client.get("/")

    assert expected in page.text


def test_detail_renders_track_rows_with_status_badges(tmp_path):
    """detail 页：封面头 + 音轨行（文件名/状态徽章/大小/播放链接）。"""
    library = tmp_path / "Library"
    audio = tmp_path / "b.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, audio=audio, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.STREAM_ARCHIVE, title="直播作品", author="miyadi",
    ))
    item_id = imported.item_id
    store.track_subtitle_path(imported.track_id, "ja").write_text(
        "1\n00:00:00,000 --> 00:01:02,000\ntext\n", encoding="utf-8"
    )
    store.close()

    page = client.get(f"/items/{item_id}")
    html = page.text
    assert 'class="work-hero"' in html
    assert "直播作品" in html
    assert "miyadi" in html
    assert 'class="track-row' in html
    assert "b.mp3" in html
    assert 'class="track-menu"' in html
    assert f'data-track-duration="/tracks/{imported.track_id}/media">1:02' in html
    assert f'action="/items/{item_id}/process"' in html
    assert 'data-process-incomplete-form' in html
    assert '>处理全部未完成音轨</button>' in html
    assert 'data-title="处理全部未完成音轨"' in html
    assert '>处理设置…</button>' in html
    assert f'action="/tracks/{imported.track_id}/rename"' in html
    assert f'action="/tracks/{imported.track_id}/delete"' in html
    assert f'data-track-player="/tracks/{imported.track_id}/play"' in html
    assert f'data-item-id="{item_id}"' in html
    assert f'data-action="/tracks/{imported.track_id}/process"' in html
    # 处理表单字段与端点全部保留，并集中到 Dialog。
    assert 'id="processing-dialog"' in html
    assert 'name="asr_provider"' in html
    assert 'name="scene"' in html
    assert 'name="whisper_model"' in html
    assert 'name="llm_profile_id"' in html
    assert 'name="mode"' in html
    assert "/process" in html
    # 媒体播放与字幕处理状态解耦：waiting Track 也能播放。
    assert f'data-play-track="/tracks/{imported.track_id}/play"' in html
    assert f'href="/tracks/{imported.track_id}/play"' in html


def test_detail_renders_enriched_overview_summary(tmp_path):
    """detail 页：概览汇总卡片（音轨数/总时长/总大小/状态计数/创建更新时间/目录）。"""
    library = tmp_path / "Library"
    one = tmp_path / "one.mp3"
    two = tmp_path / "two.mp3"
    one.write_bytes(b"x" * (3 * 1024 * 1024))
    two.write_bytes(b"y" * (2 * 1024 * 1024))
    client, headers = _authenticated_client(tmp_path, library=library)
    store = LibraryStore.open(library)
    first = store.import_audio(ImportRequest(
        source=one, kind=ItemKind.RJ_WORK, title="RJ 作品", rj_code="RJ00000801",
    ))
    second = store.import_audio(ImportRequest(
        source=two, kind=ItemKind.RJ_WORK, title="RJ 作品", rj_code="RJ00000801",
    ))
    assert first.item_id == second.item_id  # 同一 RJ 号合并为同一作品
    store.track_subtitle_path(first.track_id, "ja").write_text(
        "1\n00:00:00,000 --> 00:01:02,000\ntext\n", encoding="utf-8"
    )
    store.update_track_status(first.track_id, "playable")
    store.update_track_status(second.track_id, "no_speech")
    store.close()

    page = client.get(f"/items/{first.item_id}").text
    assert 'class="item-overview"' in page
    assert 'class="stat-label">音轨' in page
    assert 'class="stat-label">总时长' in page
    assert ">1:02" in page
    assert 'class="stat-label">总大小' in page
    assert ">5.0" in page
    assert 'class="stat-label">可播放' in page
    assert 'class="stat-label">无语音' in page
    assert 'class="status-bars"' in page
    assert 'class="item-facts"' in page
    assert "创建" in page and "更新" in page
    assert "works/RJ00000801" in page  # 所在目录
    assert 'class="track-subs"' in page
    assert 'class="chip sub-ok"' in page


def test_detail_renders_last_config_and_dlsite_link(tmp_path):
    """detail 页：上次处理配置摘要 + RJ 号 DLsite 链接 + 作者。"""
    LlmProfileStore(tmp_path / "profiles.json").save(
        name="测试配置", base_url="https://api.deepseek.com/v1", model="deepseek-chat",
        profile_id="p1",
    )
    library = tmp_path / "Library"
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"audio")
    client, _ = _authenticated_client(tmp_path, audio=audio, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="某作品", rj_code="RJ01546796", author="社团A",
    ))
    item_id = imported.item_id
    store.close()
    # 首次访问会触发 open_active_library 新建 TaskManager（启动期 cleanup 已执行）。
    client.get(f"/items/{item_id}")
    # 此后插入的已完成任务（含 config）不会被再次清理。
    store = LibraryStore.open(library)
    with store._db:
        store._db.execute(
            "INSERT OR REPLACE INTO tasks (task_id,track_id,status,stage,progress,completed,total,message,config_snapshot,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("task1", imported.track_id, "completed", "complete", 1.0, 5, 5, None,
             json.dumps({"asr_provider": "local", "scene": "asmr",
                         "whisper_model": "large-v3", "llm_profile_id": "p1"}),
             "2026-08-23T00:00:00Z"),
        )
    store.close()

    page = client.get(f"/items/{item_id}").text
    assert 'class="item-config"' in page
    config = re.search(r'class="item-config".*?</section>', page, re.S)
    assert config, "缺少上次处理配置摘要段"
    assert "本地" in config.group(0)
    assert "large-v3" in config.group(0)
    assert "测试配置" in config.group(0)
    assert "deepseek-chat" in config.group(0)
    assert "https://www.dlsite.com/maniax/work/=/product_id/RJ01546796" in page
    assert "社团A" in page


def test_process_item_enqueues_every_incomplete_track(tmp_path):
    library = tmp_path / "Library"
    one = tmp_path / "one.mp3"
    two = tmp_path / "two.mp3"
    complete = tmp_path / "complete.mp3"
    one.write_bytes(b"one")
    two.write_bytes(b"two")
    complete.write_bytes(b"complete")
    client, headers = _authenticated_client(
        tmp_path, library=library,
        worker=FakeWorkerAdapter([{"type": "task_completed", "stage": "complete"}]),
    )
    store = LibraryStore.open(library)
    first = store.import_audio(ImportRequest(
        source=one, kind=ItemKind.RJ_WORK, title="Batch", rj_code="RJ00000802"
    ))
    second = store.import_audio(ImportRequest(
        source=two, kind=ItemKind.RJ_WORK, title="Batch", rj_code="RJ00000802"
    ))
    completed = store.import_audio(ImportRequest(
        source=complete, kind=ItemKind.RJ_WORK, title="Batch", rj_code="RJ00000802"
    ))
    store.update_track_status(completed.track_id, "playable")
    store.close()
    profile = LlmProfileStore(tmp_path / "profiles.json").save(
        name="Test", base_url="https://example.com/v1", model="chat", api_key="key"
    )

    response = client.post(
        f"/items/{first.item_id}/process",
        headers=headers,
        data={
            "asr_provider": "local", "scene": "asmr", "whisper_model": "medium",
            "llm_profile_id": profile.profile_id, "mode": "from_scratch",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    tasks = client.app.state.runtime.tasks
    assert tasks.latest_for_track(first.track_id) is not None
    assert tasks.latest_for_track(second.track_id) is not None
    assert tasks.latest_for_track(completed.track_id) is None


def test_track_rename_delete_and_subtitle_download_routes(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "old.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Track ops", rj_code="RJ00000803"
    ))
    store.track_subtitle_path(imported.track_id, "ja").write_text("subtitle", encoding="utf-8")
    store.close()

    download = client.get(f"/tracks/{imported.track_id}/subtitles/ja/download")
    assert download.status_code == 200
    assert download.content == b"subtitle"
    assert "attachment" in download.headers["content-disposition"]

    renamed = client.post(
        f"/tracks/{imported.track_id}/rename", headers=headers,
        data={"filename": "renamed.mp3"}, follow_redirects=False,
    )
    assert renamed.status_code == 303
    reopened = LibraryStore.open(library)
    assert reopened.track_media_path(imported.track_id).name == "renamed.mp3"
    assert reopened.track_subtitle_path(imported.track_id, "ja").exists()
    reopened.close()

    deleted = client.post(
        f"/tracks/{imported.track_id}/delete", headers=headers, follow_redirects=False,
    )
    assert deleted.status_code == 303
    reopened = LibraryStore.open(library)
    with pytest.raises(KeyError):
        reopened.get_track(imported.track_id)
    reopened.close()


def test_track_row_click_opens_player_and_menu_buttons_do_not_navigate(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "nav.mp3"
    audio.write_bytes(b"audio")
    client, _headers = _authenticated_client(tmp_path, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.STREAM_ARCHIVE, title="Nav work", author="miyadi",
    ))
    store.close()

    page = client.get(f"/items/{imported.item_id}")

    assert f'data-track-player="/tracks/{imported.track_id}/play"' in page.text
    script = (Path(__file__).parents[1] / "subforge" / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "data-track-player" in script
    assert "stopPropagation" in script


def test_single_track_can_be_reprocessed_directly(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "single.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(
        tmp_path, library=library,
        worker=FakeWorkerAdapter([{"type": "task_completed", "stage": "complete"}]),
    )
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Single", rj_code="RJ00000804",
    ))
    store.update_track_status(imported.track_id, "failed")
    store.close()
    profile = LlmProfileStore(tmp_path / "profiles.json").save(
        name="Test", base_url="https://example.com/v1", model="chat", api_key="key"
    )

    response = client.post(
        f"/tracks/{imported.track_id}/process",
        headers=headers,
        data={
            "asr_provider": "local", "scene": "asmr", "whisper_model": "medium",
            "llm_profile_id": profile.profile_id, "mode": "from_scratch",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    task = client.app.state.runtime.tasks.latest_for_track(imported.track_id)
    assert task is not None


def test_cover_route_returns_extracted_image(tmp_path):
    """作品页路由 /covers/{item_id}：带内嵌封面时返回 JPEG，无封面 404。"""
    import shutil
    import subprocess as sp
    if shutil.which("ffmpeg") is None:
        import pytest
        pytest.skip("ffmpeg not available")

    # 生成带 attached pic 封面的 m4a
    from pathlib import Path as _P
    media = tmp_path / "cover.m4a"
    sp.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "anullsrc=r=16000:cl=mono:d=1",
         "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1",
         "-map", "0:a", "-map", "1:v", "-c:a", "aac", "-c:v", "mjpeg",
         "-disposition:v:0", "attached_pic", "-shortest", str(media)],
        check=True, capture_output=True,
    )

    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, audio=media, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=media, kind=ItemKind.STREAM_ARCHIVE, title="带封面作品", author="miyadi",
    ))
    store.close()

    # 首页卡片引用 /covers/{item_id}
    page = client.get("/")
    assert f"/covers/{imported.item_id}" in page.text

    # 封面端点返回 JPEG
    cover = client.get(f"/covers/{imported.item_id}")
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/jpeg"
    assert cover.content[:2] == b"\xff\xd8"  # JPEG magic
    assert len(cover.content) > 100

    # 缓存已写入
    assert (library / ".subforge" / "covers" / f"{imported.item_id}.jpg").exists()

    # 无封面作品 → 404
    no_cover = tmp_path / "plain.mp3"
    no_cover.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00not really audio")
    no_cover_item = _import_audio(tmp_path, library, no_cover)
    assert client.get(f"/covers/{no_cover_item}").status_code == 404


def _import_audio(tmp_path, library, media) -> str:
    client, headers = _authenticated_client(tmp_path, audio=media, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=media, kind=ItemKind.STREAM_ARCHIVE, title=media.stem, author="x",
    ))
    store.close()
    return imported.item_id


def test_stats_page_reports_library_counts(tmp_path):
    """统计页：真实库聚合数据（作品/音轨/状态分布）。"""
    library = tmp_path / "Library"
    audio = tmp_path / "s.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, audio=audio, library=library)
    store = LibraryStore.open(library)
    store.import_audio(ImportRequest(source=audio, kind=ItemKind.RJ_WORK, title="A", rj_code="RJ1"))
    store.close()

    page = client.get("/stats").text
    assert "统计" in page
    assert "作品" in page
    assert "音轨" in page


def test_task_statuses_are_returned_by_one_batch_request(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "batch-status.mp3"
    audio.write_bytes(b"audio")
    client, _headers = _authenticated_client(tmp_path, library=library)
    client.get("/")
    store = client.app.state.runtime.library
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Batch status", rj_code="RJ00000406",
    ))
    with store._db_lock, store._db:
        for task_id, status, stage in (("one", "queued", "queue"), ("two", "running", "translation")):
            store._db.execute(
                """INSERT INTO tasks(task_id,track_id,status,stage,progress,config_snapshot,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (task_id, imported.track_id, status, stage, 0.25, "{}", "now"),
            )

    response = client.get("/api/tasks/status?task_id=one&task_id=two")

    assert response.status_code == 200
    assert [(row["task_id"], row["status"]) for row in response.json()] == [
        ("one", "queued"), ("two", "running"),
    ]


def test_frontend_uses_one_batch_poll_instead_of_per_task_sse():
    script = (Path(__file__).parents[1] / "subforge" / "ui" / "static" / "app.js").read_text(encoding="utf-8")

    assert "new EventSource" not in script
    assert "/api/tasks/status?" in script


def test_task_center_shows_processing_and_download_status(tmp_path):
    """任务中心统一展示字幕处理状态与模型下载配置。"""
    library = tmp_path / "Library"
    audio = tmp_path / "task.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, library=library)
    client.get("/")  # 建立当前会话的 TaskManager，再注入一个可观察的运行中任务。
    store = client.app.state.runtime.library
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Task work", rj_code="RJ00000405",
    ))
    with store._db_lock, store._db:
        store._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,completed,total,message,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("visible-task", imported.track_id, "running", "translation", 0.5, 1, 2,
             "等待重试 · HTTP 429 · 请求 1/3 · 2秒后重试", "{}", "now"),
        )

    page = client.get("/downloads").text
    assert "任务中心" in page
    assert 'class="tab-bar task-center-tabs"' in page
    assert 'data-tab="downloads"' in page
    assert 'data-tab="subtitles"' in page
    assert 'data-tab="models"' in page
    assert "Task work" in page
    assert "translation" in page
    assert "HTTP 429" in page
    assert "1 / 2" in page
    assert "模型" in page


def test_task_center_shows_retry_for_failed_subtitle_and_download(tmp_path):
    """任务中心：失败的字幕任务与报错的 URL 下载任务都显示重试按钮。"""
    library = tmp_path / "Library"
    audio = tmp_path / "t.mp3"
    audio.write_bytes(b"audio")
    client, _headers = _authenticated_client(tmp_path, library=library)
    client.get("/")  # 建立 TaskManager
    store = client.app.state.runtime.library
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Retry work", rj_code="RJ00000405",
    ))
    with store._db_lock, store._db:
        store._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,completed,total,message,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?) """,
            ("failed-task", imported.track_id, "failed", "translation", 0.2, 0, 5,
             "HTTP 500", json.dumps({"asr_provider": "local", "scene": "normal",
                                     "whisper_model": "medium", "llm_profile_id": "p1"}),
             "now"),
        )
    runtime = client.app.state.runtime
    runtime.imports["dl-fail"] = {
        "task_id": "dl-fail", "kind": "download", "status": "error",
        "stage": "download", "message": "yt-dlp 下载失败：404", "item_id": None,
        "source_url": "https://example.com/video", "item_kind": "stream_archive",
    }
    page = client.get("/downloads").text
    assert "/tasks/failed-task/retry" in page
    assert "/api/imports/dl-fail/retry" in page
    # 未失败的下载任务不显示重试
    runtime.imports["dl-ok"] = {
        "task_id": "dl-ok", "kind": "download", "status": "done",
        "stage": "complete", "message": "导入完成", "item_id": "x",
        "source_url": "https://example.com/ok", "item_kind": "stream_archive",
    }
    page2 = client.get("/downloads").text
    assert "/api/imports/dl-ok/retry" not in page2


def test_retry_failed_subtitle_task_re_enqueues(tmp_path):
    """POST /tasks/{id}/retry：为失败字幕任务复用配置快照重新排队。"""
    library = tmp_path / "Library"
    audio = tmp_path / "t.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, library=library)
    client.get("/")
    runtime = client.app.state.runtime
    store = runtime.library
    profile = runtime.deps.profiles.save("p", "https://api.example.com", "model", api_key="k")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Retry", rj_code="RJ00000405",
    ))
    snapshot = ProcessingSnapshot("local", "normal", "medium", profile.profile_id)
    with store._db_lock, store._db:
        store._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,completed,total,message,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?) """,
            ("fail-1", imported.track_id, "failed", "translation", 0.3, 1, 5, "HTTP 500",
             json.dumps(asdict(snapshot)), "2020-01-01T00:00:00Z"),
        )
    resp = client.post("/tasks/fail-1/retry", headers=headers, follow_redirects=False)
    assert resp.status_code == 303
    # 重试后为新任务复用同一配置快照重新排队
    latest = runtime.tasks.latest_for_track(imported.track_id)
    assert latest is not None
    assert latest.task_id != "fail-1"
    assert latest.config_snapshot == asdict(snapshot)


def test_retry_rejects_non_failed_subtitle_task(tmp_path):
    """正在运行/已完成的任务不允许重试。"""
    library = tmp_path / "Library"
    audio = tmp_path / "t.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, library=library)
    client.get("/")
    store = client.app.state.runtime.library
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Retry", rj_code="RJ00000405",
    ))
    with store._db_lock, store._db:
        store._db.execute(
            """INSERT INTO tasks(task_id,track_id,status,stage,progress,completed,total,message,config_snapshot,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?) """,
            ("run-1", imported.track_id, "running", "translation", 0.3, 1, 5, "...",
             json.dumps({"asr_provider": "local", "scene": "normal",
                         "whisper_model": "medium", "llm_profile_id": "p1"}), "now"),
        )
    resp = client.post("/tasks/run-1/retry", headers=headers)
    assert resp.status_code == 409


def test_retry_failed_url_download(tmp_path):
    """POST /api/imports/{id}/retry：报错 URL 下载任务重新执行 yt-dlp 并入库。"""
    import subprocess as sp
    import tempfile as _tf
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    runtime = client.app.state.runtime
    task_id = "dl-fail-retry"
    runtime.imports[task_id] = {
        "task_id": task_id, "kind": "download", "status": "error",
        "stage": "download", "message": "yt-dlp 失败", "item_id": None,
        "source_url": "https://example.com/v", "item_kind": "stream_archive",
        "rj_code": None, "title": "重试下载", "author": "作者", "creator_ids": [],
    }
    fake_audio = tmp_path / "r.m4a"
    fake_audio.write_bytes(b"\x00" * 2048)
    real_mkdtemp = _tf.mkdtemp

    def fake_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        shutil.copy(str(fake_audio), str(Path(d) / "a.m4a"))
        return d

    def fake_run(cmd, **kwargs):
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    import subforge.ui.app as app_mod
    with (
        patch.object(app_mod.shutil, "which", lambda n: "yt-dlp" if n == "yt-dlp" else app_mod.shutil.which(n)),
        patch.object(_tf, "mkdtemp", fake_mkdtemp),
        patch.object(sp, "run", fake_run),
    ):
        resp = client.post(f"/api/imports/{task_id}/retry", headers=headers, follow_redirects=False)
        assert resp.status_code == 303
        import time as _time
        deadline = _time.time() + 10
        st = None
        while _time.time() < deadline:
            st = client.get(f"/api/imports/{task_id}").json()
            if st.get("status") == "done":
                break
            _time.sleep(0.2)
        assert st is not None and st.get("status") == "done", st
    items = LibraryStore.open(library).list_items()
    assert any(it.title == "重试下载" for it in items)


def test_item_metadata_can_be_edited_with_existing_creators(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "edit.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, audio=audio, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Old", rj_code="RJ00000400",
    ))
    circle = store.create_creator("Circle", CreatorKind.CIRCLE)
    actor = store.create_creator("Actor", CreatorKind.VOICE_ACTOR)
    store.close()

    detail = client.get(f"/items/{imported.item_id}")
    assert 'action="/items/' in detail.text
    assert 'id="work-edit-dialog"' in detail.text
    assert "data-open-work-edit" in detail.text
    assert "data-pick-work-cover" in detail.text
    assert 'name="creator_ids"' in detail.text
    assert 'data-creator-create-dialog' in detail.text
    assert "Circle" in detail.text and "Actor" in detail.text

    from urllib.parse import urlencode
    response = client.post(
        f"/items/{imported.item_id}/edit",
        headers={**headers, "content-type": "application/x-www-form-urlencoded"},
        content=urlencode([
            ("title", "New title"),
            ("kind", "rj_work"),
            ("rj_code", "RJ00000401"),
            ("creator_ids", circle.creator_id),
            ("creator_ids", actor.creator_id),
        ]),
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = LibraryStore.open(library).get_item(imported.item_id)
    assert updated.title == "New title"
    assert updated.rj_code == "RJ00000401"
    assert updated.creator_ids == [circle.creator_id, actor.creator_id]


def test_creator_filter_and_statistics_use_creator_relations(tmp_path):
    library = tmp_path / "Library"
    first_audio = tmp_path / "one.mp3"
    second_audio = tmp_path / "two.mp3"
    first_audio.write_bytes(b"one")
    second_audio.write_bytes(b"two")
    client, headers = _authenticated_client(tmp_path, library=library)
    store = LibraryStore.open(library)
    circle = store.create_creator("Circle", CreatorKind.CIRCLE)
    actor = store.create_creator("Actor", CreatorKind.VOICE_ACTOR)
    first = store.import_audio(ImportRequest(
        source=first_audio, kind=ItemKind.RJ_WORK, title="Together", rj_code="RJ00000402",
    ))
    second = store.import_audio(ImportRequest(
        source=second_audio, kind=ItemKind.RJ_WORK, title="Circle only", rj_code="RJ00000403",
    ))
    store.update_item(first.item_id, title="Together", kind=ItemKind.RJ_WORK,
                      rj_code="RJ00000402", creator_ids=[circle.creator_id, actor.creator_id])
    store.update_item(second.item_id, title="Circle only", kind=ItemKind.RJ_WORK,
                      rj_code="RJ00000403", creator_ids=[circle.creator_id])
    store.close()

    filtered = client.get(f"/?creator={circle.creator_id}&creator={actor.creator_id}").text
    assert 'class="library-toolbar"' in filtered
    assert 'class="creator-filter"' in filtered
    assert 'class="works-search"' in filtered
    assert "Together" in filtered
    assert "Circle only" not in filtered

    stats = client.get("/stats").text
    assert "Circle" in stats and "Actor" in stats
    assert f"creator={circle.creator_id}" in stats


def test_url_source_is_visible_on_item_detail(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"audio")
    client, headers = _authenticated_client(tmp_path, library=library)
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio,
        kind=ItemKind.STREAM_ARCHIVE,
        title="Source item",
        author="Actor",
        source_url="https://example.com/original-video",
    ))
    store.close()

    detail = client.get(f"/items/{imported.item_id}").text
    assert "https://example.com/original-video" in detail
    assert "原始来源" in detail


def test_quick_creator_api_returns_a_tag_ready_creator(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    response = client.post("/api/creators", headers=headers, data={
        "name": "Miyadi", "kind": "voice_actor",
    })

    assert response.status_code == 201
    assert response.json()["name"] == "Miyadi"
    assert response.json()["kind"] == "voice_actor"
    assert LibraryStore.open(library).list_creators()[0].name == "Miyadi"


def test_creator_management_can_create_rename_merge_and_delete(tmp_path):
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    created = client.post("/creators", headers=headers, data={
        "action": "create", "name": "Circle A", "kind": "circle",
    }, follow_redirects=False)
    assert created.status_code == 303
    store = LibraryStore.open(library)
    creator = store.list_creators()[0]
    store.close()

    renamed = client.post("/creators", headers=headers, data={
        "action": "rename", "creator_id": creator.creator_id, "name": "Circle B",
    }, follow_redirects=False)
    assert renamed.status_code == 303
    creator_page = client.get("/creators").text
    assert "Circle B" in creator_page
    assert 'class="tab-bar creator-tabs"' in creator_page
    assert "data-creator-menu-button" in creator_page
    assert 'id="creator-edit-dialog"' in creator_page
    assert 'id="creator-merge-dialog"' in creator_page
    assert 'id="creator-delete-dialog"' in creator_page

    deleted = client.post("/creators", headers=headers, data={
        "action": "delete", "creator_id": creator.creator_id,
    }, follow_redirects=False)
    assert deleted.status_code == 303
    assert LibraryStore.open(library).list_creators() == []


def test_item_cover_can_be_replaced_from_image_picker(tmp_path):
    library = tmp_path / "Library"
    audio = tmp_path / "cover-source.mp3"
    audio.write_bytes(b"audio")
    image = tmp_path / "manual.jpg"
    image.write_bytes(b"\xff\xd8manual-cover")
    client, headers = _authenticated_client(tmp_path, audio=audio, library=library)
    client.app.state.runtime.deps.picker.image = image
    store = LibraryStore.open(library)
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Cover", rj_code="RJ00000404",
    ))
    store.close()

    selected = client.post("/picker/image", headers=headers).json()
    preview = client.get(f"/api/selections/{selected['selection_id']}/image")
    assert preview.status_code == 200
    assert preview.content == image.read_bytes()
    response = client.post(
        f"/items/{imported.item_id}/edit",
        headers=headers,
        data={
            "title": "Cover updated", "kind": "rj_work", "rj_code": "RJ00000404",
            "selection_id": selected["selection_id"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert (library / ".subforge" / "covers" / f"{imported.item_id}.jpg").read_bytes() == image.read_bytes()
    saved_item = LibraryStore.open(library).get_item(imported.item_id)
    assert saved_item.cover_source == "manual_upload"
    assert saved_item.title == "Cover updated"


def test_about_page_reports_version(tmp_path):
    """关于页：版本号与仓库链接。"""
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    page = client.get("/about").text
    assert "0.5.0" in page
    assert "github.com" in page


def test_shell_sidebar_contains_all_nav_entries(tmp_path):
    """顶层外壳：侧边导航含全部入口（含新页），内容在 iframe。"""
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    shell = client.get("/", headers={"sec-fetch-dest": "document"}).text
    assert 'class="sidebar"' in shell
    for entry in ("作品库", "翻译配置", "创作者", "设置", "统计", "任务中心", "关于"):
        assert entry in shell
    assert 'id="content-frame"' in shell


def test_import_dialog_has_media_tabs_without_the_old_selector(tmp_path):
    """导入 Dialog 使用无动画横向 Tab：本地、链接、RJ 文件夹。"""
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    page = client.get("/").text
    assert 'id="import-dialog"' in page
    assert 'data-import-select' not in page
    assert 'data-import-tab="local"' in page
    assert 'data-import-tab="url"' in page
    assert 'data-import-tab="folder"' in page
    assert 'data-pick-import-file' in page
    assert 'data-pick-media-folder' in page
    assert 'id="folder-import-preview"' in page
    assert 'name="url"' in page
    assert 'id="pick-audio"' in page


def test_rj_folder_preview_and_background_import(tmp_path):
    import time
    library = tmp_path / "Library"
    folder = tmp_path / "RJ01499022"
    (folder / "本篇").mkdir(parents=True)
    (folder / "本篇" / "01.m4a").write_bytes(b"one")
    (folder / "readme.txt").write_text("skip", encoding="utf-8")
    client, headers = _authenticated_client(tmp_path, library=library)
    client.app.state.runtime.deps.picker.media_folder = folder

    selected = client.post("/picker/media-folder", headers=headers).json()
    preview = client.post("/api/import-folders/preview", headers=headers, data={
        "selection_id": selected["selection_id"],
    })
    assert preview.status_code == 200
    assert preview.json()["audio_count"] == 1
    assert preview.json()["skipped_count"] == 1

    started = client.post("/items/import-folder", headers=headers, data={
        "selection_id": selected["selection_id"], "rj_code": "rj01499022", "title": "",
    })
    assert started.status_code == 202
    task_id = started.json()["task_id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        status = client.get(f"/api/imports/{task_id}").json()
        if status["status"] != "running":
            break
        time.sleep(0.02)
    assert status["status"] == "done"
    assert status["imported"] == 1
    item = LibraryStore.open(library).list_items()[0]
    assert item.title == "RJ01499022"
    assert item.tracks[0].original_relative_path == "本篇/01.m4a"


def test_import_url_rejects_missing_url(tmp_path):
    """import-url 端点：无 URL / 无授权返回错误。"""
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    resp = client.post("/items/import-url", headers=headers, data={"url": ""})
    assert resp.status_code == 400
    # 未授权
    client2 = TestClient(create_app(UiDependencies(
        settings=UiSettingsStore(tmp_path / "ui2.json"),
        picker=FakeFilePicker(), profiles=LlmProfileStore(tmp_path / "p.json"),
        worker=FakeWorkerAdapter([]), startup_token="t2", open_browser=False,
        allowed_hosts={"testserver"},
    )))
    assert client2.post("/items/import-url", data={"url": "https://youtu.be/x"}).status_code == 401


def test_import_url_downloads_and_imports(tmp_path, monkeypatch):
    """import-url：mock yt-dlp 下载产物 → 入库成功。"""
    import subprocess as sp
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    fake_audio = tmp_path / "downloaded.m4a"
    fake_audio.write_bytes(b"\x00" * 2048)

    def fake_run(cmd, **kwargs):
        # 模拟 yt-dlp：把 fake_audio 复制到输出目录
        out = Path([a for a in cmd if str(a).startswith(str(tmp_path))][0] if any(str(a).startswith(str(tmp_path)) for a in cmd) else "")
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    # 直接调用 helper 验证：yt-dlp 输出目录里放一个 m4a
    from subforge.ui.app import _download_and_import
    import shutil
    monkeypatch.setattr("shutil.which", lambda name: "yt-dlp" if name == "yt-dlp" else shutil.which(name))
    # 用真实 temp dir 模拟：替换 mkdtemp 返回可控目录
    import tempfile
    real_mkdtemp = tempfile.mkdtemp
    captured = {}
    def fake_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        shutil.copy(fake_audio, Path(d) / "video.m4a")
        captured["dir"] = d
        return d
    monkeypatch.setattr("tempfile.mkdtemp", fake_mkdtemp)

    store = LibraryStore.open(library)
    result = _download_and_import(
        store, "https://www.youtube.com/watch?v=test",
        kind=ItemKind.STREAM_ARCHIVE, rj_code=None, title="下载作品", author="测试",
    )
    store.close()
    assert result.created is True
    items = LibraryStore.open(library).list_items()
    assert any(it.title == "下载作品" for it in items)


def test_import_url_returns_accepted_async(tmp_path):
    """import-url 异步：立即 202 返回，不阻塞等下载；后台任务最终完成并入库。"""
    import subprocess as sp
    import tempfile as _tf
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    fake_audio = tmp_path / "dl.m4a"
    fake_audio.write_bytes(b"\x00" * 2048)
    fake_thumb = tmp_path / "dl.jpg"
    fake_thumb.write_bytes(b"\xff\xd8fakejpeg")

    real_mkdtemp = _tf.mkdtemp

    def fake_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        shutil.copy(str(fake_audio), str(Path(d) / "视频.m4a"))
        shutil.copy(str(fake_thumb), str(Path(d) / "视频.jpg"))
        return d

    def fake_run(cmd, **kwargs):
        # 模拟 yt-dlp：直接成功
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    import subforge.ui.app as app_mod
    from unittest.mock import patch
    with (
        patch.object(app_mod.shutil, "which", lambda n: "yt-dlp" if n == "yt-dlp" else app_mod.shutil.which(n)),
        patch.object(_tf, "mkdtemp", fake_mkdtemp),
        patch.object(sp, "run", fake_run),
    ):
        resp = client.post("/items/import-url", headers=headers, data={
            "url": "https://www.bilibili.com/video/BV1x", "kind": "stream_archive",
            "title": "异步作品", "author": "作者",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        # 后台任务在 patch 上下文中运行：等待完成
        import time
        deadline = time.time() + 10
        while time.time() < deadline:
            status = client.get(f"/api/imports/{data['task_id']}").json()
            if status.get("status") == "done":
                break
            time.sleep(0.2)
        assert status.get("status") == "done", status
    items = LibraryStore.open(library).list_items()
    assert any(it.title == "异步作品" for it in items)
    item = next(it for it in items if it.title == "异步作品")
    assert (library / ".subforge" / "covers" / f"{item.item_id}.jpg").exists()
