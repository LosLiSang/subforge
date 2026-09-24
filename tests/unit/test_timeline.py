from subforge.models import SubtitleEntry
from subforge.timeline import adjust_gaps, merge_short_entries


class TestMergeShortEntries:
    def test_empty(self):
        assert merge_short_entries([]) == []

    def test_single_entry_normal(self):
        entries = [SubtitleEntry(index=1, start=0.0, end=2.0, text="hello")]
        result = merge_short_entries(entries)
        assert len(result) == 1
        assert result[0].text == "hello"

    def test_merge_short_with_next(self):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=0.2, text="short"),
            SubtitleEntry(index=2, start=0.3, end=2.0, text="normal"),
        ]
        result = merge_short_entries(entries, min_duration=0.5)
        assert len(result) == 1
        assert result[0].start == 0.0
        assert result[0].end == 2.0
        assert result[0].text == "short\nnormal"

    def test_no_merge_when_exceeds_max(self):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=0.2, text="short"),
            SubtitleEntry(index=2, start=0.3, end=10.0, text="very long"),
        ]
        result = merge_short_entries(entries, min_duration=0.5, max_duration=5.0)
        # Merged duration would be 10.0, > max_duration, so no merge
        assert len(result) == 2

    def test_last_entry_short_merged_with_prev(self):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=2.0, text="first"),
            SubtitleEntry(index=2, start=2.1, end=2.3, text="tiny"),
        ]
        result = merge_short_entries(entries, min_duration=0.5)
        assert len(result) == 1
        assert result[0].text == "first\ntiny"
        assert result[0].start == 0.0
        assert result[0].end == 2.3

    def test_all_normal_no_merge(self):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=1.0, text="a"),
            SubtitleEntry(index=2, start=1.0, end=2.0, text="b"),
            SubtitleEntry(index=3, start=2.0, end=3.0, text="c"),
        ]
        result = merge_short_entries(entries, min_duration=0.5)
        assert len(result) == 3

    def test_reindex(self):
        entries = [
            SubtitleEntry(index=5, start=0.0, end=0.2, text="x"),
            SubtitleEntry(index=6, start=0.3, end=0.5, text="y"),
        ]
        result = merge_short_entries(entries, min_duration=0.5)
        assert len(result) == 1
        assert result[0].index == 1  # reindexed from 1


class TestAdjustGaps:
    def test_empty(self):
        assert adjust_gaps([]) == []

    def test_single_entry(self):
        entries = [SubtitleEntry(index=1, start=0.0, end=1.0, text="a")]
        result = adjust_gaps(entries)
        assert result[0].end == 1.0

    def test_close_gap_extended(self):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=1.0, text="a"),
            SubtitleEntry(index=2, start=1.05, end=2.0, text="b"),
        ]
        result = adjust_gaps(entries, max_gap=0.1)
        assert result[0].end == 1.05  # extended to close gap

    def test_large_gap_not_extended(self):
        entries = [
            SubtitleEntry(index=1, start=0.0, end=1.0, text="a"),
            SubtitleEntry(index=2, start=3.0, end=4.0, text="b"),
        ]
        result = adjust_gaps(entries, max_gap=0.1)
        assert result[0].end == 1.0  # unchanged

    def test_no_backwards_extension(self):
        # gap is negative (overlap) → don't change
        entries = [
            SubtitleEntry(index=1, start=0.0, end=1.5, text="a"),
            SubtitleEntry(index=2, start=1.0, end=2.0, text="b"),
        ]
        result = adjust_gaps(entries, max_gap=0.1)
        assert result[0].end == 1.5  # unchanged (overlap, not gap)
