import json
import shutil
from pathlib import Path

import pytest

from subforge.library import ImportRequest, ItemKind, LibraryStore


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
