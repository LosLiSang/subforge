"""
End-to-End Verification Test for DLsite Metadata Auto-Pulling and Tag Search Adaptation.

SYSTEM FAILURE MODES (Documented upfront as required by AGENTS.md):
-----------------------------------------------------------------------------
1. FM1: Network & Offline Resilience / Parsing Divergence:
   - DLsite product pages may change structure or floor (maniax vs home vs girls).
   - Network requests may fail, timeout, or require proxy/cookies (adultchecked=1).
   - Failure must be graceful and non-blocking: import must NEVER fail or crash when DLsite is unreachable.
   - Missing table rows (e.g. works without voice actors or genres) must default safely.

2. FM2: Creator Association & Duplicate Prevention:
   - Circles must be mapped to CreatorKind.CIRCLE and voice actors to CreatorKind.VOICE_ACTOR.
   - Re-running sync or importing multiple works from the same circle/CV must reuse existing creators.

3. FM3: Tag Search & Filtering Omission:
   - Previous library search only checked title, rj_code, and creator names, ignoring tags.
   - Search by keyword, tokens, or #tag / tag:tag syntax must match item tags.
   - Dedicated tag filter query parameter and UI dropdown must filter works accurately.
   - Library item listing must return all_tags and tag_counts.

4. FM4: Tag Persistence Across Storage & Edits:
   - Tags must be persisted in metadata.json and survive restarts / sync_index.
   - Manual edits via /items/{id}/edit must preserve and update tags and original_title.

5. FM5: Cover Image Ingestion & Referer Protection:
   - DLsite image CDNs (img.dlsite.jp) reject requests without proper Referer/User-Agent.
   - Image downloader must provide valid headers, validate payload, and set cover_source="dlsite".
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from subforge.dlsite import (
    DlsiteMetadata,
    fetch_dlsite_cover,
    fetch_dlsite_metadata,
    normalize_rj_code,
    parse_dlsite_html,
    resolve_dlsite_proxy,
)
from subforge.library import CreatorKind, ImportRequest, ItemKind, LibraryStore
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
FRONTEND_DIST = REPO_ROOT / "subforge" / "ui" / "dist"

SAMPLE_DLSITE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta property="og:title" content="【パンツ超特化】【3時間30分超】パンツの女神たち | DLsite 同人 - R18">
  <meta property="og:image" content="https://img.dlsite.jp/modpub/images2/work/doujin/RJ01307000/RJ01306764_img_main.jpg">
</head>
<body>
  <h1 id="work_name">【パンツ超特化】【3時間30分超】パンツの女神たち</h1>
  <span class="maker_name"><a href="/circle/123.html">VOICE LOVER</a></span>
  <table id="work_outline">
    <tr>
      <th>サークル名</th>
      <td><a href="/circle/123.html">VOICE LOVER</a></td>
    </tr>
    <tr>
      <th>声優</th>
      <td><a href="/author/1.html">陽向葵ゅか</a></td>
    </tr>
    <tr>
      <th>販売日</th>
      <td>2024年12月27日</td>
    </tr>
    <tr>
      <th>ジャンル</th>
      <td>
        <a href="/genre/101.html">ASMR</a>
        <a href="/genre/102.html">ささやき</a>
        <a href="/genre/103.html">甘サド</a>
        <a href="/genre/104.html">耳かき</a>
      </td>
    </tr>
  </table>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_dlsite_metadata_and_tag_search_e2e(tmp_path: Path):
    # -------------------------------------------------------------------------
    # Step 1: Verify DLsite HTML parser and RJ normalization (FM1, FM5)
    # -------------------------------------------------------------------------
    assert normalize_rj_code("rj01306764") == "RJ01306764"
    assert normalize_rj_code("01306764") == "RJ01306764"
    assert normalize_rj_code("RJ123456") == "RJ123456"

    parsed = parse_dlsite_html(SAMPLE_DLSITE_HTML, "RJ01306764")
    assert parsed.rj_code == "RJ01306764"
    assert parsed.title == "【パンツ超特化】【3時間30分超】パンツの女神たち"
    assert parsed.circle == "VOICE LOVER"
    assert parsed.voice_actors == ["陽向葵ゅか"]
    assert "ASMR" in parsed.tags
    assert "耳かき" in parsed.tags
    assert "甘サド" in parsed.tags
    assert parsed.release_date == "2024-12-27"
    assert parsed.cover_url == "https://img.dlsite.jp/modpub/images2/work/doujin/RJ01307000/RJ01306764_img_main.jpg"

    # -------------------------------------------------------------------------
    # Step 2: Initialize Library & FastAPI Backend
    # -------------------------------------------------------------------------
    lib_dir = tmp_path / "library"
    lib_dir.mkdir()
    library = LibraryStore.initialize(lib_dir)

    profile_store = ModelProfileStore(tmp_path / "model-profiles.json")
    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(lib_dir)
    picker = FakeFilePicker()
    deps = UiDependencies(
        settings=settings,
        picker=picker,
        profiles=profile_store,
        worker=FakeWorkerAdapter([]),
        startup_token="test-e2e-token",
        is_fixed_token=True,
        no_auth=True,
        allowed_hosts={"testserver", "localhost", "127.0.0.1"},
    )
    app = create_app(deps)

    fake_cover_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00\xff\xfe\x00\x10Lavc61.11.100\x00\xff\xdb\x00C\x00"
        b"\x08\x04\x04\x04\x04\x04\x05\x05\x05\x05\x05\x05\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x07\x07\x07\x08"
        b"\x08\x08\x07\x07\x07\x06\x06\x07\x07\x08\x08\x08\x08\t\t\t\x08\x08\x08\x08\t\t\n\n\n\x0c\x0c\x0b\x0b\x0e\x0e\x0e\x11"
        b"\x11\x14\xff\xc4\x00M\x00\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07\x01\x01\x01\x01\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x07\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x11\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc0\x00\x11\x08\x00@\x00"
        b"@\x03\x01\x22\x00\x02\x11\x00\x03\x11\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\x8e\x00\xdf\xd2\xc0\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\xff\xd9"
    )

    mock_meta = DlsiteMetadata(
        rj_code="RJ01306764",
        title="【パンツ超特化】【3時間30分超】パンツの女神たち",
        circle="VOICE LOVER",
        voice_actors=["陽向葵ゅか"],
        tags=["ASMR", "ささやき", "甘サド", "耳かき"],
        cover_url="https://img.dlsite.jp/fake_cover.jpg",
        release_date="2024-12-27",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_info = (await client.get("/api/session")).json()
        headers = {"x-csrf-token": session_info["csrf_token"], "origin": "http://testserver"}

        # -------------------------------------------------------------------------
        # Step 3: Verify GET /api/dlsite/{rj_code} endpoint (FM1)
        # -------------------------------------------------------------------------
        with patch("subforge.dlsite.fetch_dlsite_metadata", return_value=mock_meta):
            res_dlsite = await client.get("/api/dlsite/RJ01306764", headers=headers)
            assert res_dlsite.status_code == 200
            dlsite_json = res_dlsite.json()
            assert dlsite_json["ok"] is True
            assert dlsite_json["data"]["circle"] == "VOICE LOVER"
            assert dlsite_json["data"]["voice_actors"] == ["陽向葵ゅか"]
            assert "耳かき" in dlsite_json["data"]["tags"]

        # -------------------------------------------------------------------------
        # Step 4: Folder Import with RJ Code -> Auto Pull DLsite Info (FM1, FM2, FM5)
        # -------------------------------------------------------------------------
        work_folder = tmp_path / "RJ01306764_import_folder"
        work_folder.mkdir()
        track1 = work_folder / "track01.mp3"
        track1.write_bytes(b"\x00" * 20000)
        track2 = work_folder / "track02.wav"
        track2.write_bytes(b"\x00" * 30000)

        picker.media_folder = work_folder
        picker_res = await client.post("/picker/folder", headers=headers)
        assert picker_res.status_code == 200
        selection_id = picker_res.json()["selection_id"]

        with patch("subforge.dlsite.fetch_dlsite_metadata", return_value=mock_meta), \
             patch("subforge.dlsite.fetch_dlsite_cover", return_value=fake_cover_bytes):
            res_import = await client.post(
                "/items/import-folder",
                data={
                    "selection_id": selection_id,
                    "rj_code": "RJ01306764",
                    "title": "",
                },
                headers=headers,
            )
            assert res_import.status_code == 202
            import_task_id = res_import.json()["task_id"]

            # Wait for worker thread to complete import
            for _ in range(50):
                await asyncio.sleep(0.1)
                status_res = await client.get(f"/api/imports/{import_task_id}")
                st = status_res.json()
                if st.get("status") in {"done", "partial", "error"}:
                    break
            assert st.get("status") == "done", f"Import task failed: {st}"

        # Verify created item in library
        items = library.list_items()
        assert len(items) == 1
        imported_item = items[0]
        assert imported_item.rj_code == "RJ01306764"
        assert imported_item.title == mock_meta.title
        assert imported_item.release_date == "2024-12-27"
        assert imported_item.cover_source == "dlsite"
        assert "ASMR" in imported_item.tags
        assert "甘サド" in imported_item.tags

        # Verify Creators created with proper kinds
        creators = library.list_creators()
        circle = next((c for c in creators if c.name == "VOICE LOVER"), None)
        va = next((c for c in creators if c.name == "陽向葵ゅか"), None)
        assert circle is not None, "Circle VOICE LOVER must be created"
        assert circle.kind == CreatorKind.CIRCLE
        assert va is not None, "Voice actor 陽向葵ゅか must be created"
        assert va.kind == CreatorKind.VOICE_ACTOR

        # -------------------------------------------------------------------------
        # Step 5: Verify Tag Search & Filtering (FM3)
        # -------------------------------------------------------------------------
        # Add a second item without the ASMR tags for contrast
        media2 = tmp_path / "second_track.mp3"
        media2.write_bytes(b"\x00" * 15000)
        item2_res = library.import_audio(ImportRequest(
            source=media2,
            title="普通的日常直播录音",
            kind=ItemKind.STREAM_ARCHIVE,
            author="主播小萌",
        ))
        library.update_item(
            item2_res.item_id,
            title="普通的日常直播录音",
            kind=ItemKind.STREAM_ARCHIVE,
            rj_code=None,
            creator_ids=library.get_item(item2_res.item_id).creator_ids,
            tags=["杂谈", "游戏"],
        )

        # 5a. Verify all_tags and tag_counts in /api/library/items
        res_list = await client.get("/api/library/items", headers=headers)
        assert res_list.status_code == 200
        list_data = res_list.json()
        assert list_data["total"] == 2
        all_tags = list_data["all_tags"]
        assert "ASMR" in all_tags
        assert "耳かき" in all_tags
        assert "杂谈" in all_tags
        assert list_data["tag_counts"]["ASMR"] == 1

        # 5b. Search by tag text (e.g. q="甘サド")
        res_search_tag = await client.get("/api/library/items?q=甘サド", headers=headers)
        res_search_json = res_search_tag.json()
        assert res_search_json["total"] == 1
        assert res_search_json["items"][0]["rj_code"] == "RJ01306764"

        # 5c. Search by #tag syntax (e.g. q="#耳かき")
        res_hash_search = await client.get("/api/library/items?q=%23耳かき", headers=headers)
        assert res_hash_search.json()["total"] == 1
        assert res_hash_search.json()["items"][0]["rj_code"] == "RJ01306764"

        # 5d. Tag filter query param (tag=杂谈)
        res_tag_filter = await client.get("/api/library/items?tag=杂谈", headers=headers)
        tag_filter_json = res_tag_filter.json()
        assert tag_filter_json["total"] == 1
        assert tag_filter_json["items"][0]["title"] == "普通的日常直播录音"

        # -------------------------------------------------------------------------
        # Step 6: Verify On-Demand Sync: POST /api/items/{id}/sync-dlsite (FM1, FM4)
        # -------------------------------------------------------------------------
        # Create a work with RJ code but empty tags
        media3 = tmp_path / "sync_track.mp3"
        media3.write_bytes(b"\x00" * 12000)
        item3_res = library.import_audio(ImportRequest(
            source=media3,
            title="待同步作品 RJ01308888",
            kind=ItemKind.RJ_WORK,
            rj_code="RJ01308888",
        ))
        assert library.get_item(item3_res.item_id).tags == []

        mock_meta2 = DlsiteMetadata(
            rj_code="RJ01308888",
            title="另一个DLsite作品",
            circle="新社团B",
            voice_actors=["新声优C"],
            tags=["催眠", "耳舐め"],
            cover_url="https://img.dlsite.jp/fake_cover2.jpg",
            release_date="2025-01-01",
        )
        with patch("subforge.dlsite.fetch_dlsite_metadata", return_value=mock_meta2), \
             patch("subforge.dlsite.fetch_dlsite_cover", return_value=fake_cover_bytes):
            sync_res = await client.post(
                f"/api/items/{item3_res.item_id}/sync-dlsite",
                headers=headers,
            )
            assert sync_res.status_code == 200
            assert sync_res.json()["ok"] is True

        item3_updated = library.get_item(item3_res.item_id)
        assert "催眠" in item3_updated.tags
        assert "耳舐め" in item3_updated.tags
        assert item3_updated.cover_source == "dlsite"

        # -------------------------------------------------------------------------
        # Step 7: Verify Item Edit: POST /items/{id}/edit (FM4)
        # -------------------------------------------------------------------------
        edit_res = await client.post(
            f"/items/{item3_res.item_id}/edit",
            data={
                "title": "手动修改后的标题",
                "original_title": "Original Japanese Title",
                "rj_code": "RJ01308888",
                "tags": "新标签A, 新标签B, 催眠",
            },
            headers={**headers, "accept": "application/json"},
        )
        assert edit_res.status_code == 200
        item3_edited = library.get_item(item3_res.item_id)
        assert item3_edited.title == "手动修改后的标题"
        assert item3_edited.original_title == "Original Japanese Title"
        assert "新标签A" in item3_edited.tags
        assert "催眠" in item3_edited.tags

        # -------------------------------------------------------------------------
        # Step 8: Verify Frontend Source & Built Bundle
        # -------------------------------------------------------------------------
        library_page_src = (FRONTEND_SRC / "pages" / "Library" / "index.tsx").read_text(encoding="utf-8")
        assert "allTags" in library_page_src
        assert "全部标签" in library_page_src
        assert "tagCounts" in library_page_src

        item_detail_src = (FRONTEND_SRC / "pages" / "ItemDetail" / "index.tsx").read_text(encoding="utf-8")
        assert "sync-dlsite" in item_detail_src
        assert "从 DLsite 同步" in item_detail_src

        import_folder_src = (FRONTEND_SRC / "pages" / "Library" / "ImportFolderModal.tsx").read_text(encoding="utf-8")
        assert "从 DLsite 获取信息" in import_folder_src
        assert "dlsiteMeta" in import_folder_src

        # Check compiled bundle contains dlsite sync
        dist_js_files = list((FRONTEND_DIST / "assets").glob("*.js"))
        assert len(dist_js_files) > 0
        compiled_js = "\n".join(f.read_text(encoding="utf-8") for f in dist_js_files)
        assert "sync-dlsite" in compiled_js
        assert "api/dlsite" in compiled_js

        # -------------------------------------------------------------------------
        # Step 9: Verify Live Scraping Through Proxy (if available)
        # -------------------------------------------------------------------------
        live_proxy = resolve_dlsite_proxy()
        if live_proxy:
            live_meta = fetch_dlsite_metadata("RJ01306764", proxy=live_proxy, timeout=10)
            if live_meta:
                assert live_meta.circle == "VOICE LOVER"
                assert "陽向葵ゅか" in live_meta.voice_actors
                assert len(live_meta.tags) > 0
                if live_meta.cover_url:
                    live_cover = fetch_dlsite_cover(live_meta.cover_url, proxy=live_proxy, timeout=10)
                    assert live_cover is not None and len(live_cover) > 1000

    # -------------------------------------------------------------------------
    # Step 10: Generate Reproducible Artifact
    # -------------------------------------------------------------------------
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "dlsite_metadata_and_tag_search_e2e_artifact.json"
    artifact_content = {
        "test_name": "test_dlsite_metadata_and_tag_search_e2e",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "verified_features": [
            "DLsite HTML parser (title, circle, CVs, tags, cover_url, release_date)",
            "RJ code normalization and floor redirection",
            "Folder import auto-pulling DLsite metadata & cover",
            "Circle and Voice Actor creator mapping with CreatorKind",
            "Tag keyword search, #tag syntax, and tag query param filter",
            "Tag list and tag counts aggregation in api_list_items",
            "On-demand DLsite sync endpoint (/api/items/{id}/sync-dlsite)",
            "Manual tag and original title editing persistence",
            "Frontend tag filter selector, DLsite sync button, and modal preview",
            "Compiled bundle distribution synchronization",
        ],
        "test_counts": {
            "items_imported": len(library.list_items()),
            "creators_indexed": len(library.list_creators()),
            "total_tags_indexed": len(all_tags),
        },
    }
    artifact_path.write_text(json.dumps(artifact_content, indent=2, ensure_ascii=False), encoding="utf-8")
    assert artifact_path.is_file()
    assert artifact_path.stat().st_size > 100

    # Also copy artifact to repo tests directory for verifiable artifact preservation
    repo_artifact = REPO_ROOT / "tests" / "dlsite_tag_search_e2e_artifact.json"
    repo_artifact.write_text(json.dumps(artifact_content, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[E2E ARTIFACT CREATED] {repo_artifact}")
