from unittest.mock import AsyncMock

import pytest

from subforge.config import Config
from subforge.models import SubtitleEntry
from subforge.translate.context import (
    _build_user_message,
    _parse_translations,
    build_batches,
    translate_all,
)


def make_entries(n: int, start_time: float = 0.0, gap: float = 2.0) -> list[SubtitleEntry]:
    """Helper to create n subtitle entries."""
    entries = []
    for i in range(n):
        entries.append(SubtitleEntry(
            index=i + 1,
            start=start_time,
            end=start_time + gap - 0.1,
            text=f"Entry {i + 1} text",
        ))
        start_time += gap
    return entries


class TestBuildBatches:
    def test_single_batch(self):
        entries = make_entries(5)
        batches = build_batches(entries, batch_size=10, context_size=3)
        assert len(batches) == 1
        assert len(batches[0]["batch"]) == 5
        assert batches[0]["prev_context"] == []
        assert batches[0]["next_context"] == []

    def test_multiple_batches(self):
        entries = make_entries(45)
        batches = build_batches(entries, batch_size=20, context_size=10)
        assert len(batches) == 3
        # batch 1: 20 entries
        assert len(batches[0]["batch"]) == 20
        # batch 2: 20 entries
        assert len(batches[1]["batch"]) == 20
        # batch 3: 5 entries
        assert len(batches[2]["batch"]) == 5

    def test_context_windows(self):
        entries = make_entries(50)
        batches = build_batches(entries, batch_size=20, context_size=10)

        # Batch 1: no prev context, has next context
        assert len(batches[0]["prev_context"]) == 0
        assert len(batches[0]["next_context"]) == 10

        # Batch 2: has both prev and next context
        assert len(batches[1]["prev_context"]) == 10
        assert len(batches[1]["next_context"]) == 10

        # Batch 3 (last): has prev context, no next
        assert len(batches[2]["prev_context"]) == 10
        assert len(batches[2]["next_context"]) == 0

    def test_exact_fit(self):
        entries = make_entries(20)
        batches = build_batches(entries, batch_size=20, context_size=5)
        assert len(batches) == 1
        assert len(batches[0]["batch"]) == 20

    def test_overlap_coverage(self):
        """Adjacent batches should share context region."""
        entries = make_entries(30)
        batches = build_batches(entries, batch_size=20, context_size=10)
        # Batch 1: entries[0:20], Batch 2: entries[20:30]
        # Batch 2's prev_context should be entries[10:20]
        batch2_prev = batches[1]["prev_context"]
        assert batch2_prev[0].index == 11  # entries[10]
        assert batch2_prev[-1].index == 20  # entries[19]


class TestBuildUserMessage:
    def test_basic_batch(self):
        batch = [
            SubtitleEntry(index=1, start=0.0, end=1.5, text="こんにちは"),
            SubtitleEntry(index=2, start=1.5, end=3.0, text="元気ですか"),
        ]
        msg = _build_user_message(batch, [], [])
        assert "こんにちは" in msg
        assert "元気ですか" in msg
        assert "Entries to translate" in msg
        assert "Previous entries" not in msg

    def test_with_prev_context(self):
        batch = [SubtitleEntry(index=3, start=4.0, end=5.0, text="New text")]
        prev = [SubtitleEntry(index=1, start=0.0, end=2.0, text="Old")]
        msg = _build_user_message(batch, prev, [])
        assert "Previous entries" in msg
        assert "Old" in msg
        assert "New text" in msg

    def test_with_next_context(self):
        batch = [SubtitleEntry(index=1, start=0.0, end=1.0, text="Current")]
        next_entries = [SubtitleEntry(index=2, start=1.0, end=2.0, text="Future")]
        msg = _build_user_message(batch, [], next_entries)
        assert "Upcoming entries" in msg
        assert "do NOT translate" in msg
        assert "Future" in msg

    def test_full_context(self):
        batch = [SubtitleEntry(index=2, start=1.0, end=2.0, text="Middle")]
        prev = [SubtitleEntry(index=1, start=0.0, end=1.0, text="First")]
        next_entries = [SubtitleEntry(index=3, start=2.0, end=3.0, text="Last")]
        msg = _build_user_message(batch, prev, next_entries)
        assert "Previous entries" in msg
        assert "Entries to translate" in msg
        assert "Upcoming entries" in msg


class TestParseTranslations:
    def test_parse_numbered(self):
        batch = [
            SubtitleEntry(index=1, start=0.0, end=1.0, text="a"),
            SubtitleEntry(index=2, start=1.0, end=2.0, text="b"),
        ]
        response = "[1] 你好\n[2] 世界"
        result = _parse_translations(response, batch)
        assert result == ["你好", "世界"]

    def test_parse_with_extra_lines(self):
        batch = [SubtitleEntry(index=5, start=0.0, end=1.0, text="x")]
        response = "Some notes\n[5] 翻译\nMore notes"
        result = _parse_translations(response, batch)
        assert result == ["翻译"]

    def test_missing_entry_fallback(self):
        batch = [SubtitleEntry(index=99, start=0.0, end=1.0, text="x")]
        response = "No bracket here"
        result = _parse_translations(response, batch)
        assert result == [""]  # fallback empty


class TestTranslateAll:
    @pytest.fixture
    def config(self):
        return Config(
            source_lang="ja",
            target_lang="zh",
            batch_size=10,
            context_size=3,
        )

    async def test_translate_all(self, config):
        entries = make_entries(5)
        mock_translate = AsyncMock()
        mock_translate.return_value = "[1] 文本1\n[2] 文本2\n[3] 文本3\n[4] 文本4\n[5] 文本5"

        result = await translate_all(entries, config, mock_translate)

        assert len(result) == 5
        assert result[0].text == "文本1"
        assert result[1].text == "文本2"
        assert result[4].text == "文本5"
        # Should have made 1 call (5 entries < batch_size 10)
        assert mock_translate.call_count == 1

    async def test_translate_all_preserves_timestamps(self, config):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=2.5, text="こんにちは"),
        ]
        mock_translate = AsyncMock(return_value="[1] 你好")

        result = await translate_all(entries, config, mock_translate)

        assert result[0].start == 0.0
        assert result[0].end == 2.5
        assert result[0].text == "你好"

    async def test_multiple_batches(self, config):
        entries = make_entries(25)
        mock_translate = AsyncMock()
        # Return enough translations for each batch
        mock_translate.side_effect = [
            "\n".join(f"[{i}] text{i}" for i in range(1, 11)),
            "\n".join(f"[{i}] text{i}" for i in range(11, 21)),
            "\n".join(f"[{i}] text{i}" for i in range(21, 26)),
        ]

        result = await translate_all(entries, config, mock_translate)

        assert len(result) == 25
        assert mock_translate.call_count == 3
