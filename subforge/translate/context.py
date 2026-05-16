from __future__ import annotations

from subforge.config import Config
from subforge.models import SubtitleEntry

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
    # Simple fallback: split by lines, match to batch size
    lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
    translations: list[str] = []

    # Try to extract numbered entries like [1] text
    for entry in batch:
        prefix = f"[{entry.index}]"
        found = False
        for line in lines:
            if line.startswith(prefix):
                # Remove the prefix
                text = line[len(prefix):].strip()
                translations.append(text)
                found = True
                break
        if not found:
            translations.append("")  # placeholder if parsing fails

    return translations


def build_batches(
    entries: list[SubtitleEntry],
    batch_size: int = 20,
    context_size: int = 10,
) -> list[dict]:
    """Split entries into overlapping batches for context-aware translation.

    Each batch dict contains:
      - batch: list[SubtitleEntry] — entries to translate this round
      - prev_context_start: int — index into entries for previous context
      - next_context_start: int — index into entries for look-ahead

    The caller should fill in actual translations for prev_context after
    each batch is complete.
    """
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
) -> list[SubtitleEntry]:
    """Translate all subtitle entries batch by batch with sliding context.

    Args:
        entries: Source language subtitle entries.
        config: Application configuration.
        llm_translate_fn: Async function (messages, config) -> str.

    Returns:
        New list of SubtitleEntry with translated text.
    """
    batches = build_batches(entries, config.batch_size, config.context_size)
    translated_map: dict[int, str] = {}  # entry index -> translated text

    for batch_info in batches:
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

    result: list[SubtitleEntry] = []
    for entry in entries:
        result.append(SubtitleEntry(
            index=entry.index,
            start=entry.start,
            end=entry.end,
            text=translated_map.get(entry.index, entry.text),
        ))
    return result
