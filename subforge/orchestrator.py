from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from tqdm import tqdm

from subforge.asr.engine import transcribe as asr_transcribe
from subforge.asr.model_manager import ensure_model
from subforge.config import Config
from subforge.models import Job, JobStatus
from subforge.timeline import adjust_gaps, merge_short_entries
from subforge.translate.context import translate_all
from subforge.translate.llm_client import LLMError, translate_batch
from subforge.translate.srt_io import write_srt

logger = logging.getLogger(__name__)


class _SlotAllocator:
    """Manage tqdm position slots so concurrent jobs don't overwrite each other."""

    def __init__(self, num_slots: int) -> None:
        self._available = asyncio.Queue()
        for i in range(num_slots):
            self._available.put_nowait(i)

    async def acquire(self) -> int:
        return await self._available.get()

    async def release(self, slot: int) -> None:
        await self._available.put(slot)


async def process_one(job: Job, config: Config, pbar_slot: int) -> None:
    """Process a single file: ASR → timeline fix → translate → write output."""
    job.status = JobStatus.ASR_RUNNING
    job.started_at = time.time()
    logger.info("[%s] %s: ASR started", job.id, job.file_path.name)

    try:
        # Stage 1: ASR
        _available, local_only = ensure_model(job.model_size, config.models_dir)
        asr_bar = tqdm(
            total=1.0,
            desc=f"[ASR] {job.file_path.name}",
            position=pbar_slot,
            leave=False,
            unit="",
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {elapsed}",
        )

        def _asr_progress(value: float) -> None:
            asr_bar.n = value
            asr_bar.refresh()

        entries = await asyncio.to_thread(
            asr_transcribe,
            job.file_path,
            model_size=job.model_size,
            language=job.source_lang,
            models_dir=config.models_dir,
            local_files_only=local_only,
            device=config.device,
            compute_type=config.compute_type,
            vad_filter=config.vad_filter,
            vad_threshold=config.vad_threshold,
            vad_min_speech_duration_ms=config.vad_min_speech_duration_ms,
            vad_min_silence_duration_ms=config.vad_min_silence_duration_ms,
            vad_speech_pad_ms=config.vad_speech_pad_ms,
            vad_max_speech_duration_s=config.vad_max_speech_duration_s,
            condition_on_previous_text=config.condition_on_previous_text,
            no_speech_threshold=config.no_speech_threshold,
            preprocess_audio=config.preprocess_audio,
            progress_callback=_asr_progress,
        )
        asr_bar.close()
        job.asr_progress = 1.0

        if not entries:
            raise RuntimeError("ASR produced no segments")

        # Stage 1.5: Timeline fine-tuning
        entries = merge_short_entries(entries)
        entries = adjust_gaps(entries)

        # Write source language SRT
        source_srt_path = job.file_path.with_suffix(".srt")
        if config.output_dir:
            source_srt_path = config.output_dir / source_srt_path.name
        write_srt(entries, source_srt_path)
        logger.info("[%s] %s: Source SRT → %s", job.id, job.file_path.name, source_srt_path)

        # Stage 2: Translation
        job.status = JobStatus.TRANSLATING
        logger.info("[%s] %s: Translation started", job.id, job.file_path.name)

        total_batches = -(-len(entries) // config.batch_size)  # ceil division
        translate_bar = tqdm(
            total=total_batches,
            desc=f"[Translate] {job.file_path.name}",
            position=pbar_slot,
            leave=False,
            unit="batch",
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} batches",
        )

        def _tl_progress(done: int, _total: int) -> None:
            translate_bar.n = done
            translate_bar.refresh()

        translated = await translate_all(
            entries, config, translate_batch,
            progress_callback=_tl_progress,
        )
        translate_bar.close()

        # Write target language SRT
        target_srt_path = job.file_path.parent / f"{job.file_path.stem}_{job.target_lang}.srt"
        if config.output_dir:
            target_srt_path = config.output_dir / target_srt_path.name
        write_srt(translated, target_srt_path)
        job.translate_progress = 1.0
        logger.info("[%s] %s: Target SRT → %s", job.id, job.file_path.name, target_srt_path)

        job.status = JobStatus.DONE
        job.finished_at = time.time()
        elapsed = job.finished_at - job.started_at
        logger.info("[%s] %s: Done in %.1fs", job.id, job.file_path.name, elapsed)

    except LLMError as e:
        job.status = JobStatus.FAILED
        job.error = f"Translation failed: {e}"
        job.finished_at = time.time()
        logger.error("[%s] %s: FAILED — %s", job.id, job.file_path.name, e)
        # Source SRT was already written, so partial success

    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = f"{type(e).__name__}: {e}"
        job.finished_at = time.time()
        logger.exception("[%s] %s: FAILED", job.id, job.file_path.name)


async def _worker(
    queue: asyncio.Queue[Job | None],
    semaphore: asyncio.Semaphore,
    slots: _SlotAllocator,
    config: Config,
) -> None:
    while True:
        job = await queue.get()
        if job is None:  # sentinel to stop
            queue.task_done()
            break
        async with semaphore:
            slot = await slots.acquire()
            try:
                await process_one(job, config, slot)
            finally:
                await slots.release(slot)
        queue.task_done()


async def process_all(jobs: list[Job], config: Config) -> dict:
    """Process all jobs with concurrency control.

    Returns:
        Dict with 'succeeded', 'failed', 'total_time' keys.
    """
    if not jobs:
        return {"succeeded": 0, "failed": 0, "total_time": 0.0}

    queue: asyncio.Queue[Job | None] = asyncio.Queue()
    semaphore = asyncio.Semaphore(config.concurrency)

    # Enqueue all jobs
    for job in jobs:
        queue.put_nowait(job)

    # Put sentinels for each worker
    for _ in range(config.concurrency):
        queue.put_nowait(None)

    total = len(jobs)
    logger.info("Processing %d file(s) with concurrency=%d", total, config.concurrency)

    slots = _SlotAllocator(config.concurrency)
    started_at = time.time()

    workers = [
        asyncio.create_task(_worker(queue, semaphore, slots, config))
        for _ in range(config.concurrency)
    ]

    # Wait for all jobs to finish
    await queue.join()

    # Cancel workers (they should already be done)
    for w in workers:
        w.cancel()

    total_time = time.time() - started_at
    succeeded = sum(1 for j in jobs if j.status == JobStatus.DONE)
    failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)

    logger.info("Done. Succeeded: %d, Failed: %d, Total time: %.1fs",
                 succeeded, failed, total_time)
    for j in jobs:
        status = "OK" if j.status == JobStatus.DONE else "FAIL"
        elapsed = ""
        if j.started_at and j.finished_at:
            elapsed = f" ({j.finished_at - j.started_at:.1f}s)"
        error_str = f" — {j.error}" if j.error else ""
        logger.info("  [%s] %s%s%s", status, j.file_path.name, elapsed, error_str)

    return {"succeeded": succeeded, "failed": failed, "total_time": total_time}
