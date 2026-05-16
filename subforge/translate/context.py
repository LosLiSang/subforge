from __future__ import annotations

import asyncio
import logging
from typing import Callable

from subforge.config import Config
from subforge.models import SubtitleEntry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a professional subtitle translator. Translate the following subtitle \
entries from {source_lang} to {target_lang}.

Guidelines:
- Preserve the original meaning and tone.
- Keep translations concise and natural in the target language.
- Maintain consistency with the provided context (previous translations).
- Output ONLY the translated text for each entry, one per line, \
in the same order as the input.
- Prefix each line with its entry index in brackets, like: [1] Translated text"""


def _build_user_message(
    batch: list[SubtitleEntry],
    prev_context: list[tuple[SubtitleEntry, str]],
    next_context: list[SubtitleEntry],
) -> str:
    """Build the user message with context and batch entries."""
    parts: list[str] = []

    if prev_context:
        parts.append("=== Previous translations (for context) ===")
        for entry, translated in prev_context:
            parts.append(f"[{entry.index}] Original: {entry.text}")
            parts.append(f"[{entry.index}] Translation: {translated}")
        parts.append("")

    parts.append("=== Entries to translate ===")
    for entry in batch:
        parts.append(f"[{entry.index}] {entry.text}")

    if next_context:
        parts.append("")
        parts.append("=== Upcoming entries (for context, do NOT translate) ===")
        for entry in next_context:
            parts.append(f"[{entry.index}] {entry.text}")

    return "\n".join(parts)


def _parse_translations(response: str, batch: list[SubtitleEntry]) -> list[str]:
    """Parse the LLM response to extract per-entry translations."""
    lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
    translations: list[str] = []

    for entry in batch:
        prefix = f"[{entry.index}]"
        found = False
        for line in lines:
            if line.startswith(prefix):
                text = line[len(prefix):].strip()
                translations.append(text)
                found = True
                break
        if not found:
            translations.append("")

    return translations


class _DependencyTracker:
    """Track which batches are ready to translate based on context dependencies.

    A batch is ready when all batches whose entries appear in its prev_context
    window have been translated.
    """

    def __init__(self, total_batches: int, batch_size: int, context_size: int) -> None:
        self._total = total_batches
        self._deps: dict[int, set[int]] = {i: set() for i in range(total_batches)}
        self._dependents: dict[int, set[int]] = {i: set() for i in range(total_batches)}
        self._done: set[int] = set()

        if context_size <= 0:
            return  # all batches independent

        for idx in range(total_batches):
            start = idx * batch_size
            prev_start = max(0, start - context_size)
            if prev_start < start:
                first_batch = prev_start // batch_size
                last_batch = min((start - 1) // batch_size, idx - 1)
                for dep_idx in range(first_batch, last_batch + 1):
                    self._deps[idx].add(dep_idx)
                    self._dependents[dep_idx].add(idx)

    def initial_ready(self) -> list[int]:
        """Return batch indices that have no dependencies (ready immediately)."""
        return [i for i in range(self._total) if not self._deps[i]]

    def mark_done(self, batch_idx: int) -> list[int]:
        """Mark a batch as done and return any newly-ready batch indices."""
        self._done.add(batch_idx)
        newly_ready: list[int] = []
        for dep_idx in self._dependents.get(batch_idx, set()):
            if dep_idx not in self._done and self._deps[dep_idx].issubset(self._done):
                newly_ready.append(dep_idx)
        return newly_ready

    def all_done(self) -> bool:
        return len(self._done) == self._total


def build_batches(
    entries: list[SubtitleEntry],
    batch_size: int = 20,
    context_size: int = 10,
) -> list[dict]:
    """Split entries into overlapping batches for context-aware translation."""
    batches: list[dict] = []
    i = 0
    while i < len(entries):
        batch = entries[i:i + batch_size]
        prev_start = max(0, i - context_size)
        next_start = min(len(entries), i + len(batch))
        batches.append({
            "batch": batch,
            "prev_context": entries[prev_start:i],
            "next_context": entries[next_start:next_start + context_size],
        })
        i += batch_size
    return batches


async def translate_all(
    entries: list[SubtitleEntry],
    config: Config,
    llm_translate_fn,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[SubtitleEntry]:
    """Translate all subtitle entries with dependency-aware concurrency.

    Uses a DependencyTracker to respect the sliding context window: a batch
    is only submitted when all batches providing its prev_context are done.
    Up to config.translate_workers batches may be in-flight concurrently.
    """
    batches = build_batches(entries, config.batch_size, config.context_size)
    if not batches:
        return []

    tracker = _DependencyTracker(len(batches), config.batch_size, config.context_size)
    translated_map: dict[int, str] = {}
    completed_count = 0

    # Ready queue + semaphore for concurrency control
    ready_queue: asyncio.Queue[int] = asyncio.Queue()
    semaphore = asyncio.Semaphore(config.translate_workers)

    for idx in tracker.initial_ready():
        ready_queue.put_nowait(idx)

    async def _translate_batch(batch_idx: int) -> None:
        nonlocal completed_count

        batch_info = batches[batch_idx]
        batch = batch_info["batch"]
        prev_entries = batch_info["prev_context"]
        next_entries = batch_info["next_context"]

        # Build context from already-translated entries
        prev_context: list[tuple[SubtitleEntry, str]] = []
        for entry in prev_entries:
            if entry.index in translated_map:
                prev_context.append((entry, translated_map[entry.index]))

        user_msg = _build_user_message(batch, prev_context, next_entries)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(
                source_lang=config.source_lang,
                target_lang=config.target_lang,
            )},
            {"role": "user", "content": user_msg},
        ]

        response = await llm_translate_fn(messages, config)
        translations = _parse_translations(response, batch)

        for entry, trans in zip(batch, translations):
            translated_map[entry.index] = trans

        logger.debug("Batch %d/%d complete (%d entries)",
                      batch_idx + 1, len(batches), len(batch))

    first_error: Exception | None = None

    async def _worker() -> None:
        nonlocal completed_count, first_error
        while True:
            batch_idx = await ready_queue.get()
            try:
                try:
                    async with semaphore:
                        await _translate_batch(batch_idx)
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                    raise
            finally:
                newly_ready = tracker.mark_done(batch_idx)
                completed_count += 1
                for new_idx in newly_ready:
                    ready_queue.put_nowait(new_idx)
                if progress_callback:
                    progress_callback(completed_count, len(batches))
                ready_queue.task_done()

    # Launch workers
    worker_tasks = [
        asyncio.create_task(_worker())
        for _ in range(min(config.translate_workers, len(batches)))
    ]

    await ready_queue.join()

    # If any batch failed, cancel remaining workers and raise
    if first_error is not None:
        for t in worker_tasks:
            t.cancel()
        raise first_error

    # Stop workers
    for t in worker_tasks:
        t.cancel()

    # Reconstruct ordered result
    result: list[SubtitleEntry] = []
    for entry in entries:
        result.append(SubtitleEntry(
            index=entry.index,
            start=entry.start,
            end=entry.end,
            text=translated_map.get(entry.index, entry.text),
        ))
    return result
