from __future__ import annotations

import asyncio
import logging
from typing import Callable

from subforge.config import Config
from subforge.models import SubtitleEntry
from subforge.resume import ResumeState, ResumeStore

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
    prev_context: list[SubtitleEntry],
    next_context: list[SubtitleEntry],
) -> str:
    """Build the user message with source-only context and batch entries."""
    parts: list[str] = []

    if prev_context:
        parts.append("=== Previous entries (for context) ===")
        for entry in prev_context:
            parts.append(f"[{entry.index}] {entry.text}")
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
    resume_state: ResumeState | None = None,
    resume_store: ResumeStore | None = None,
) -> list[SubtitleEntry]:
    """Translate all subtitle entries with full concurrency.

    All batches are independent — context uses source-language text only
    (both previous and upcoming entries), so there is no dependency chain.
    Up to config.translate_workers batches may be in-flight concurrently.
    """
    batches = build_batches(entries, config.batch_size, config.context_size)
    if not batches:
        return []

    translated_map: dict[int, str] = {}
    completed_count = 0
    completed_batches = {}
    if resume_state is not None:
        completed_batches = resume_state.translation.get("completed_batches", {})

    queue: asyncio.Queue[int] = asyncio.Queue()
    semaphore = asyncio.Semaphore(config.translate_workers)
    # Initial calls may run concurrently, but semantic-empty retries are serialized.
    # This prevents a transient provider overload from causing every failed batch to
    # retry at the same instant and return another HTTP-200-but-empty response.
    semantic_retry_lock = asyncio.Lock()

    for idx in range(len(batches)):
        cached_entries = completed_batches.get(str(idx))
        expected_entries = batches[idx]["batch"]
        expected_indices = {entry.index for entry in expected_entries}
        try:
            cached_by_index = {int(cached["index"]): cached for cached in (cached_entries or [])}
        except (KeyError, TypeError, ValueError):
            cached_by_index = {}
        # 自愈：只有整批条目齐全且每条都有非空译文，历史缓存才算完成。
        # 过去使用 any()，导致一个批次只要有一条译文就会被跳过，留下批次内空字幕。
        cache_is_complete = (
            bool(cached_entries)
            and len(cached_entries) == len(expected_entries)
            and set(cached_by_index) == expected_indices
            and all(str(cached_by_index[index].get("text", "")).strip() for index in expected_indices)
        )
        if cache_is_complete:
            for cached in cached_entries:
                translated_map[int(cached["index"])] = str(cached["text"])
            completed_count += 1
        else:
            queue.put_nowait(idx)

    if completed_count:
        logger.info("Translation resume: skipping %d/%d completed batch(es)",
                    completed_count, len(batches))
        if progress_callback:
            progress_callback(completed_count, len(batches))

    if completed_count == len(batches):
        return [
            SubtitleEntry(
                index=entry.index,
                start=entry.start,
                end=entry.end,
                text=translated_map.get(entry.index, entry.text),
            )
            for entry in entries
        ]

    async def _translate_batch(batch_idx: int) -> None:
        nonlocal completed_count

        batch_info = batches[batch_idx]
        batch = batch_info["batch"]
        prev_entries = batch_info["prev_context"]
        next_entries = batch_info["next_context"]

        semantic_attempts = 3

        async def _request_batch(target_batch: list[SubtitleEntry]) -> tuple[str, list[str]]:
            user_msg = _build_user_message(target_batch, prev_entries, next_entries)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT.format(
                    source_lang=config.source_lang,
                    target_lang=config.target_lang,
                )},
                {"role": "user", "content": user_msg},
            ]
            response = ""
            translations: list[str] = []
            for attempt in range(1, semantic_attempts + 1):
                if attempt == 1:
                    response = await llm_translate_fn(messages, config)
                else:
                    wait = 2 ** (attempt - 2)
                    logger.warning(
                        "Batch %d/%d returned incomplete translations; semantic retry %d/%d in %ds",
                        batch_idx + 1, len(batches), attempt, semantic_attempts, wait,
                    )
                    await asyncio.sleep(wait)
                    async with semantic_retry_lock:
                        response = await llm_translate_fn(messages, config)
                translations = _parse_translations(response, target_batch)
                if response.strip() and all(t.strip() for t in translations):
                    break
            return response, translations

        response, translations = await _request_batch(batch)
        missing_entries = [
            entry for entry, translation in zip(batch, translations)
            if not translation.strip()
        ]
        if missing_entries and len(missing_entries) < len(batch):
            # Some local models omit individual [N] lines in a large response while
            # successfully translating the rest. Repair only the missing entries in
            # smaller requests instead of caching silent holes or failing the file.
            repaired: dict[int, str] = {}
            repair_size = 5
            for start in range(0, len(missing_entries), repair_size):
                repair_batch = missing_entries[start:start + repair_size]
                _, repair_translations = await _request_batch(repair_batch)
                unresolved = [
                    entry for entry, translation in zip(repair_batch, repair_translations)
                    if not translation.strip()
                ]
                repaired.update({
                    entry.index: translation
                    for entry, translation in zip(repair_batch, repair_translations)
                    if translation.strip()
                })
                if unresolved:
                    if len(repair_batch) == 1:
                        raise RuntimeError(
                            f"LLM returned incomplete repair translations after {semantic_attempts} "
                            f"semantic attempts (batch {batch_idx + 1}, 1 entry empty)."
                        )
                    # If a repair group is still partial, fall back to one entry per
                    # request. This handles local models that drop specific lines in
                    # a multi-entry response but can translate them individually.
                    for entry in unresolved:
                        _, single_translation = await _request_batch([entry])
                        if not single_translation or not single_translation[0].strip():
                            raise RuntimeError(
                                f"LLM returned incomplete repair translations after {semantic_attempts} "
                                f"semantic attempts (batch {batch_idx + 1}, entry {entry.index} empty)."
                            )
                        repaired[entry.index] = single_translation[0]
            translations = [
                translation or repaired.get(entry.index, "")
                for entry, translation in zip(batch, translations)
            ]

        if not response.strip() or not all(t.strip() for t in translations):
            # Never cache a batch whose response is non-empty at the HTTP layer but
            # contains no usable [N] translations after semantic retries.
            raise RuntimeError(
                f"LLM returned an incomplete translation batch after {semantic_attempts} semantic attempts "
                f"(batch {batch_idx + 1}: "
                f"{sum(1 for t in translations if not t.strip())}/{len(batch)} entries empty). "
                "This can be caused by reasoning token exhaustion or a transient "
                "provider failure under concurrent load."
            )

        translated_entries: list[SubtitleEntry] = []
        for entry, trans in zip(batch, translations):
            translated_map[entry.index] = trans
            translated_entries.append(SubtitleEntry(
                index=entry.index,
                start=entry.start,
                end=entry.end,
                text=trans,
            ))

        if resume_state is not None and resume_store is not None:
            resume_store.save_batch(
                resume_state,
                batch_idx,
                translated_entries,
                len(batches),
            )

        logger.debug("Batch %d/%d complete (%d entries)",
                      batch_idx + 1, len(batches), len(batch))

    first_error: Exception | None = None

    async def _worker() -> None:
        nonlocal completed_count, first_error
        while True:
            batch_idx = await queue.get()
            try:
                if first_error is None:
                    async with semaphore:
                        await _translate_batch(batch_idx)
                    completed_count += 1
                    if progress_callback:
                        progress_callback(completed_count, len(batches))
                else:
                    logger.debug("Skipping batch %d because an earlier batch failed", batch_idx)
            except Exception as exc:
                if first_error is None:
                    first_error = exc
            finally:
                queue.task_done()

    worker_tasks = [
        asyncio.create_task(_worker())
        for _ in range(min(config.translate_workers, len(batches)))
    ]

    await queue.join()

    if first_error is not None:
        for t in worker_tasks:
            t.cancel()
        raise first_error

    for t in worker_tasks:
        t.cancel()

    result: list[SubtitleEntry] = []
    for entry in entries:
        result.append(SubtitleEntry(
            index=entry.index,
            start=entry.start,
            end=entry.end,
            text=translated_map.get(entry.index, entry.text),
        ))
    return result
