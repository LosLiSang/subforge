import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from subforge.config import Config
from subforge.models import Job, JobStatus, SubtitleEntry
from subforge.orchestrator import process_all, process_one
from subforge.translate.llm_client import LLMError


@pytest.fixture
def config():
    return Config(
        source_lang="ja",
        target_lang="zh",
        concurrency=2,
    )


@pytest.fixture
def sample_entries():
    return [
        SubtitleEntry(index=1, start=0.0, end=1.0, text="こんにちは"),
        SubtitleEntry(index=2, start=1.0, end=2.0, text="世界"),
    ]


class TestProcessOne:
    async def test_successful_pipeline(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")

        async def fake_translate(msgs, cfg):
            return "translated"

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
            await process_one(job, config)

        assert job.status == JobStatus.DONE
        assert job.asr_progress == 1.0
        assert job.translate_progress == 1.0
        assert job.error is None

    async def test_asr_failure(self, config, tmp_path):
        job = Job(file_path=tmp_path / "broken.mp3")

        with patch(
            "subforge.orchestrator.asr_transcribe",
            side_effect=RuntimeError("ASR crashed"),
        ):
            await process_one(job, config)

        assert job.status == JobStatus.FAILED
        assert "RuntimeError" in (job.error or "")

    async def test_translation_failure_keeps_source_srt(self, config, sample_entries, tmp_path):
        job = Job(file_path=tmp_path / "test.mp3")

        async def bad_translate(msgs, cfg):
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
            await process_one(job, config)

        assert job.status == JobStatus.FAILED
        assert "API down" in (job.error or "")
        source_srt = tmp_path / "test.srt"
        assert source_srt.exists()


class TestProcessAll:
    async def test_empty_jobs(self, config):
        result = await process_all([], config)
        assert result["succeeded"] == 0
        assert result["failed"] == 0
        assert result["total_time"] == 0.0

    async def test_all_success(self, config, tmp_path):
        jobs = [Job(file_path=tmp_path / f"file{i}.mp3") for i in range(3)]

        sample = [SubtitleEntry(index=1, start=0.0, end=1.0, text="hello")]

        async def fake_translate_batch(msgs, cfg):
            return "translated"

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

        async def fake_translate_batch(msgs, cfg):
            return "translated"

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

        async def fake_translate_batch(msgs, cfg):
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
