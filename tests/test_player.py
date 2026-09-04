from pathlib import Path

from starlette.testclient import TestClient

from subforge.library import ImportRequest, ItemKind, LibraryStore
from subforge.models import SubtitleEntry
from subforge.translate.srt_io import write_srt
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.picker import FakeFilePicker
from subforge.ui.profiles import LlmProfileStore
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter


def _player_client(tmp_path):
    library_root = tmp_path / "Library"
    store = LibraryStore.initialize(library_root)
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"0123456789")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000300"
    ))
    write_srt(
        [SubtitleEntry(1, 0.0, 1.0, "こんにちは")],
        store.track_subtitle_path(imported.track_id, "ja"),
    )
    write_srt(
        [SubtitleEntry(1, 0.0, 1.0, "你好")],
        store.track_subtitle_path(imported.track_id, "zh"),
    )
    store.update_track_status(imported.track_id, "playable")
    store.close()
    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(library_root)
    app = create_app(UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=LlmProfileStore(tmp_path / "profiles.json"),
        worker=FakeWorkerAdapter([]),
        startup_token="token",
        open_browser=False,
        allowed_hosts={"testserver"},
    ))
    client = TestClient(app)
    client.get("/?token=token")
    # 模拟 iframe 外壳内请求（内页内容断言）
    _frame_headers = {"sec-fetch-dest": "iframe"}
    original_get = client.get

    def _get(url, **kwargs):
        kwargs.setdefault("headers", {})
        kwargs["headers"] = {**_frame_headers, **kwargs["headers"]}
        return original_get(url, **kwargs)

    client.get = _get
    return client, imported.track_id


def test_media_route_supports_byte_range(tmp_path):
    client, track_id = _player_client(tmp_path)

    response = client.get(f"/tracks/{track_id}/media", headers={"range": "bytes=2-5"})

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["accept-ranges"] == "bytes"


def test_invalid_range_returns_416(tmp_path):
    client, track_id = _player_client(tmp_path)

    response = client.get(f"/tracks/{track_id}/media", headers={"range": "bytes=99-100"})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


def test_subtitle_route_returns_only_track_languages(tmp_path):
    client, track_id = _player_client(tmp_path)

    source = client.get(f"/tracks/{track_id}/subtitles/ja")
    forbidden = client.get(f"/tracks/{track_id}/subtitles/en")

    assert source.status_code == 200
    assert source.json() == [{"start": 0.0, "end": 1.0, "text": "こんにちは"}]
    assert forbidden.status_code == 404


def test_global_player_repairs_missing_item_id_when_same_track_reactivated():
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "global-player.js").read_text(encoding="utf-8")
    start = js.index("activate(trackId")
    activate = js[start:js.index("close()", start)]

    assert "st.itemId !== itemId" in activate
    # 空 itemId 不得再拼出 /covers/ 这种必然 404 的请求
    assert "const coverUrl = st.itemId ? `/covers/${st.itemId}` : '';" in js


def test_player_and_track_row_carry_item_id_for_cover_thumbnail(tmp_path):
    client, track_id = _player_client(tmp_path)
    page = client.get(f"/tracks/{track_id}/play")

    assert 'data-item-id=' in page.text
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "player.js").read_text(encoding="utf-8")
    assert "itemId=root.dataset.itemId" in js
    assert "player.activate(track,title,itemId)" in js


def test_player_page_contains_audio_and_bilingual_subtitle_surfaces(tmp_path):
    client, track_id = _player_client(tmp_path)

    response = client.get(f"/tracks/{track_id}/play")

    assert response.status_code == 200
    assert 'id="play-toggle"' in response.text       # 自绘控制条（统一音频源）
    assert 'id="play-seek"' in response.text
    assert 'id="source-subtitle"' in response.text
    assert 'id="target-subtitle"' in response.text
    assert 'data-source-language="ja"' in response.text
    assert 'data-target-language="zh"' in response.text
    # media 由全局播放器 iframe（embed 页）加载
    embed_page = client.get(f"/tracks/{track_id}/play?embed=1").text
    assert f'/tracks/{track_id}/media' in embed_page


def test_transcript_rows_include_time_and_translation_columns(tmp_path):
    """全部字幕区：JS 渲染 4 列（起/止时间 + 双语），缺失翻译显示占位。"""
    client, track_id = _player_client(tmp_path)
    page = client.get(f"/tracks/{track_id}/play").text
    assert 'id="transcript"' in page

    # player.js 必须渲染起止时间列并处理缺失翻译
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "player.js").read_text(encoding="utf-8")
    assert "entry.start" in js and "entry.end" in js
    assert "transcript-time" in js           # 时间列 class
    assert "target[i]?.text" in js or "target[i]" in js


def test_transcript_is_lazily_rendered_on_details_open():
    """全部字幕懒加载：transcript DOM 仅在 <details> 展开（toggle）时才构建，
    折叠时跳过，避免几千条字幕一次性挤进 DOM。"""
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "player.js").read_text(encoding="utf-8")
    assert "loadSubtitleData" in js and "renderTranscript" in js
    assert "armTranscriptToggle" in js
    # renderTranscript 仅在 <details> open 后才被调用
    assert "details.open" in js
    assert "toggle" in js


def test_global_player_has_persistent_200_percent_volume_control():
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "global-player.js").read_text(encoding="utf-8")

    assert 'data-role="volume"' in js
    assert 'max="2"' in js
    assert "setVolume" in js
    assert "createGain" in js
    assert "volume * 100" in js


def test_player_bar_single_row_layout():
    """播放条为单行紧凑网格：封面、标题、进度、控制键同排等高。"""
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "global-player.js").read_text(encoding="utf-8")
    css = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "app.css").read_text(encoding="utf-8")

    assert "player-bar-row" in js
    assert "player-bar-cover" in js
    assert "player-bar-row{display:grid" in css
    assert "grid-template-columns:36px minmax(100px,1fr)" in css


def test_global_player_rebuilds_audio_frame_when_detail_track_changes():
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "global-player.js").read_text(encoding="utf-8")
    activate = js[js.index("activate(trackId"):js.index("close()", js.index("activate(trackId"))]

    assert "this.frame.remove()" in activate
    assert "this.frame = null" in activate
    assert "this.audio = null" in activate


def test_player_handles_missing_subtitles_without_blocking_audio():
    js = (Path(__file__).parent.parent / "subforge" / "ui" / "static" / "player.js").read_text(encoding="utf-8")
    assert "暂无源语言字幕" in js
    assert "暂无翻译字幕" in js


def test_player_page_has_subtitle_mode_selector(tmp_path):
    """播放页必须有字幕模式选择（双语/仅原文/仅译文/关闭）。"""
    client, track_id = _player_client(tmp_path)
    page = client.get(f"/tracks/{track_id}/play").text
    assert 'data-subtitle-mode="both"' in page
    assert 'data-subtitle-mode="source"' in page
    assert 'data-subtitle-mode="target"' in page
    assert 'data-subtitle-mode="off"' in page


def test_every_page_has_global_player_bar(tmp_path):
    """顶层外壳固定播放条；内页（iframe 内容）不含播放条（外壳持有）。"""
    client, track_id = _player_client(tmp_path)
    # 顶层外壳（无 Sec-Fetch-Dest: iframe）→ 含播放条 + 内容 iframe
    shell = client.get("/", headers={"sec-fetch-dest": "document"}).text
    assert 'id="player-bar"' in shell
    assert "/static/global-player.js" in shell
    assert 'id="content-frame"' in shell
    # 内页（iframe 内）→ 不含播放条（由外壳统一持有）
    inner = client.get(f"/tracks/{track_id}/play").text
    assert 'id="player-bar"' not in inner
    assert "/static/global-player.js" not in inner


def test_player_embed_mode_renders_bare_audio(tmp_path):
    """embed=1 模式（底部播放条 iframe）：只保留 audio，隐藏完整页面装饰。"""
    client, track_id = _player_client(tmp_path)
    page = client.get(f"/tracks/{track_id}/play?embed=1").text
    assert 'id="audio"' in page
    assert f'/tracks/{track_id}/media' in page
    assert 'class="player-bar"' not in page   # iframe 内不渲染底部条（仅空容器）
    assert 'data-embed="1"' in page
