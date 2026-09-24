from pathlib import Path

import pytest

from subforge.models import SubtitleEntry
from subforge.translate.srt_io import (
    _format_timestamp,
    _parse_timestamp,
    read_srt,
    write_srt,
)


class TestFormatTimestamp:
    def test_zero(self):
        assert _format_timestamp(0.0) == "00:00:00,000"

    def test_seconds_only(self):
        assert _format_timestamp(5.5) == "00:00:05,500"

    def test_minutes(self):
        assert _format_timestamp(125.750) == "00:02:05,750"

    def test_hours(self):
        assert _format_timestamp(3661.001) == "01:01:01,001"

    def test_millis_rounding(self):
        assert _format_timestamp(0.9995) == "00:00:01,000"


class TestParseTimestamp:
    def test_zero(self):
        assert _parse_timestamp("00:00:00,000") == 0.0

    def test_seconds(self):
        assert _parse_timestamp("00:00:05,500") == 5.5

    def test_minutes(self):
        assert _parse_timestamp("00:02:05,750") == 125.75

    def test_hours(self):
        assert _parse_timestamp("01:01:01,001") == 3661.001

    def test_invalid(self):
        with pytest.raises(ValueError):
            _parse_timestamp("not a timestamp")


class TestWriteReadRoundtrip:
    def test_write_and_read(self, tmp_path):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=2.5, text="こんにちは"),
            SubtitleEntry(index=2, start=2.5, end=5.0, text="さようなら"),
        ]
        path = tmp_path / "test.srt"
        write_srt(entries, path)

        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "こんにちは" in content
        assert "00:00:00,000 --> 00:00:02,500" in content

        parsed = read_srt(path)
        assert len(parsed) == 2
        assert parsed[0].index == 1
        assert parsed[0].start == 0.0
        assert parsed[0].end == 2.5
        assert parsed[0].text == "こんにちは"
        assert parsed[1].index == 2
        assert parsed[1].text == "さようなら"

    def test_multiline_text(self, tmp_path):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=1.0, text="Line 1\nLine 2"),
        ]
        path = tmp_path / "multiline.srt"
        write_srt(entries, path)
        parsed = read_srt(path)
        assert parsed[0].text == "Line 1\nLine 2"

    def test_empty_list(self, tmp_path):
        path = tmp_path / "empty.srt"
        write_srt([], path)
        assert path.read_text() == ""

    def test_read_srt_caches_by_mtime(self, tmp_path):
        """read_srt 进程内缓存：同文件重复读取返回副本且不重新解析；
        修改文件（mtime 变化）后失效，读到新内容。"""
        from subforge.translate.srt_io import _srt_cache

        path = tmp_path / "cached.srt"
        write_srt([SubtitleEntry(index=1, start=0.0, end=1.0, text="one")], path)
        first = read_srt(path)
        second = read_srt(path)
        assert first == second
        assert first is not second  # 返回副本，未暴露内部缓存对象

        # 修改文件后 mtime 应变化；某些文件系统 mtime 精度有限，强制更新以保证失效
        import os
        import time

        write_srt([SubtitleEntry(index=1, start=0.0, end=2.0, text="two")], path)
        os.utime(path, (time.time() + 5, time.time() + 5))
        refreshed = read_srt(path)
        assert refreshed[0].text == "two"

    def test_read_srt_mutation_does_not_poison_cache(self, tmp_path):
        """调用方原地修改返回列表不污染缓存：缓存键命中的是缓存副本。"""
        path = tmp_path / "mutable.srt"
        write_srt([SubtitleEntry(index=1, start=0.0, end=1.0, text="hello")], path)
        first = read_srt(path)
        first[0].text = "hacked"
        second = read_srt(path)
        assert second[0].text == "hello"
