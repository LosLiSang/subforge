from __future__ import annotations

from pathlib import Path

import pytest

from subforge.library import ImportRequest, ItemKind, LibraryStore
from subforge.models import SubtitleEntry
from subforge.subtitle_revision import SubtitleRevisionStore
from subforge.translate.srt_io import read_srt, write_srt


def _library_with_subtitles(tmp_path: Path):
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"audio")
    library = LibraryStore.initialize(tmp_path / "library")
    result = library.import_audio(ImportRequest(
        source=source,
        kind=ItemKind.STREAM_ARCHIVE,
        title="测试直播",
        author="测试作者",
    ))
    track_id = result.track_id
    source_path = library.track_subtitle_path(track_id, "ja")
    target_path = library.track_subtitle_path(track_id, "zh")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    write_srt([
        SubtitleEntry(1, 0.0, 1.0, "原文一"),
        SubtitleEntry(2, 1.2, 2.0, "原文二"),
    ], source_path)
    write_srt([
        SubtitleEntry(1, 0.0, 1.0, "译文一"),
        SubtitleEntry(2, 1.2, 2.0, "译文二"),
    ], target_path)
    return library, track_id, source_path, target_path


def test_commit_updates_both_subtitles_and_creates_baseline(tmp_path):
    library, track_id, source_path, target_path = _library_with_subtitles(tmp_path)
    store = SubtitleRevisionStore(library, duration_resolver=lambda _path: 10.0)

    document = store.load(track_id)
    document.source_entries[0].text = "修正原文"
    document.target_entries[0].text = "修正译文"
    committed = store.commit(track_id, document.source_entries, document.target_entries)

    assert read_srt(source_path)[0].text == "修正原文"
    assert read_srt(target_path)[0].text == "修正译文"
    assert committed.source_entries[0].index == 1
    library.close()


def test_commit_rolls_back_both_files_when_second_replace_fails(tmp_path):
    library, track_id, source_path, target_path = _library_with_subtitles(tmp_path)
    calls = 0

    def fail_second_replace(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("target replace failed")
        source.replace(target)

    store = SubtitleRevisionStore(
        library,
        duration_resolver=lambda _path: 10.0,
        replace_new=fail_second_replace,
    )
    document = store.load(track_id)
    document.source_entries[0].text = "不应保存的原文"
    document.target_entries[0].text = "不应保存的译文"

    with pytest.raises(OSError, match="target replace failed"):
        store.commit(track_id, document.source_entries, document.target_entries)

    assert read_srt(source_path)[0].text == "原文一"
    assert read_srt(target_path)[0].text == "译文一"
    library.close()


def test_restore_previous_and_baseline(tmp_path):
    library, track_id, source_path, target_path = _library_with_subtitles(tmp_path)
    store = SubtitleRevisionStore(library, duration_resolver=lambda _path: 10.0)

    first = store.load(track_id)
    first.source_entries[0].text = "第一次原文"
    first.target_entries[0].text = "第一次译文"
    store.commit(track_id, first.source_entries, first.target_entries)

    second = store.load(track_id)
    second.source_entries[0].text = "第二次原文"
    second.target_entries[0].text = "第二次译文"
    store.commit(track_id, second.source_entries, second.target_entries)

    store.restore_previous(track_id)
    assert read_srt(source_path)[0].text == "第一次原文"
    assert read_srt(target_path)[0].text == "第一次译文"

    store.restore_baseline(track_id)
    assert read_srt(source_path)[0].text == "原文一"
    assert read_srt(target_path)[0].text == "译文一"
    library.close()


def test_merge_split_and_delete_keep_source_target_aligned(tmp_path):
    library, track_id, _source_path, _target_path = _library_with_subtitles(tmp_path)
    store = SubtitleRevisionStore(library, duration_resolver=lambda _path: 10.0)

    merged = store.merge(track_id, 1, 2, source_text="合并原文", target_text="合并译文")
    assert [(e.start, e.end, e.text) for e in merged.source_entries] == [(0.0, 2.0, "合并原文")]
    assert merged.target_entries[0].text == "合并译文"

    split = store.split(
        track_id,
        1,
        split_time=1.0,
        source_texts=("前半原文", "后半原文"),
        target_texts=("前半译文", "后半译文"),
    )
    assert [(e.start, e.end, e.text) for e in split.source_entries] == [
        (0.0, 1.0, "前半原文"), (1.0, 2.0, "后半原文")
    ]

    deleted = store.delete(track_id, 1)
    # 删除后开头留下 [0,1) 无字幕区间 → 自动补一条空文本条目
    assert len(deleted.source_entries) == len(deleted.target_entries) == 2
    assert deleted.source_entries[0].text == ""
    assert deleted.source_entries[0].start == 0.0
    assert deleted.source_entries[1].text == "后半原文"
    library.close()


def test_replace_range_preserves_entries_outside_candidate_window(tmp_path):
    library, track_id, _source_path, _target_path = _library_with_subtitles(tmp_path)
    store = SubtitleRevisionStore(library, duration_resolver=lambda _path: 10.0)

    replaced = store.replace_range(
        track_id,
        target_start=0.0,
        target_end=1.0,
        source_entries=[SubtitleEntry(1, 0.1, 0.8, "候选原文")],
        target_entries=[SubtitleEntry(1, 0.1, 0.8, "候选译文")],
    )

    assert [entry.text for entry in replaced.source_entries] == ["候选原文", "原文二"]
    assert [entry.text for entry in replaced.target_entries] == ["候选译文", "译文二"]
    assert replaced.source_entries[1].start == 1.2
    library.close()


def test_leading_gap_is_filled_with_empty_entry_and_empty_text_allowed(tmp_path):
    library, track_id, _source_path, _target_path = _library_with_subtitles(tmp_path)
    # 重写为开头有 2 秒无字幕区间的字幕
    store = SubtitleRevisionStore(library, duration_resolver=lambda _path: 10.0)
    source_path = library.track_subtitle_path(track_id, "ja")
    target_path = library.track_subtitle_path(track_id, "zh")
    write_srt([
        SubtitleEntry(1, 2.0, 3.0, "原文"),
    ], source_path)
    write_srt([
        SubtitleEntry(1, 2.0, 3.0, "译文"),
    ], target_path)

    document = store.load(track_id)
    document.source_entries[0].text = ""  # 手动改成空
    committed = store.commit(track_id, document.source_entries, document.target_entries)

    # 首条前 2 秒空段被自动补上空条目；手动改空也保留
    assert committed.source_entries[0].start == 0.0
    assert committed.source_entries[0].end == 2.0
    assert committed.source_entries[0].text == ""
    assert committed.source_entries[1].text == ""
    assert committed.target_entries[0].text == ""
    from subforge.translate.srt_io import read_srt as _read
    assert _read(source_path)[0].text.strip() == ""
    library.close()


def test_structure_operations_reject_unaligned_documents(tmp_path):
    library, track_id, _source_path, target_path = _library_with_subtitles(tmp_path)
    write_srt([SubtitleEntry(1, 0.0, 2.0, "只有一条译文")], target_path)
    store = SubtitleRevisionStore(library, duration_resolver=lambda _path: 10.0)

    with pytest.raises(ValueError, match="对应关系"):
        store.merge(track_id, 1, 2, source_text="合并", target_text="合并")
    library.close()


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([SubtitleEntry(1, -0.1, 1.0, "文本")], "不得为负数"),
        ([SubtitleEntry(1, 1.0, 1.0, "文本")], "必须早于"),
        ([SubtitleEntry(1, 0.0, 11.0, "文本")], "超过媒体时长"),
        ([SubtitleEntry(1, 0.0, 2.0, "文本"), SubtitleEntry(2, 1.5, 3.0, "文本")], "重叠"),
    ],
)
def test_commit_rejects_invalid_timeline(tmp_path, entries, message):
    library, track_id, _source_path, _target_path = _library_with_subtitles(tmp_path)
    store = SubtitleRevisionStore(library, duration_resolver=lambda _path: 10.0)

    with pytest.raises(ValueError, match=message):
        store.commit(track_id, entries, [SubtitleEntry(1, 0.0, 1.0, "译文")])
    library.close()
