from __future__ import annotations

import copy
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from subforge.asr.engine import _audio_duration_seconds
from subforge.library import LibraryStore
from subforge.models import SubtitleEntry
from subforge.translate.srt_io import read_srt, write_srt


@dataclass
class SubtitleDocument:
    source_language: str
    target_language: str
    source_entries: list[SubtitleEntry]
    target_entries: list[SubtitleEntry]


class SubtitleRevisionStore:
    """Validate and atomically revise a Track's source/target subtitles.

    Formal subtitle files remain the authority.  The store owns the on-disk
    snapshot layout and guarantees that callers never observe only one side of
    a two-file revision.
    """

    def __init__(
        self,
        library: LibraryStore,
        *,
        duration_resolver: Callable[[Path], float] = _audio_duration_seconds,
        replace_new: Callable[[Path, Path], None] | None = None,
    ) -> None:
        self.library = library
        self._duration_resolver = duration_resolver
        self._replace_new = replace_new or self._replace_path

    @staticmethod
    def _replace_path(source: Path, target: Path) -> None:
        os.replace(source, target)

    def load(self, track_id: str) -> SubtitleDocument:
        _item, track = self.library.get_track(track_id)

        def clean(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
            return [
                SubtitleEntry(entry.index, entry.start, entry.end, entry.text.strip())
                for entry in entries
            ]

        return SubtitleDocument(
            source_language=track.source_language,
            target_language=track.target_language,
            source_entries=clean(self._read_if_present(
                self.library.track_subtitle_path(track_id, track.source_language)
            )),
            target_entries=clean(self._read_if_present(
                self.library.track_subtitle_path(track_id, track.target_language)
            )),
        )

    def commit(
        self,
        track_id: str,
        source_entries: list[SubtitleEntry],
        target_entries: list[SubtitleEntry],
    ) -> SubtitleDocument:
        _item, track = self.library.get_track(track_id)
        media_path = self.library.track_media_path(track_id)
        duration = self._duration_resolver(media_path)
        source = self._normalize_and_validate(source_entries, duration, "源语言字幕")
        target = self._normalize_and_validate(target_entries, duration, "翻译字幕")
        source = self._with_leading_gap_entry(source)
        target = self._with_leading_gap_entry(target)

        source_path = self.library.track_subtitle_path(track_id, track.source_language)
        target_path = self.library.track_subtitle_path(track_id, track.target_language)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        pairs = [(source_path, source), (target_path, target)]

        self._snapshot_current(track_id, track.source_language, source_path)
        self._snapshot_current(track_id, track.target_language, target_path)
        self._commit_files(pairs)
        return self.load(track_id)

    def replace_range(
        self,
        track_id: str,
        *,
        target_start: float,
        target_end: float,
        source_entries: list[SubtitleEntry],
        target_entries: list[SubtitleEntry],
    ) -> SubtitleDocument:
        document = self._aligned_document(track_id)
        if target_start < 0 or target_start >= target_end:
            raise ValueError("候选替换范围无效")
        if not source_entries or len(source_entries) != len(target_entries):
            raise ValueError("候选源字幕与翻译字幕对应关系不明确")
        for source, target in zip(source_entries, target_entries, strict=True):
            if source.start < target_start or source.end > target_end:
                raise ValueError("候选字幕超出目标替换范围")
            if abs(source.start - target.start) > 0.001 or abs(source.end - target.end) > 0.001:
                raise ValueError("候选源字幕与翻译字幕时间轴不一致")

        kept_source = [
            entry for entry in document.source_entries
            if entry.end <= target_start or entry.start >= target_end
        ]
        kept_target = [
            entry for entry in document.target_entries
            if entry.end <= target_start or entry.start >= target_end
        ]
        source = sorted([*kept_source, *source_entries], key=lambda entry: (entry.start, entry.end))
        target = sorted([*kept_target, *target_entries], key=lambda entry: (entry.start, entry.end))
        return self.commit(track_id, source, target)

    def merge(
        self,
        track_id: str,
        start_index: int,
        end_index: int,
        *,
        source_text: str,
        target_text: str,
    ) -> SubtitleDocument:
        document = self._aligned_document(track_id)
        if start_index < 1 or end_index < start_index or end_index > len(document.source_entries):
            raise ValueError("合并字幕范围无效")
        first = document.source_entries[start_index - 1]
        last = document.source_entries[end_index - 1]
        source = document.source_entries[:start_index - 1] + [
            SubtitleEntry(start_index, first.start, last.end, source_text)
        ] + document.source_entries[end_index:]
        target = document.target_entries[:start_index - 1] + [
            SubtitleEntry(start_index, first.start, last.end, target_text)
        ] + document.target_entries[end_index:]
        return self.commit(track_id, source, target)

    def split(
        self,
        track_id: str,
        index: int,
        *,
        split_time: float,
        source_texts: tuple[str, str],
        target_texts: tuple[str, str],
    ) -> SubtitleDocument:
        document = self._aligned_document(track_id)
        if index < 1 or index > len(document.source_entries):
            raise ValueError("拆分字幕序号不存在")
        current = document.source_entries[index - 1]
        if not current.start < split_time < current.end:
            raise ValueError("拆分时间必须位于原字幕范围内")
        source_parts = [
            SubtitleEntry(index, current.start, split_time, source_texts[0]),
            SubtitleEntry(index + 1, split_time, current.end, source_texts[1]),
        ]
        target_parts = [
            SubtitleEntry(index, current.start, split_time, target_texts[0]),
            SubtitleEntry(index + 1, split_time, current.end, target_texts[1]),
        ]
        source = document.source_entries[:index - 1] + source_parts + document.source_entries[index:]
        target = document.target_entries[:index - 1] + target_parts + document.target_entries[index:]
        return self.commit(track_id, source, target)

    def delete(self, track_id: str, index: int) -> SubtitleDocument:
        document = self._aligned_document(track_id)
        if index < 1 or index > len(document.source_entries):
            raise ValueError("删除字幕序号不存在")
        source = document.source_entries[:index - 1] + document.source_entries[index:]
        target = document.target_entries[:index - 1] + document.target_entries[index:]
        return self.commit(track_id, source, target)

    def restore_previous(self, track_id: str) -> SubtitleDocument:
        return self._restore(track_id, "previous")

    def restore_baseline(self, track_id: str) -> SubtitleDocument:
        return self._restore(track_id, "baseline")

    def _aligned_document(self, track_id: str) -> SubtitleDocument:
        document = self.load(track_id)
        if len(document.source_entries) != len(document.target_entries):
            raise ValueError("源字幕与翻译字幕对应关系不明确，不能执行结构操作")
        for source, target in zip(document.source_entries, document.target_entries, strict=True):
            if abs(source.start - target.start) > 0.001 or abs(source.end - target.end) > 0.001:
                raise ValueError("源字幕与翻译字幕对应关系不明确，不能执行结构操作")
        return document

    def _restore(self, track_id: str, snapshot: str) -> SubtitleDocument:
        _item, track = self.library.get_track(track_id)
        directory = self._revision_directory(track_id)
        source_path = directory / f"{snapshot}.{track.source_language}.srt"
        target_path = directory / f"{snapshot}.{track.target_language}.srt"
        if not source_path.is_file() or not target_path.is_file():
            raise FileNotFoundError(f"没有可恢复的{snapshot}字幕快照")
        return self.commit(track_id, read_srt(source_path), read_srt(target_path))

    def _revision_directory(self, track_id: str) -> Path:
        item, _track = self.library.get_track(track_id)
        directory = (
            self.library.item_directory(item.item_id)
            / ".subforge"
            / "tracks"
            / track_id
            / "subtitles"
        )
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _snapshot_current(self, track_id: str, language: str, current: Path) -> None:
        directory = self._revision_directory(track_id)
        baseline = directory / f"baseline.{language}.srt"
        previous = directory / f"previous.{language}.srt"
        if current.is_file():
            if not baseline.exists():
                self._copy_durable(current, baseline)
            self._copy_durable(current, previous)
        else:
            previous.unlink(missing_ok=True)

    @staticmethod
    def _copy_durable(source: Path, target: Path) -> None:
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        shutil.copyfile(source, temporary)
        with temporary.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)

    def _commit_files(self, pairs: list[tuple[Path, list[SubtitleEntry]]]) -> None:
        temporary: dict[Path, Path] = {}
        rollback: dict[Path, Path] = {}
        try:
            for final, entries in pairs:
                final.parent.mkdir(parents=True, exist_ok=True)
                handle = tempfile.NamedTemporaryFile(
                    prefix=f".{final.name}.", suffix=".tmp", dir=final.parent, delete=False
                )
                handle.close()
                temp_path = Path(handle.name)
                write_srt(entries, temp_path)
                with temp_path.open("r+b") as stream:
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary[final] = temp_path

            for final, _entries in pairs:
                if final.exists():
                    backup = final.with_name(f".{final.name}.{uuid4().hex}.rollback")
                    os.replace(final, backup)
                    rollback[final] = backup

            for final, _entries in pairs:
                self._replace_new(temporary[final], final)
                temporary.pop(final, None)
        except Exception:
            for final, _entries in pairs:
                if final.exists():
                    final.unlink(missing_ok=True)
            for final, backup in rollback.items():
                if backup.exists():
                    os.replace(backup, final)
            raise
        finally:
            for path in temporary.values():
                path.unlink(missing_ok=True)
            for path in rollback.values():
                path.unlink(missing_ok=True)

    @staticmethod
    def _read_if_present(path: Path) -> list[SubtitleEntry]:
        return read_srt(path) if path.is_file() else []

    @staticmethod
    def _normalize_and_validate(
        entries: list[SubtitleEntry],
        media_duration: float,
        label: str,
    ) -> list[SubtitleEntry]:
        normalized: list[SubtitleEntry] = []
        previous_end = -1.0
        for position, original in enumerate(copy.deepcopy(entries), start=1):
            # 允许空文本条目：用于开头无语音区间或手动标记为空的段落
            text = original.text.strip()
            start = float(original.start)
            end = float(original.end)
            if start < 0 or end < 0:
                raise ValueError(f"{label}时间不得为负数")
            if start >= end:
                raise ValueError(f"{label}开始时间必须早于结束时间")
            if media_duration > 0 and end > media_duration + 0.001:
                raise ValueError(f"{label}结束时间超过媒体时长")
            if start < previous_end - 0.001:
                raise ValueError(f"{label}第 {position} 条与前一条字幕重叠")
            normalized.append(SubtitleEntry(position, round(start, 3), round(end, 3), text))
            previous_end = end
        return normalized

    @staticmethod
    def _with_leading_gap_entry(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
        """开头存在 ≥0.5s 无字幕区间时自动补一条空文本条目，覆盖 [0, 首条开始]。"""
        if not entries or entries[0].start < 0.5:
            return entries
        leading = SubtitleEntry(0, 0.0, round(entries[0].start, 3), "")
        return [leading, *entries]
