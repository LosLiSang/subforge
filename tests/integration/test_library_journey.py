"""Golden Journey: Library & Item Lifecycle.

涵盖作品全生命周期黄金主干：
1. 身份与 CSRF 会话协商
2. 作品导入（含音轨、声优、社团与标签）
3. 作品列表检索（分页、total_size、subtitle_status）
4. 标签管理与级联（/api/tags/list、创建、级联重命名、级联删除、作品内联更新）
5. 作品详情与统计概览（/api/items/{id}）
6. 音频流式传输（Byte-Range 206）
7. 双语字幕读取与在线编辑持久化（/api/tracks/{id}/subtitles & /edit）
8. 声优管理与系统统计（/api/creators, /api/stats）
"""

import struct
import wave
from pathlib import Path
import pytest
import httpx

from unittest.mock import patch

from subforge.dlsite import DlsiteMetadata
from subforge.library import CreatorKind, ImportRequest, ItemKind, LibraryStore
from subforge.models import SubtitleEntry
from subforge.translate.srt_io import write_srt
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter


def _generate_silent_wav(path: Path, duration_secs: float = 2.0, sample_rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(duration_secs * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            wf.writeframes(struct.pack("<h", 0))


@pytest.mark.asyncio
async def test_library_and_item_golden_journey(tmp_path: Path):
    lib_dir = tmp_path / "golden_library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    library = LibraryStore.initialize(lib_dir)

    # 1. 准备声优与社团
    cv = library._find_or_create_creator("早见沙织", CreatorKind.VOICE_ACTOR)
    circle = library._find_or_create_creator("同人社团A", CreatorKind.CIRCLE)

    # 2. 导入作品与音轨
    media_file = tmp_path / "audio_track.wav"
    _generate_silent_wav(media_file, duration_secs=4.0)
    imported = library.import_audio(ImportRequest(
        source=media_file,
        title="黄金旅程测试ASMR作品",
        kind=ItemKind.RJ_WORK,
        rj_code="RJ01999999",
        creator_ids=[cv.creator_id, circle.creator_id],
    ))
    item_id = imported.item_id
    track_id = imported.track_id

    # 赋予初始标签
    library.update_item(
        item_id,
        title="黄金旅程测试ASMR作品",
        kind=ItemKind.RJ_WORK,
        rj_code="RJ01999999",
        creator_ids=[cv.creator_id, circle.creator_id],
        tags=["ASMR", "耳舐め", "催眠"],
    )

    # 写入双语字幕
    ja_path = library.track_subtitle_path(track_id, "ja")
    zh_path = library.track_subtitle_path(track_id, "zh")
    write_srt([SubtitleEntry(index=1, start=0.0, end=2.0, text="こんにちは")], ja_path)
    write_srt([SubtitleEntry(index=1, start=0.0, end=2.0, text="你好")], zh_path)
    library.update_track_status(track_id, "completed")
    library.close()

    # 3. 启动应用
    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(lib_dir)
    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=ModelProfileStore(tmp_path / "profiles.json"),
        worker=FakeWorkerAdapter([]),
        startup_token="golden-secret-token",
        is_fixed_token=True,
        allowed_hosts={"127.0.0.1", "localhost", "testserver"},
    )
    app = create_app(deps)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: 会话鉴权与 CSRF 获取
        auth_res = await client.get("/?token=golden-secret-token", follow_redirects=True)
        assert auth_res.status_code == 200
        session_info = (await client.get("/api/session")).json()
        csrf_token = session_info["csrf_token"]
        assert csrf_token is not None
        headers = {"x-csrf-token": csrf_token, "origin": "http://testserver"}

        # Step 2: 作品列表查询（分页、total_size、subtitle_status）
        items_res = await client.get("/api/library/items?page=1&limit=10")
        assert items_res.status_code == 200
        items_data = items_res.json()
        assert items_data["total"] >= 1
        work = next(it for it in items_data["items"] if it["item_id"] == item_id)
        assert work["title"] == "黄金旅程测试ASMR作品"
        assert work["rj_code"] == "RJ01999999"
        assert work["subtitle_status"] == "bilingual"
        assert work["total_size"] > 0
        assert len(work["creators"]) == 2
        assert "ASMR" in work["tags"]

        # Step 3: 标签体系与级联操作
        # 3a. 查询标签聚合列表
        tag_list_res = await client.get("/api/tags/list")
        assert tag_list_res.status_code == 200
        tag_map = {t["name"]: t["item_count"] for t in tag_list_res.json()}
        assert tag_map.get("ASMR") == 1
        assert tag_map.get("耳舐め") == 1

        # 3b. 创建新标签
        create_tag_res = await client.post("/api/tags", data={"action": "create", "name": "新标签X"}, headers=headers)
        assert create_tag_res.status_code in (200, 201)

        # 3c. 级联重命名标签 ("耳舐め" -> "极上舔耳")
        rename_tag_res = await client.post(
            "/api/tags",
            data={"action": "rename", "old_name": "耳舐め", "new_name": "极上舔耳"},
            headers=headers,
        )
        assert rename_tag_res.status_code == 200
        # 验证关联作品中的标签已被自动更新
        rechecked_lib = LibraryStore.open(lib_dir)
        updated_work = rechecked_lib.get_item(item_id)
        assert "极上舔耳" in updated_work.tags
        assert "耳舐め" not in updated_work.tags
        rechecked_lib.close()

        # 3d. 级联删除标签 ("催眠")
        del_tag_res = await client.post(
            "/api/tags",
            data={"action": "delete", "name": "催眠"},
            headers=headers,
        )
        assert del_tag_res.status_code == 200
        rechecked_lib2 = LibraryStore.open(lib_dir)
        assert "催眠" not in rechecked_lib2.get_item(item_id).tags
        rechecked_lib2.close()

        # Step 4: 作品详情与统计概览
        detail_res = await client.get(f"/api/items/{item_id}")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["item"]["item_id"] == item_id
        assert len(detail["tracks"]) == 1
        assert detail["tracks"][0]["has_media"] is True
        assert detail["tracks"][0]["has_target_sub"] is True
        assert detail["overview"]["all_completed"] is True
        assert "0:02" in detail["overview"]["total_duration_label"]

        # Step 5: 音频 Byte-Range 流式传输
        media_res = await client.get(
            f"/api/tracks/{track_id}/media",
            headers={"range": "bytes=0-511"},
        )
        assert media_res.status_code == 206
        assert media_res.headers["content-range"].startswith("bytes 0-511/")
        assert len(media_res.content) == 512

        # Step 6: 双语字幕读取与在线编辑持久化
        sub_res = await client.get(f"/api/tracks/{track_id}/subtitles")
        assert sub_res.status_code == 200
        sub_data = sub_res.json()
        assert sub_data["source"][0]["text"] == "こんにちは"
        assert sub_data["target"][0]["text"] == "你好"

        # 在线编辑译文并保存
        edit_sub_res = await client.post(
            f"/api/tracks/{track_id}/subtitles/edit",
            json={
                "language": "zh",
                "index": 1,
                "start": 0.0,
                "end": 2.5,
                "text": "你好，主人！",
            },
            headers=headers,
        )
        assert edit_sub_res.status_code == 200
        sub_after_edit = (await client.get(f"/api/tracks/{track_id}/subtitles")).json()
        assert sub_after_edit["target"][0]["text"] == "你好，主人！"

        # Step 7: 声优管理与全局统计
        new_cv_res = await client.post(
            "/api/creators",
            data={"name": "临时测试声优C", "kind": "voice_actor"},
            headers=headers,
        )
        assert new_cv_res.status_code == 201
        temp_cv_id = new_cv_res.json()["creator_id"]

        del_cv_res = await client.post(
            "/creators",
            data={"action": "delete", "creator_id": temp_cv_id},
            headers={**headers, "Accept": "application/json"},
        )
        assert del_cv_res.status_code == 200

        stats_res = await client.get("/api/stats")
        assert stats_res.status_code == 200
        stats_data = stats_res.json()
        assert stats_data["total_items"] >= 1
        assert stats_data["subtitled_percentage"] == 100.0

        # Step 8: DLsite 元数据查询与一键同步
        mock_dlsite = DlsiteMetadata(
            rj_code="RJ01999999",
            title="DLsite最新同步标题",
            circle="社团TOP",
            voice_actors=["早见沙织"],
            tags=["ASMR", "最新标签"],
            cover_url="https://img.dlsite.jp/cover.jpg",
            release_date="2025-02-01",
        )
        fake_cover = b"\xff\xd8\xff\xe0" + b"\x00" * 100

        with patch("subforge.dlsite.fetch_dlsite_metadata", return_value=mock_dlsite), \
             patch("subforge.dlsite.fetch_dlsite_cover", return_value=fake_cover):
            # 8a. /api/dlsite/{rj_code} 接口查询
            query_dlsite_res = await client.get("/api/dlsite/RJ01999999", headers=headers)
            assert query_dlsite_res.status_code == 200
            assert query_dlsite_res.json()["data"]["circle"] == "社团TOP"

            # 8b. /api/items/{id}/sync-dlsite 触发作品元数据与标签同步
            sync_res = await client.post(f"/api/items/{item_id}/sync-dlsite", headers=headers)
            assert sync_res.status_code == 200
            assert sync_res.json().get("ok") is True

        # 验证同步后作品标签已自动更新
        rechecked_lib3 = LibraryStore.open(lib_dir)
        synced_item = rechecked_lib3.get_item(item_id)
        assert "最新标签" in synced_item.tags
        assert synced_item.cover_source == "dlsite"
        rechecked_lib3.close()

        # Step 9: 标签检索、关键字与作品分类 (kind) 过滤
        # 9a. 标签过滤
        filter_tag_res = await client.get("/api/library/items?tag=最新标签", headers=headers)
        assert filter_tag_res.status_code == 200
        assert filter_tag_res.json()["total"] >= 1

        # 9b. 分类过滤 (kind=rj_work)
        kind_res = await client.get("/api/library/items?kind=rj_work", headers=headers)
        assert kind_res.status_code == 200
        assert all(it["kind"] == "rj_work" for it in kind_res.json()["items"])

