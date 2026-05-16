from pathlib import Path

import pytest

from subforge.scanner import scan_paths


class TestScanPaths:
    def test_single_file(self, tmp_path):
        mp3 = tmp_path / "test.mp3"
        mp3.write_text("dummy")
        result = scan_paths([mp3])
        assert result == [mp3]

    def test_multiple_files(self, tmp_path):
        a = tmp_path / "a.mp3"
        b = tmp_path / "b.mp4"
        a.write_text("")
        b.write_text("")
        result = scan_paths([a, b])
        assert len(result) == 2
        assert a in result
        assert b in result

    def test_directory_recursive(self, tmp_path):
        (tmp_path / "sub").mkdir()
        a = tmp_path / "a.mp3"
        b = tmp_path / "sub" / "b.wav"
        a.write_text("")
        b.write_text("")
        result = scan_paths([tmp_path])
        assert len(result) == 2
        assert a in result
        assert b in result

    def test_mixed_input(self, tmp_path):
        dir_path = tmp_path / "extra"
        dir_path.mkdir()
        f1 = tmp_path / "x.mp3"
        f2 = dir_path / "y.m4a"
        f1.write_text("")
        f2.write_text("")
        result = scan_paths([f1, dir_path])
        assert len(result) == 2
        assert f1 in result
        assert f2 in result

    def test_unsupported_format_filtered(self, tmp_path, capsys):
        mp3 = tmp_path / "keep.mp3"
        txt = tmp_path / "skip.txt"
        png = tmp_path / "skip.png"
        mp3.write_text("")
        txt.write_text("")
        png.write_text("")
        result = scan_paths([tmp_path])
        assert result == [mp3]
        stderr = capsys.readouterr().err
        assert "unsupported format" in stderr

    def test_all_supported_formats(self, tmp_path):
        files = []
        for ext in [".mp3", ".mp4", ".wav", ".m4a", ".flac"]:
            f = tmp_path / f"audio{ext}"
            f.write_text("")
            files.append(f)
        result = scan_paths([tmp_path])
        assert len(result) == 5

    def test_not_found(self, tmp_path, capsys):
        missing = tmp_path / "nope.mp3"
        result = scan_paths([missing])
        assert result == []
        assert "not found" in capsys.readouterr().err

    def test_deduplication(self, tmp_path):
        f = tmp_path / "dup.mp3"
        f.write_text("")
        result = scan_paths([f, f, tmp_path])
        assert result == [f]

    def test_sorted_output(self, tmp_path):
        c = tmp_path / "c.mp3"
        a = tmp_path / "a.mp3"
        b = tmp_path / "b.mp3"
        for x in [c, a, b]:
            x.write_text("")
        result = scan_paths([tmp_path])
        assert result == [a, b, c]  # sorted
