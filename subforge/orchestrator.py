from __future__ import annotations

import asyncio
import logging
import time


from subforge.asr.deepgram import transcribe as deepgram_transcribe, transcribe_chunked as deepgram_transcribe_chunked
from subforge.asr.remote_limiter import RemoteAsrRequestLimiter
from subforge.asr.engine import _audio_duration_seconds, transcribe as asr_transcribe
from subforge.asr.model_manager import ensure_model
from subforge.config import Config
from subforge.events import EventSink, EventType, emit_event, make_event
from subforge.gemini_audio import (
    GeminiAudioAdapter,
    GoogleGeminiTransport,
    OpenAICompatibleAudioTransport,
    gemini_profile_from_mapping,
)
from subforge.models import Job, JobStatus, SubtitleEntry
from subforge.resume import ResumeStore, read_reusable_srt
from subforge.segment_processing import SegmentRequest
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


def _clamp_entries_to_duration(entries: list, duration: float) -> list:
    """把 ASR 结果钳制到媒体时长内。

    Whisper 对结尾静音会幻觉出「ご視聴ありがとうございました」这类尾句，
    时间戳可能超出实际音频长度；写盘前钳制/丢弃，避免脏数据阻止后续编辑。
    """
    if duration <= 0:
        return entries
    clamped: list[SubtitleEntry] = []
    for entry in entries:
        if entry.start >= duration - 0.001:
            continue  # 完全在音频之后，属幻觉
        end = min(float(entry.end), duration)
        if end - float(entry.start) < 0.001:
            continue
        clamped.append(SubtitleEntry(len(clamped) + 1, float(entry.start), round(end, 3), entry.text))
    return clamped


def _target_srt_is_complete(source_entries: list, target_entries: list) -> bool:
    """Return whether a target SRT has one non-empty translation per source entry."""
    if len(source_entries) != len(target_entries):
        return False
    source_indices = [entry.index for entry in source_entries]
    target_indices = [entry.index for entry in target_entries]
    return source_indices == target_indices and all(entry.text.strip() for entry in target_entries)


def _run_asr(job: Job, config: Config, progress_callback, model_ready_callback=None, resume_state=None, resume_store=None) -> list:
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
        if config.remote_asr_global_workers > 0:
            return deepgram_transcribe_chunked(
                job.file_path,
                api_key=config.deepgram_api_key,
                model=config.deepgram_model,
                language=job.source_lang,
                keyterms=config.deepgram_keyterms,
                chunk_seconds=config.asr_chunk_seconds,
                limiter=RemoteAsrRequestLimiter(
                    config.remote_asr_limiter_dir,
                    config.remote_asr_global_workers,
                ),
                progress_callback=progress_callback,
                resume_state=resume_state,
                resume_store=resume_store,
            )
        return deepgram_transcribe(
            job.file_path,
            api_key=config.deepgram_api_key,
            model=config.deepgram_model,
            language=job.source_lang,
            keyterms=config.deepgram_keyterms,
            progress_callback=progress_callback,
        )
    raise ValueError(f"Unsupported ASR provider: {config.asr_provider}")


def _merge_fn_from_profile(profile: dict | None):
    """把合并 Profile 快照包装成文本层校对回调（保留 SubForge 时间轴）。"""
    if not profile:
        return None
    merge_config = Config(
        llm_api_key=str(profile.get("api_key", "")),
        llm_base_url=str(profile.get("base_url", "")),
        llm_model=str(profile.get("model", "")),
        llm_proxy_url=str(profile.get("proxy_url", "")),
        llm_verify_tls=bool(profile.get("verify_tls", True)),
        llm_ca_bundle=str(profile.get("ca_bundle", "")),
        translate_workers=1,
        translation_global_workers=0,
    )

    async def merge_fn(messages):
        return await translate_batch(messages, merge_config)

    return merge_fn


async def _run_asr_model(job: Job, config: Config, progress_callback, model_ready_callback=None, resume_state=None, resume_store=None) -> list:
    """用统一模型 Profile 作为 ASR（Gemini 类音频模型）。

    异步直接 await（transport 为异步），不在 worker 线程里再套 asyncio.run。
    """
    profile = config.asr_profile or {}
    if not profile:
        raise ValueError("ASR 模型 Profile 缺失")
    gemini_profile = gemini_profile_from_mapping(profile)
    # 任务快照控制本次请求粒度，但不能突破 ASR Profile 的硬上限。
    gemini_profile.max_segment_seconds = min(
        gemini_profile.max_segment_seconds,
        max(10, int(config.asr_chunk_seconds)),
    )
    remote_limiter = (
        RemoteAsrRequestLimiter(config.remote_asr_limiter_dir, config.remote_asr_global_workers)
        if config.remote_asr_global_workers > 0 else None
    )
    transport = (
        GoogleGeminiTransport(gemini_profile, request_limiter=remote_limiter)
        if gemini_profile.protocol == "google_native"
        else OpenAICompatibleAudioTransport(gemini_profile, request_limiter=remote_limiter)
    )
    if model_ready_callback:
        model_ready_callback()
    duration = _audio_duration_seconds(job.file_path)
    if duration <= 0:
        raise ValueError("无法读取媒体时长，无法进行分片转写")
    merge_profile = config.merge_profile or None
    adapter_kwargs = {
        "merge_fn": _merge_fn_from_profile(merge_profile),
        "merge_prompt": str((merge_profile or {}).get("merge_prompt", "")),
        "progress_callback": progress_callback,
    }
    if config.remote_asr_global_workers > 0:
        adapter_kwargs["chunk_concurrency"] = config.remote_asr_global_workers
    # transport 在每次真实 HTTP attempt 上获取网络 ASR 槽；
    # adapter 不再包住含重试/退避的整个 generate()。
    adapter = GeminiAudioAdapter(gemini_profile, transport, **adapter_kwargs)
    process_kwargs = {}
    if resume_state is not None:
        process_kwargs["resume_state"] = resume_state
    if resume_store is not None:
        process_kwargs["resume_store"] = resume_store
    candidate = await adapter.process(
        SegmentRequest(
            media_path=job.file_path,
            target_start=0.0,
            target_end=duration,
            source_language=job.source_lang,
            target_language=job.target_lang,
            processing_mode="transcribe",
        ),
        **process_kwargs,
    )
    return candidate.source_entries


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
                source_entries = read_reusable_srt(source_srt_path) if source_srt_path.exists() else None
                if target_entries is not None and (
                    source_entries is None or _target_srt_is_complete(source_entries, target_entries)
                ):
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
                logger.warning("[%s] %s: Existing target SRT is incomplete; resuming translation",
                               job.id, job.file_path.name)

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
            if config.asr_provider == "model":
                profile_name = (config.asr_profile or {}).get("name") or (config.asr_profile or {}).get("model") or "Gemini"
                model_desc = f"Model ({profile_name})"
            elif config.asr_provider == "deepgram":
                model_desc = f"Deepgram ({config.deepgram_model})"
            else:
                model_desc = job.model_size
            emit_event(event_sink, make_event(
                EventType.ASR_PREPARING,
                job.id,
                stage="model",
                message=f"Preparing ASR model {model_desc}",
            ))
            logger.info("[%s] %s: ASR model preparing (%s)", job.id, job.file_path.name, model_desc)
            def _asr_progress(
                value: float,
                completed: int | None = None,
                total: int | None = None,
                message: str | None = None,
            ) -> None:
                progress = max(0.0, min(1.0, value))
                job.asr_progress = progress
                emit_event(event_sink, make_event(
                    EventType.ASR_PROGRESS,
                    job.id,
                    stage="asr",
                    progress=progress,
                    completed=completed,
                    total=total,
                    message=message,
                ))

            def _model_ready(message: str | None = None) -> None:
                nonlocal current_stage
                current_stage = "asr"
                emit_event(event_sink, make_event(
                    EventType.ASR_STARTED,
                    job.id,
                    stage="asr",
                    message=message or "ASR 模型已就绪，开始转写",
                ))

            if config.asr_provider == "model":
                entries = await _run_asr_model(job, config, _asr_progress, _model_ready, resume_state=state, resume_store=store)
            else:
                entries = await asyncio.to_thread(
                    _run_asr,
                    job,
                    config,
                    _asr_progress,
                    _model_ready,
                    state,
                    store,
                )
            job.asr_progress = 1.0
            emit_event(event_sink, make_event(
                EventType.ASR_COMPLETED,
                job.id,
                stage="asr",
                progress=1.0,
                message="ASR 转写完成",
            ))
            logger.debug("[%s] DBG: ASR stage returned, entries=%d", job.id, len(entries))

        if not entries:
            job.status = JobStatus.NO_SPEECH
            job.finished_at = time.time()
            logger.info("[%s] %s: no recognizable speech", job.id, job.file_path.name)
            emit_event(event_sink, make_event(
                EventType.TASK_NO_SPEECH,
                job.id,
                stage="no_speech",
                progress=1.0,
                message="未识别到可生成字幕的语音",
            ))
            return

        # Stage 1.5: Timeline fine-tuning
        logger.debug("[%s] DBG: entering merge_short_entries", job.id)
        entries = merge_short_entries(entries)
        logger.debug("[%s] DBG: merge_short_entries done, %d entries", job.id, len(entries))
        entries = adjust_gaps(entries)
        logger.debug("[%s] DBG: adjust_gaps done", job.id)
        entries = _clamp_entries_to_duration(entries, _audio_duration_seconds(job.file_path))

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
            message="开始翻译",
        ))
        def _tl_progress(done: int, _total: int) -> None:
            emit_event(event_sink, make_event(
                EventType.TRANSLATION_PROGRESS,
                job.id,
                stage="translation",
                progress=done / _total if _total else 1.0,
                completed=done,
                total=_total,
                message=f"翻译中（{done}/{_total} 批次）",
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
            message="翻译完成",
        ))
        logger.info("[%s] %s: Target SRT → %s", job.id, job.file_path.name, target_srt_path)

        job.status = JobStatus.DONE
        job.finished_at = time.time()
        elapsed = job.finished_at - job.started_at
        logger.info("[%s] %s: Done in %.1fs", job.id, job.file_path.name, elapsed)
        emit_event(event_sink, make_event(
            EventType.TASK_COMPLETED,
            job.id,
            stage="complete",
            message=f"处理完成（耗时 {elapsed:.1f}s）",
        ))

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
