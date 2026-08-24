import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from subforge.config import Config
from subforge.events import EventType
from subforge.models import Job, JobStatus, SubtitleEntry
from subforge.orchestrator import process_all, process_one
from subforge.translate.llm_client import LLMError


@pytest.fixture
def config(tmp_path):
    return Config(
        source_lang="ja",
        target_lang="zh",
        concurrency=2,
        jobs_dir=tmp_path / "jobs",
    )


@pytest.fixture
def sample_entries():
    return [
        SubtitleEntry(index=1, start=0.0, end=1.0, text="こんにちは"),
        SubtitleEntry(index=2, start=1.0, end=2.0, text="世界"),
    ]


class TestProcessOne:
    async def test_successful_pipeline_emits_structured_events(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")
        events = []

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        def fake_asr(*args, **kwargs):
            kwargs["model_ready_callback"]()
            kwargs["progress_callback"](0.25)
            kwargs["progress_callback"](0.75)
            return sample_entries

        with (
            patch("subforge.orchestrator.asr_transcribe", side_effect=fake_asr),
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0, event_sink=events.append)

        assert [event.type for event in events] == [
            EventType.ASR_PREPARING,
            EventType.ASR_STARTED,
            EventType.ASR_PROGRESS,
            EventType.ASR_PROGRESS,
            EventType.ASR_COMPLETED,
            EventType.TRANSLATION_STARTED,
            EventType.TRANSLATION_PROGRESS,
            EventType.TRANSLATION_COMPLETED,
            EventType.TASK_COMPLETED,
        ]
        assert [events[2].progress, events[3].progress] == [0.25, 0.75]
        assert events[6].completed == 1
        assert events[6].total == 1
        assert all(str(job.file_path) not in (event.message or "") for event in events)

    async def test_empty_asr_finishes_as_no_speech_without_translation(self, config, tmp_path):
        job = Job(file_path=tmp_path / "silent.mp3")
        events = []

        with (
            patch("subforge.orchestrator.asr_transcribe", return_value=[]),
            patch("subforge.orchestrator.translate_batch", new=AsyncMock()) as translate,
        ):
            await process_one(job, config, pbar_slot=0, event_sink=events.append)

        assert job.status == JobStatus.NO_SPEECH
        assert job.error is None
        assert events[-1].type == EventType.TASK_NO_SPEECH
        assert events[-1].stage == "no_speech"
        assert "未识别到" in events[-1].message
        translate.assert_not_awaited()

    async def test_failed_pipeline_emits_safe_failure_event(self, config, tmp_path):
        job = Job(file_path=tmp_path / "secret-name.mp3")
        events = []

        with patch("subforge.orchestrator.asr_transcribe", side_effect=RuntimeError("ASR crashed")):
            await process_one(job, config, pbar_slot=0, event_sink=events.append)

        assert events[-1].type == EventType.TASK_FAILED
        assert events[-1].stage == "model"
        assert events[-1].error_type == "RuntimeError"
        assert events[-1].message == "ASR crashed"
        assert str(job.file_path) not in events[-1].message

    async def test_successful_pipeline(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 译\n[2] 文\n[3] 桩"

        with (
            patch(
                "subforge.orchestrator.asr_transcribe",
                return_value=sample_entries,
            ),
            patch(
                "subforge.orchestrator.translate_batch",
                side_effect=fake_translate,
            ),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        assert job.asr_progress == 1.0
        assert job.translate_progress == 1.0
        assert job.error is None

    async def test_direct_model_path_bypasses_cache_lookup(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3", model_size="large-v3")
        direct = tmp_path / "large-v3"
        direct.mkdir()
        config.direct_model_path = direct

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.ensure_model") as mock_ensure,
            patch("subforge.orchestrator.asr_transcribe", return_value=sample_entries) as mock_asr,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        mock_ensure.assert_not_called()
        assert mock_asr.call_args.kwargs["model_size"] == str(direct)
        assert mock_asr.call_args.kwargs["local_files_only"] is True

    async def test_default_local_provider_uses_local_asr(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.asr_transcribe", return_value=sample_entries) as mock_local,
            patch("subforge.orchestrator.deepgram_transcribe") as mock_deepgram,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        assert mock_local.call_count == 1
        mock_deepgram.assert_not_called()

    async def test_deepgram_provider_uses_deepgram_asr(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")
        config.asr_provider = "deepgram"
        config.deepgram_api_key = "dg-test"
        config.deepgram_model = "nova-3"
        config.deepgram_keyterms = ["社長"]

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.ensure_model") as mock_ensure_model,
            patch("subforge.orchestrator.asr_transcribe") as mock_local,
            patch("subforge.orchestrator.deepgram_transcribe", return_value=sample_entries) as mock_deepgram,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        mock_ensure_model.assert_not_called()
        mock_local.assert_not_called()
        assert mock_deepgram.call_count == 1
        _, kwargs = mock_deepgram.call_args
        assert kwargs["api_key"] == "dg-test"
        assert kwargs["model"] == "nova-3"
        assert kwargs["language"] == "ja"
        assert kwargs["keyterms"] == ["社長"]

    async def test_deepgram_missing_key_fails_file(self, config, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")
        config.asr_provider = "deepgram"
        config.deepgram_api_key = ""

        await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.FAILED
        assert "DeepgramAuthError" in (job.error or "")

    async def test_asr_failure(self, config, tmp_path):
        job = Job(file_path=tmp_path / "broken.mp3")

        with patch(
            "subforge.orchestrator.asr_transcribe",
            side_effect=RuntimeError("ASR crashed"),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.FAILED
        assert "RuntimeError" in (job.error or "")

    async def test_translation_failure_keeps_source_srt(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")

        async def bad_translate(msgs, cfg, activity_callback=None):
            raise LLMError("API down")

        with (
            patch(
                "subforge.orchestrator.asr_transcribe",
                return_value=sample_entries,
            ),
            patch(
                "subforge.orchestrator.translate_batch",
                side_effect=bad_translate,
            ),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.FAILED
        assert "API down" in (job.error or "")
        source_srt = tmp_path / "test.ja.srt"
        assert source_srt.exists()

    async def test_existing_target_srt_skips_whole_file(self, config, sample_entries, tmp_path):
        from subforge.translate.srt_io import write_srt

        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        write_srt(sample_entries, tmp_path / "test.zh.srt")

        with (
            patch("subforge.orchestrator.asr_transcribe") as mock_asr,
            patch("subforge.orchestrator.translate_batch", new_callable=AsyncMock) as mock_translate,
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        assert job.asr_progress == 1.0
        assert job.translate_progress == 1.0
        mock_asr.assert_not_called()
        mock_translate.assert_not_called()

    async def test_incomplete_target_srt_is_retranslated(self, config, sample_entries, tmp_path):
        from subforge.translate.srt_io import read_srt, write_srt

        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        write_srt(sample_entries, tmp_path / "test.ja.srt")
        incomplete = [sample_entries[0], sample_entries[1].__class__(
            sample_entries[1].index, sample_entries[1].start, sample_entries[1].end, "",
        )]
        write_srt(incomplete, tmp_path / "test.zh.srt")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.asr_transcribe") as mock_asr,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        mock_asr.assert_not_called()
        assert [entry.text for entry in read_srt(tmp_path / "test.zh.srt")] == ["你好", "世界"]

    async def test_legacy_source_srt_is_not_reused(self, config, sample_entries, tmp_path):
        from subforge.translate.srt_io import write_srt

        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        write_srt(sample_entries, tmp_path / "test.srt")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.asr_transcribe", return_value=sample_entries) as mock_asr,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        assert mock_asr.call_count == 1
        assert (tmp_path / "test.ja.srt").exists()

    async def test_existing_source_srt_skips_asr(self, config, sample_entries, tmp_path):
        from subforge.translate.srt_io import write_srt

        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        write_srt(sample_entries, tmp_path / "test.ja.srt")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.asr_transcribe") as mock_asr,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        mock_asr.assert_not_called()
        assert (tmp_path / "test.zh.srt").exists()

    async def test_existing_source_srt_skips_deepgram(self, config, sample_entries, tmp_path):
        from subforge.translate.srt_io import write_srt

        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        config.asr_provider = "deepgram"
        config.deepgram_api_key = "dg-test"
        write_srt(sample_entries, tmp_path / "test.ja.srt")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.deepgram_transcribe") as mock_deepgram,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        mock_deepgram.assert_not_called()

    async def test_force_ignores_existing_srt_files(self, config, sample_entries, tmp_path):
        from subforge.translate.srt_io import write_srt

        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        config.force = True
        write_srt([SubtitleEntry(index=1, start=0.0, end=1.0, text="old")], tmp_path / "test.ja.srt")
        write_srt([SubtitleEntry(index=1, start=0.0, end=1.0, text="old")], tmp_path / "test.zh.srt")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.asr_transcribe", return_value=sample_entries) as mock_asr,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        assert mock_asr.call_count == 1

    async def test_force_with_deepgram_calls_deepgram(self, config, sample_entries, tmp_path):
        from subforge.translate.srt_io import write_srt

        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        config.force = True
        config.asr_provider = "deepgram"
        config.deepgram_api_key = "dg-test"
        write_srt([SubtitleEntry(index=1, start=0.0, end=1.0, text="old")], tmp_path / "test.ja.srt")
        write_srt([SubtitleEntry(index=1, start=0.0, end=1.0, text="old")], tmp_path / "test.zh.srt")

        async def fake_translate(msgs, cfg, activity_callback=None):
            return "[1] 你好\n[2] 世界"

        with (
            patch("subforge.orchestrator.deepgram_transcribe", return_value=sample_entries) as mock_deepgram,
            patch("subforge.orchestrator.translate_batch", side_effect=fake_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        assert mock_deepgram.call_count == 1

    async def test_translation_failure_preserves_completed_batch(self, config, tmp_path):
        from subforge.resume import ResumeStore

        config.batch_size = 10
        config.context_size = 0
        config.translate_workers = 1
        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        entries = [
            SubtitleEntry(index=i, start=float(i), end=float(i) + 0.5, text=f"src{i}")
            for i in range(1, 16)
        ]

        async def flaky_translate(msgs, cfg, activity_callback=None):
            user_msg = msgs[-1]["content"]
            if "[11]" in user_msg:
                raise LLMError("batch failed")
            return "\n".join(f"[{i}] ok{i}" for i in range(1, 11))

        with (
            patch("subforge.orchestrator.asr_transcribe", return_value=entries),
            patch("subforge.orchestrator.translate_batch", side_effect=flaky_translate),
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.FAILED
        store = ResumeStore(config.jobs_dir)
        loaded = store.load(job, config)
        assert loaded is not None
        assert loaded.translation["completed_batches"]["0"][0]["text"] == "ok1"
        assert "1" not in loaded.translation["completed_batches"]

    async def test_second_run_processes_only_remaining_batch(self, config, tmp_path):
        from subforge.resume import ResumeStore
        from subforge.translate.srt_io import read_srt, write_srt

        config.batch_size = 10
        config.translate_workers = 1
        job = Job(file_path=tmp_path / "test.mp3")
        job.file_path.write_text("audio", encoding="utf-8")
        entries = [
            SubtitleEntry(index=i, start=float(i), end=float(i) + 0.5, text=f"src{i}")
            for i in range(1, 16)
        ]
        write_srt(entries, tmp_path / "test.ja.srt")

        store = ResumeStore(config.jobs_dir)
        state = store.create(job, config, tmp_path / "test.ja.srt", tmp_path / "test.zh.srt")
        store.save_batch(
            state,
            0,
            [SubtitleEntry(index=i, start=float(i), end=float(i) + 0.5, text=f"cached{i}") for i in range(1, 11)],
            total_batches=2,
        )

        async def translate_remaining(msgs, cfg, activity_callback=None):
            assert "[1]" not in msgs[-1]["content"].split("=== Entries to translate ===")[-1]
            return "\n".join(f"[{i}] live{i}" for i in range(11, 16))

        with (
            patch("subforge.orchestrator.asr_transcribe") as mock_asr,
            patch("subforge.orchestrator.translate_batch", side_effect=translate_remaining) as mock_translate,
        ):
            await process_one(job, config, pbar_slot=0)

        assert job.status == JobStatus.DONE
        mock_asr.assert_not_called()
        assert mock_translate.call_count == 1
        target_entries = read_srt(tmp_path / "test.zh.srt")
        assert target_entries[0].text == "cached1"
        assert target_entries[-1].text == "live15"


class TestProcessAll:
    async def test_empty_jobs(self, config):
        result = await process_all([], config)
        assert result["succeeded"] == 0
        assert result["failed"] == 0
        assert result["total_time"] == 0.0

    async def test_all_success(self, config, tmp_path):
        jobs = [Job(file_path=tmp_path / f"file{i}.mp3") for i in range(3)]

        sample = [SubtitleEntry(index=1, start=0.0, end=1.0, text="hello")]

        async def fake_translate_batch(msgs, cfg, activity_callback=None):
            return "[1] 译桩"

        with (
            patch(
                "subforge.orchestrator.asr_transcribe",
                return_value=sample,
            ),
            patch(
                "subforge.orchestrator.translate_batch",
                side_effect=fake_translate_batch,
            ),
        ):
            result = await process_all(jobs, config)

        assert result["succeeded"] == 3
        assert result["failed"] == 0
        for job in jobs:
            assert job.status == JobStatus.DONE

    async def test_failure_isolation(self, config, tmp_path):
        jobs = [Job(file_path=tmp_path / f"file{i}.mp3") for i in range(4)]

        def flaky_asr(file_path, **kwargs):
            if "file2" in str(file_path):
                raise RuntimeError("ASR failed")
            return [SubtitleEntry(index=1, start=0.0, end=1.0, text="hello")]

        async def fake_translate_batch(msgs, cfg, activity_callback=None):
            return "[1] 译桩"

        with (
            patch(
                "subforge.orchestrator.asr_transcribe",
                side_effect=flaky_asr,
            ),
            patch(
                "subforge.orchestrator.translate_batch",
                side_effect=fake_translate_batch,
            ),
        ):
            result = await process_all(jobs, config)

        assert result["succeeded"] == 3
        assert result["failed"] == 1

    async def test_concurrency_semaphore_limits(self, config, tmp_path):
        jobs = [Job(file_path=tmp_path / f"file{i}.mp3") for i in range(6)]
        config.concurrency = 2

        active = 0
        max_active = 0
        lock = asyncio.Lock()

        def tracking_asr(file_path, **kwargs):
            nonlocal active, max_active
            # Note: this runs in a thread via to_thread, so no real asyncio lock
            return [SubtitleEntry(index=1, start=0.0, end=1.0, text="x")]

        async def fake_translate_batch(msgs, cfg, activity_callback=None):
            nonlocal active, max_active
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            return "ok"

        with (
            patch(
                "subforge.orchestrator.asr_transcribe",
                side_effect=tracking_asr,
            ),
            patch(
                "subforge.orchestrator.translate_batch",
                side_effect=fake_translate_batch,
            ),
        ):
            await process_all(jobs, config)

        # Concurrency is controlled by Semaphore on the outer process_one,
        # but since ASR uses to_thread (which bypasses the semaphore's async
        # scope), we verify the semaphore limits the translation phase.
        assert max_active <= config.concurrency