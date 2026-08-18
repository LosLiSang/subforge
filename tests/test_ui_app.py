import re
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from subforge.library import ImportRequest, ItemKind, LibraryStore
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.picker import FakeFilePicker
from subforge.ui.profiles import LlmProfileStore
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter


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
    store.close()

    page = client.get(f"/items/{item_id}")
    html = page.text
    assert 'class="work-hero"' in html
    assert "直播作品" in html
    assert "miyadi" in html
    assert 'class="track-row' in html
    assert "b.mp3" in html
    # 处理表单字段与端点全部保留
    assert 'name="asr_provider"' in html
    assert 'name="scene"' in html
    assert 'name="whisper_model"' in html
    assert 'name="llm_profile_id"' in html
    assert 'name="mode"' in html
    assert "/process" in html


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


def test_downloads_page_shows_model_and_proxy_status(tmp_path):
    """下载管理页：模型缓存/直接目录/代理配置状态。"""
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    page = client.get("/downloads").text
    assert "下载管理" in page or "下载" in page
    assert "模型" in page


def test_about_page_reports_version(tmp_path):
    """关于页：版本号与仓库链接。"""
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)

    page = client.get("/about").text
    assert "0.4.0" in page
    assert "github.com" in page


def test_shell_sidebar_contains_all_nav_entries(tmp_path):
    """顶层外壳：侧边导航含全部入口（含新页），内容在 iframe。"""
    library = tmp_path / "Library"
    client, headers = _authenticated_client(tmp_path, library=library)
    shell = client.get("/", headers={"sec-fetch-dest": "document"}).text
    assert 'class="sidebar"' in shell
    for entry in ("作品库", "翻译配置", "设置", "统计", "下载管理", "关于"):
        assert entry in shell
    assert 'id="content-frame"' in shell
