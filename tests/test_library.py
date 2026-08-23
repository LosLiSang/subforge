import json
import shutil
from pathlib import Path

import pytest

from subforge.library import CreatorKind, ImportRequest, ItemKind, LibraryStore


def test_initialize_creates_movable_library_structure(tmp_path):
    root = tmp_path / "Library"

    store = LibraryStore.initialize(root)

    assert store.root == root.resolve()
    assert (root / "library.json").exists()
    assert json.loads((root / "library.json").read_text(encoding="utf-8"))["schema_version"] == 1
    for relative in ("works", "streams", ".incoming", ".trash", ".subforge"):
        assert (root / relative).is_dir()


def test_import_rj_audio_copies_source_and_preserves_filename(tmp_path):
    root = tmp_path / "Library"
    source = tmp_path / "01 耳かき.m4a"
    source.write_bytes(b"audio-data")
    store = LibraryStore.initialize(root)

    result = store.import_audio(ImportRequest(
        source=source,
        kind=ItemKind.RJ_WORK,
        title="测试作品",
        rj_code="RJ01546796",
    ))

    assert result.created is True
    assert source.read_bytes() == b"audio-data"
    item = store.get_item(result.item_id)
    assert item.rj_code == "RJ01546796"
    assert len(item.tracks) == 1
    archived = root / "works" / "RJ01546796" / item.tracks[0].media
    assert archived.name == source.name
    assert archived.read_bytes() == source.read_bytes()
    assert item.tracks[0].status == "waiting"


def test_duplicate_hash_is_not_copied_again(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    first = tmp_path / "first.m4a"
    second = tmp_path / "renamed.m4a"
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    created = store.import_audio(ImportRequest(
        source=first, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000001"
    ))
    duplicate = store.import_audio(ImportRequest(
        source=second, kind=ItemKind.STREAM_ARCHIVE, title="Stream", author="Author"
    ))

    assert duplicate.created is False
    assert duplicate.item_id == created.item_id
    assert duplicate.track_id == created.track_id
    assert len(store.list_items()) == 1


def test_same_rj_adds_a_second_track(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    one = tmp_path / "one.m4a"
    two = tmp_path / "two.m4a"
    one.write_bytes(b"one")
    two.write_bytes(b"two")

    first = store.import_audio(ImportRequest(
        source=one, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000002"
    ))
    second = store.import_audio(ImportRequest(
        source=two, kind=ItemKind.RJ_WORK, title="Ignored", rj_code="RJ00000002"
    ))

    assert first.item_id == second.item_id
    assert first.track_id != second.track_id
    assert len(store.get_item(first.item_id).tracks) == 2


def test_stream_archive_requires_author(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    source = tmp_path / "stream.m4a"
    source.write_bytes(b"audio")

    with pytest.raises(ValueError, match="author is required"):
        store.import_audio(ImportRequest(
            source=source, kind=ItemKind.STREAM_ARCHIVE, title="Stream"
        ))


def test_damaged_sqlite_rebuilds_from_metadata(tmp_path):
    root = tmp_path / "Library"
    store = LibraryStore.initialize(root)
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    result = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000008"
    ))
    store.close()
    (root / ".subforge" / "index.sqlite").write_bytes(b"not sqlite")

    reopened = LibraryStore.open(root)

    assert reopened.get_item(result.item_id).title == "Work"
    assert list((root / ".subforge").glob("index.damaged-*.sqlite"))


def test_deleting_sqlite_rebuilds_from_metadata(tmp_path):
    root = tmp_path / "Library"
    store = LibraryStore.initialize(root)
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    result = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000003"
    ))
    store.close()
    (root / ".subforge" / "index.sqlite").unlink()

    reopened = LibraryStore.open(root)

    assert reopened.get_item(result.item_id).title == "Work"


def test_library_can_move_and_reopen(tmp_path):
    original = tmp_path / "Library"
    moved = tmp_path / "Moved Library"
    store = LibraryStore.initialize(original)
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    result = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000004"
    ))
    store.close()
    shutil.move(str(original), str(moved))

    reopened = LibraryStore.open(moved)
    item = reopened.get_item(result.item_id)

    assert reopened.track_media_path(item.tracks[0].track_id).read_bytes() == b"audio"


def test_prepare_retranslate_keeps_source_and_backs_up_target(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    result = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000006"
    ))
    source_srt = store.track_subtitle_path(result.track_id, "ja")
    target_srt = store.track_subtitle_path(result.track_id, "zh")
    source_srt.parent.mkdir(parents=True, exist_ok=True)
    source_srt.write_text("source", encoding="utf-8")
    target_srt.write_text("target", encoding="utf-8")
    resume = store.track_resume_dir(result.track_id) / "state.json"
    resume.write_text("{}", encoding="utf-8")

    store.prepare_processing(result.track_id, "retranslate")

    assert source_srt.exists()
    assert not target_srt.exists()
    assert list(target_srt.parent.glob("audio.zh.srt.bak-*"))
    assert not resume.exists()


def test_prepare_from_scratch_backs_up_both_subtitles_and_keeps_media(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    result = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000007"
    ))
    for language in ("ja", "zh"):
        path = store.track_subtitle_path(result.track_id, language)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(language, encoding="utf-8")

    store.prepare_processing(result.track_id, "from_scratch")

    assert store.track_media_path(result.track_id).read_bytes() == b"audio"
    assert not store.track_subtitle_path(result.track_id, "ja").exists()
    assert not store.track_subtitle_path(result.track_id, "zh").exists()


def test_trash_item_moves_directory_and_hides_index(tmp_path):
    root = tmp_path / "Library"
    store = LibraryStore.initialize(root)
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    result = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000005"
    ))

    store.trash_item(result.item_id)

    assert store.list_items() == []
    assert any((root / ".trash").iterdir())
    with pytest.raises(KeyError):
        store.get_item(result.item_id)


def test_creator_store_supports_same_name_with_distinct_ids(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")

    circle = store.create_creator("Alice", CreatorKind.CIRCLE)
    actor = store.create_creator("Alice", CreatorKind.VOICE_ACTOR)

    assert circle.creator_id != actor.creator_id
    assert [(c.name, c.kind) for c in store.list_creators()] == [
        ("Alice", CreatorKind.CIRCLE),
        ("Alice", CreatorKind.VOICE_ACTOR),
    ]


def test_update_item_enforces_creator_kind_rules_and_filters_by_all_creators(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=audio, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000009"
    ))
    circle = store.create_creator("Circle", CreatorKind.CIRCLE)
    actor = store.create_creator("Actor", CreatorKind.VOICE_ACTOR)

    updated = store.update_item(
        imported.item_id,
        title="Updated",
        kind=ItemKind.RJ_WORK,
        rj_code="RJ00000010",
        creator_ids=[circle.creator_id, actor.creator_id],
    )

    assert updated.title == "Updated"
    assert updated.rj_code == "RJ00000010"
    assert updated.creator_ids == [circle.creator_id, actor.creator_id]
    assert [item.item_id for item in store.list_items([circle.creator_id, actor.creator_id])] == [imported.item_id]
    assert store.list_items([circle.creator_id, "missing"]) == []

    with pytest.raises(ValueError, match="voice actors"):
        store.update_item(
            imported.item_id,
            title="Stream",
            kind=ItemKind.STREAM_ARCHIVE,
            rj_code=None,
            creator_ids=[circle.creator_id],
        )


def test_scan_rj_folder_recurses_classifies_and_prefixes_colliding_names(tmp_path):
    folder = tmp_path / "RJ01499022"
    (folder / "本篇").mkdir(parents=True)
    (folder / "特典").mkdir()
    (folder / "本篇" / "01.m4a").write_bytes(b"one")
    (folder / "特典" / "01.m4a").write_bytes(b"two")
    (folder / "movie.mp4").write_bytes(b"video")
    (folder / "booklet.pdf").write_bytes(b"pdf")
    store = LibraryStore.initialize(tmp_path / "Library")

    scan = store.scan_rj_folder(folder)

    assert scan.audio_count == 2
    assert scan.video_count == 1
    assert scan.skipped_count == 1
    assert [entry.relative_path for entry in scan.media] == [
        "movie.mp4", "本篇/01.m4a", "特典/01.m4a",
    ]
    names = {entry.relative_path: entry.archive_name for entry in scan.media}
    assert names["本篇/01.m4a"] == "本篇_01.m4a"
    assert names["特典/01.m4a"] == "特典_01.m4a"
    assert names["movie.mp4"] == "movie.m4a"


def test_import_rj_folder_converts_videos_defaults_title_and_reports_partial_success(tmp_path, monkeypatch):
    import subprocess
    folder = tmp_path / "RJ01499022"
    (folder / "本篇").mkdir(parents=True)
    (folder / "特典").mkdir()
    (folder / "本篇" / "01.m4a").write_bytes(b"one")
    (folder / "特典" / "01.m4a").write_bytes(b"two")
    (folder / "movie.mp4").write_bytes(b"video")
    (folder / "broken.mkv").write_bytes(b"broken")
    (folder / "readme.txt").write_text("skip", encoding="utf-8")
    store = LibraryStore.initialize(tmp_path / "Library")

    monkeypatch.setattr("subforge.library.shutil.which", lambda name: "ffmpeg" if name == "ffmpeg" else None)
    def fake_run(cmd, **kwargs):
        output = Path(cmd[-1])
        if "broken.mkv" in " ".join(str(value) for value in cmd):
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"bad codec")
        output.write_bytes(b"converted")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")
    monkeypatch.setattr("subforge.library.subprocess.run", fake_run)

    result = store.import_rj_folder(folder, rj_code="rj01499022", title="   ")

    assert result.status == "partial"
    assert result.imported_count == 3
    assert result.failed_count == 1
    assert result.skipped_count == 1
    item = store.get_item(result.item_id)
    assert item.title == "RJ01499022"
    assert [track.original_relative_path for track in item.tracks] == [
        "movie.mp4", "本篇/01.m4a", "特典/01.m4a",
    ]
    assert len({track.media for track in item.tracks}) == 3
    assert any(track.media.endswith("movie.m4a") for track in item.tracks)


def test_recently_used_creators_are_persisted_and_sorted_first(tmp_path):
    root = tmp_path / "Library"
    store = LibraryStore.initialize(root)
    first = store.create_creator("Alpha", CreatorKind.VOICE_ACTOR)
    second = store.create_creator("Beta", CreatorKind.VOICE_ACTOR)

    store.touch_creators([first.creator_id])
    store.close()

    reopened = LibraryStore.open(root)
    assert [creator.creator_id for creator in reopened.list_creators()] == [
        first.creator_id,
        second.creator_id,
    ]
    assert reopened.list_creators()[0].last_used_at is not None


def test_url_import_source_is_immutable_and_tracks_generated_media(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")

    imported = store.import_audio(ImportRequest(
        source=audio,
        kind=ItemKind.STREAM_ARCHIVE,
        title="Stream",
        author="Actor",
        source_url="https://example.com/video/1",
    ))

    item = store.get_item(imported.item_id)
    assert len(item.sources) == 1
    assert item.sources[0].url == "https://example.com/video/1"
    assert item.sources[0].track_ids == [imported.track_id]
    assert item.sources[0].source_type == "url"


def test_track_can_be_renamed_with_subtitles_and_resume_reset(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    source = tmp_path / "old.mp3"
    source.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000901"
    ))
    store.track_subtitle_path(imported.track_id, "ja").write_text("source", encoding="utf-8")
    store.track_subtitle_path(imported.track_id, "zh").write_text("target", encoding="utf-8")
    (store.track_resume_dir(imported.track_id) / "state.json").write_text(
        json.dumps({"media": {"path": imported.track_id}}), encoding="utf-8"
    )

    track = store.rename_track(imported.track_id, "new title.mp3")

    assert track.media == "media/new title.mp3"
    assert store.track_media_path(imported.track_id).name == "new title.mp3"
    assert store.track_subtitle_path(imported.track_id, "ja").read_text(encoding="utf-8") == "source"
    assert store.track_subtitle_path(imported.track_id, "zh").read_text(encoding="utf-8") == "target"
    assert list(store.track_resume_dir(imported.track_id).glob("*.json")) == []


def test_track_delete_moves_assets_to_trash_and_removes_metadata(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    source = tmp_path / "delete.mp3"
    source.write_bytes(b"audio")
    imported = store.import_audio(ImportRequest(
        source=source, kind=ItemKind.RJ_WORK, title="Work", rj_code="RJ00000902"
    ))
    store.track_subtitle_path(imported.track_id, "ja").write_text("source", encoding="utf-8")

    store.trash_track(imported.track_id)

    with pytest.raises(KeyError):
        store.get_track(imported.track_id)
    trash_entries = list((store.root / ".trash").glob(f"track-{imported.track_id}-*"))
    assert len(trash_entries) == 1
    assert (trash_entries[0] / "delete.mp3").exists()
    assert (trash_entries[0] / "delete.ja.srt").exists()
