from __future__ import annotations

from subforge.models import SubtitleEntry


def merge_short_entries(
    entries: list[SubtitleEntry],
    min_duration: float = 0.5,
    max_duration: float = 5.0,
) -> list[SubtitleEntry]:
    """Merge subtitle entries that are shorter than min_duration seconds.

    A short entry is merged into its next neighbor. If it's the last entry
    and short, it's merged into the previous one. Resulting merged entry
    must not exceed max_duration, otherwise the merge is skipped.
    """
    if not entries:
        return []

    result: list[SubtitleEntry] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        duration = entry.end - entry.start

        if duration < min_duration and i + 1 < len(entries):
            # Merge with next entry
            next_entry = entries[i + 1]
            merged_duration = next_entry.end - entry.start
            if merged_duration <= max_duration:
                merged = SubtitleEntry(
                    index=len(result) + 1,
                    start=entry.start,
                    end=next_entry.end,
                    text=f"{entry.text}\n{next_entry.text}",
                )
                result.append(merged)
                i += 2
                continue
        elif duration < min_duration and i == len(entries) - 1 and result:
            # Last entry is short: merge with previous
            prev = result[-1]
            merged_duration = entry.end - prev.start
            if merged_duration <= max_duration:
                result[-1] = SubtitleEntry(
                    index=prev.index,
                    start=prev.start,
                    end=entry.end,
                    text=f"{prev.text}\n{entry.text}",
                )
                i += 1
                continue

        result.append(SubtitleEntry(
            index=len(result) + 1,
            start=entry.start,
            end=entry.end,
            text=entry.text,
        ))
        i += 1

    return result


def adjust_gaps(
    entries: list[SubtitleEntry],
    max_gap: float = 0.1,
) -> list[SubtitleEntry]:
    """Extend the end time of each entry to close small gaps with the next entry.

    If the gap between entry[i].end and entry[i+1].start is less than max_gap,
    entry[i].end is extended to match entry[i+1].start.
    """
    if len(entries) < 2:
        return entries

    result: list[SubtitleEntry] = []
    for i, entry in enumerate(entries):
        if i < len(entries) - 1:
            next_start = entries[i + 1].start
            gap = next_start - entry.end
            if 0 < gap <= max_gap:
                entry = SubtitleEntry(
                    index=entry.index,
                    start=entry.start,
                    end=next_start,
                    text=entry.text,
                )
        result.append(entry)
    return result
