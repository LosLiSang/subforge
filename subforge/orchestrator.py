from __future__ import annotations

import asyncio
import logging
import time


from subforge.asr.deepgram import transcribe as deepgram_transcribe
from subforge.asr.engine import transcribe as asr_transcribe
from subforge.asr.model_manager import ensure_model
from subforge.config import Config
from subforge.events import EventSink, EventType, emit_event, make_event
from subforge.models import Job, JobStatus
from subforge.resume import ResumeStore, read_reusable_srt
from subforge.timeline import adjust_gaps, merge_short_entries
from subforge.translate.context import translate_all
from subforge.translate.llm_client import LLMError, translate_batch
from subforge.translate.srt_io import subtitle_path, write_srt

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


def _run_asr(job: Job, config: Config, progress_callback, model_ready_callback=None) -> list:
    if config.asr_provider == "local":
        if config.direct_model_path:
            model_reference = str(config.direct_model_path)
            local_only = True
        else:
            _available, local_only = ensure_model(job.model_size, config.models_dir)
            model_reference = job.model_size
        return asr_transcribe(
            job.file_path,
            model_size=model_reference,
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
            progress_callback=progress_callback,
            model_ready_callback=model_ready_callback,
        )
    if config.asr_provider == "deepgram":
        if model_ready_callback:
            model_ready_callback()
        return deepgram_transcribe(
            job.file_path,
            api_key=config.deepgram_api_key,
            model=config.deepgram_model,
            language=job.source_lang,
            keyterms=config.deepgram_keyterms,
            progress_callback=progress_callback,
        )
    raise ValueError(f"Unsupported ASR provider: {config.asr_provider}")


async def process_one(
    job: Job,
    config: Config,
    pbar_slot: int,
    event_sink: EventSink | None = None,
    resume_store: ResumeStore | None = None,
) -> None:
    """Process a single file: ASR → timeline fix → translate → write output."""
    job.started_at = time.time()
    current_stage = "setup"

    try:
        source_srt_path = subtitle_path(job.file_path, job.source_lang, config.output_dir)
        target_srt_path = subtitle_path(job.file_path, job.target_lang, config.output_dir)
        if config.output_dir:
            config.output_dir.mkdir(parents=True, exist_ok=True)

        store = resume_store or ResumeStore(config.jobs_dir)
        if config.force:
            logger.info("[%s] %s: --force enabled, ignoring existing SRT files and resume state",
                        job.id, job.file_path.name)
            state = store.create(job, config, source_srt_path, target_srt_path)
            store.save(state)
        else:
            state = store.load(job, config)
            if state is None:
                state = store.create(job, config, source_srt_path, target_srt_path)
                store.save(state)

            if target_srt_path.exists():
                target_entries = read_reusable_srt(target_srt_path)
                if target_entries is not None:
                    job.asr_progress = 1.0
                    job.translate_progress = 1.0
                    job.status = JobStatus.DONE
                    job.finished_at = time.time()
                    logger.info("[%s] %s: Target SRT already complete, skipping file",
                                job.id, job.file_path.name)
                    emit_event(event_sink, make_event(
                        EventType.TASK_COMPLETED,
                        job.id,
                        stage="complete",
                        message="Existing target subtitle reused",
                    ))
                    return

        entries = None
        if not config.force:
            if source_srt_path.exists():
                entries = read_reusable_srt(source_srt_path)
                if entries is not None:
                    job.asr_progress = 1.0
                    logger.info("[%s] %s: Reusing existing source SRT → %s",
                                job.id, job.file_path.name, source_srt_path)
            elif state.asr.get("status") == "done":
                state_source = store.resolve_path(state.paths.get("source_srt", str(source_srt_path)))
                entries = read_reusable_srt(state_source)
                if entries is not None:
                    source_srt_path = state_source
                    job.asr_progress = 1.0
                    logger.info("[%s] %s: Reusing resumed source SRT → %s",
                                job.id, job.file_path.name, source_srt_path)

        # Stage 1: ASR
        if entries is None:
            job.status = JobStatus.ASR_RUNNING
            current_stage = "model"
            emit_event(event_sink, make_event(
                EventType.ASR_PREPARING,
                job.id,
                stage="model",
                message=f"Preparing ASR model {job.model_size}",
            ))
            logger.info("[%s] %s: ASR model preparing", job.id, job.file_path.name)
            def _asr_progress(value: float) -> None:
                emit_event(event_sink, make_event(
                    EventType.ASR_PROGRESS,
                    job.id,
                    stage="asr",
                    progress=max(0.0, min(1.0, value)),
                ))

            def _model_ready() -> None:
                nonlocal current_stage
                current_stage = "asr"
                emit_event(event_sink, make_event(EventType.ASR_STARTED, job.id, stage="asr"))

            entries = await asyncio.to_thread(
                _run_asr,
                job,
                config,
                _asr_progress,
                _model_ready,
            )
            job.asr_progress = 1.0
            emit_event(event_sink, make_event(
                EventType.ASR_COMPLETED,
                job.id,
                stage="asr",
                progress=1.0,
            ))
            logger.debug("[%s] DBG: asyncio.to_thread returned, entries=%d", job.id, len(entries))

        if not entries:
            raise RuntimeError("ASR produced no segments")

        # Stage 1.5: Timeline fine-tuning
        logger.debug("[%s] DBG: entering merge_short_entries", job.id)
        entries = merge_short_entries(entries)
        logger.debug("[%s] DBG: merge_short_entries done, %d entries", job.id, len(entries))
        entries = adjust_gaps(entries)
        logger.debug("[%s] DBG: adjust_gaps done", job.id)

        # Write source language SRT
        logger.debug("[%s] DBG: about to write_srt to %s", job.id, source_srt_path)
        write_srt(entries, source_srt_path)
        store.mark_asr_done(state)
        logger.info("[%s] %s: Source SRT → %s", job.id, job.file_path.name, source_srt_path)

        # Stage 2: Translation
        job.status = JobStatus.TRANSLATING
        current_stage = "translation"
        logger.info("[%s] %s: Translation started", job.id, job.file_path.name)

        total_batches = -(-len(entries) // config.batch_size)  # ceil division
        emit_event(event_sink, make_event(
            EventType.TRANSLATION_STARTED,
            job.id,
            stage="translation",
            progress=0.0,
            completed=0,
            total=total_batches,
        ))
        def _tl_progress(done: int, _total: int) -> None:
            emit_event(event_sink, make_event(
                EventType.TRANSLATION_PROGRESS,
                job.id,
                stage="translation",
                progress=done / _total if _total else 1.0,
                completed=done,
                total=_total,
            ))

        def _llm_activity(message: str) -> None:
            emit_event(event_sink, make_event(
                EventType.TRANSLATION_ACTIVITY,
                job.id,
                stage="translation",
                message=message,
            ))

        async def _translate_with_activity(messages, cfg):
            return await translate_batch(
                messages, cfg, activity_callback=_llm_activity,
            )

        translated = await translate_all(
            entries, config, _translate_with_activity,
            progress_callback=_tl_progress,
            resume_state=state,
            resume_store=store,
        )

        # Write target language SRT
        write_srt(translated, target_srt_path)
        store.mark_translation_done(state)
        job.translate_progress = 1.0
        emit_event(event_sink, make_event(
            EventType.TRANSLATION_COMPLETED,
            job.id,
            stage="translation",
            progress=1.0,
            completed=total_batches,
            total=total_batches,
        ))
        logger.info("[%s] %s: Target SRT → %s", job.id, job.file_path.name, target_srt_path)

        job.status = JobStatus.DONE
        job.finished_at = time.time()
        elapsed = job.finished_at - job.started_at
        logger.info("[%s] %s: Done in %.1fs", job.id, job.file_path.name, elapsed)
        emit_event(event_sink, make_event(EventType.TASK_COMPLETED, job.id, stage="complete"))

    except LLMError as e:
        job.status = JobStatus.FAILED
        job.error = f"Translation failed: {e}"
        job.finished_at = time.time()
        logger.error("[%s] %s: FAILED — %s", job.id, job.file_path.name, e)
        emit_event(event_sink, make_event(
            EventType.TASK_FAILED,
            job.id,
            stage="translation",
            message=str(e),
            error_type=type(e).__name__,
        ))
        # Source SRT was already written, so partial success

    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = f"{type(e).__name__}: {e}"
        job.finished_at = time.time()
        logger.exception("[%s] %s: FAILED", job.id, job.file_path.name)
        emit_event(event_sink, make_event(
            EventType.TASK_FAILED,
            job.id,
            stage=current_stage,
            message=str(e),
            error_type=type(e).__name__,
        ))


async def _worker(
    queue: asyncio.Queue[Job | None],
    semaphore: asyncio.Semaphore,
    slots: _SlotAllocator,
    config: Config,
    event_sink: EventSink | None,
) -> None:
    while True:
        job = await queue.get()
        if job is None:  # sentinel to stop
            queue.task_done()
            break
        try:
            async with semaphore:
                slot = await slots.acquire()
                try:
                    await process_one(job, config, slot, event_sink=event_sink)
                finally:
                    await slots.release(slot)
        finally:
            queue.task_done()


async def process_all(
    jobs: list[Job],
    config: Config,
    event_sink: EventSink | None = None,
) -> dict:
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
        emit_event(event_sink, make_event(EventType.TASK_QUEUED, job.id, stage="queue"))
        queue.put_nowait(job)

    # Put sentinels for each worker
    for _ in range(config.concurrency):
        queue.put_nowait(None)

    total = len(jobs)
    logger.info("Processing %d file(s) with concurrency=%d", total, config.concurrency)

    slots = _SlotAllocator(config.concurrency)
    started_at = time.time()

    workers = [
        asyncio.create_task(_worker(queue, semaphore, slots, config, event_sink))
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
