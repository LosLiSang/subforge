from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from subforge.asr.engine import transcribe as asr_transcribe
from subforge.config import Config
from subforge.models import Job, JobStatus
from subforge.timeline import adjust_gaps, merge_short_entries
from subforge.translate.context import translate_all
from subforge.translate.llm_client import LLMError, translate_batch
from subforge.translate.srt_io import write_srt


async def process_one(job: Job, config: Config) -> None:
    """Process a single file: ASR → timeline fix → translate → write output."""
    job.status = JobStatus.ASR_RUNNING
    job.started_at = time.time()
    print(f"[{job.id}] {job.file_path.name}: ASR started", file=sys.stderr)

    try:
        # Stage 1: ASR
        entries = await asyncio.to_thread(
            asr_transcribe,
            job.file_path,
            model_size=job.model_size,
            language=job.source_lang,
            models_dir=config.models_dir,
        )
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
        print(f"[{job.id}] {job.file_path.name}: Source SRT → {source_srt_path}", file=sys.stderr)

        # Stage 2: Translation
        job.status = JobStatus.TRANSLATING
        print(f"[{job.id}] {job.file_path.name}: Translation started", file=sys.stderr)

        translated = await translate_all(entries, config, translate_batch)

        # Write target language SRT
        target_srt_path = job.file_path.parent / f"{job.file_path.stem}_{job.target_lang}.srt"
        if config.output_dir:
            target_srt_path = config.output_dir / target_srt_path.name
        write_srt(translated, target_srt_path)
        job.translate_progress = 1.0
        print(f"[{job.id}] {job.file_path.name}: Target SRT → {target_srt_path}", file=sys.stderr)

        job.status = JobStatus.DONE
        job.finished_at = time.time()
        elapsed = job.finished_at - job.started_at
        print(f"[{job.id}] {job.file_path.name}: Done in {elapsed:.1f}s", file=sys.stderr)

    except LLMError as e:
        job.status = JobStatus.FAILED
        job.error = f"Translation failed: {e}"
        job.finished_at = time.time()
        print(f"[{job.id}] {job.file_path.name}: FAILED — {e}", file=sys.stderr)
        # Source SRT was already written, so partial success

    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = f"{type(e).__name__}: {e}"
        job.finished_at = time.time()
        print(f"[{job.id}] {job.file_path.name}: FAILED — {e}", file=sys.stderr)


async def _worker(
    queue: asyncio.Queue[Job | None],
    semaphore: asyncio.Semaphore,
    config: Config,
) -> None:
    while True:
        job = await queue.get()
        if job is None:  # sentinel to stop
            queue.task_done()
            break
        async with semaphore:
            await process_one(job, config)
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
    print(f"\nProcessing {total} file(s) with concurrency={config.concurrency}\n",
          file=sys.stderr)

    started_at = time.time()

    workers = [
        asyncio.create_task(_worker(queue, semaphore, config))
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

    print(f"\n{'='*50}", file=sys.stderr)
    print(f"Done. Succeeded: {succeeded}, Failed: {failed}, Total time: {total_time:.1f}s",
          file=sys.stderr)
    for j in jobs:
        status = "OK" if j.status == JobStatus.DONE else "FAIL"
        elapsed = ""
        if j.started_at and j.finished_at:
            elapsed = f" ({j.finished_at - j.started_at:.1f}s)"
        error_str = f" — {j.error}" if j.error else ""
        print(f"  [{status}] {j.file_path.name}{elapsed}{error_str}", file=sys.stderr)

    return {"succeeded": succeeded, "failed": failed, "total_time": total_time}
