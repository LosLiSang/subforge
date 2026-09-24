import time
from pathlib import Path

from subforge.models import Job, JobStatus, SubtitleEntry


class TestSubtitleEntry:
    def test_create_entry(self):
        entry = SubtitleEntry(index=1, start=0.0, end=2.5, text="こんにちは")
        assert entry.index == 1
        assert entry.start == 0.0
        assert entry.end == 2.5
        assert entry.text == "こんにちは"


class TestJobStatus:
    def test_all_statuses(self):
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.ASR_RUNNING.value == "asr_running"
        assert JobStatus.TRANSLATING.value == "translating"
        assert JobStatus.DONE.value == "done"
        assert JobStatus.FAILED.value == "failed"


class TestJob:
    def test_defaults(self):
        job = Job(file_path=Path("test.mp3"))
        assert job.file_path == Path("test.mp3")
        assert job.source_lang == "ja"
        assert job.target_lang == "zh"
        assert job.model_size == "medium"
        assert job.status == JobStatus.QUEUED
        assert job.asr_progress == 0.0
        assert job.translate_progress == 0.0
        assert job.error is None
        assert job.started_at is None
        assert job.finished_at is None
        assert len(job.id) == 8

    def test_custom_params(self):
        job = Job(
            file_path=Path("lecture.wav"),
            source_lang="en",
            target_lang="zh",
            model_size="large",
        )
        assert job.source_lang == "en"
        assert job.target_lang == "zh"
        assert job.model_size == "large"

    def test_unique_ids(self):
        job1 = Job(file_path=Path("a.mp3"))
        job2 = Job(file_path=Path("b.mp3"))
        assert job1.id != job2.id

    def test_lifecycle(self):
        job = Job(file_path=Path("test.mp3"))
        assert job.status == JobStatus.QUEUED

        job.status = JobStatus.ASR_RUNNING
        job.started_at = time.time()
        assert job.status == JobStatus.ASR_RUNNING
        assert job.started_at is not None

        job.status = JobStatus.TRANSLATING
        job.asr_progress = 1.0
        assert job.status == JobStatus.TRANSLATING
        assert job.asr_progress == 1.0

        job.status = JobStatus.DONE
        job.translate_progress = 1.0
        job.finished_at = time.time()
        assert job.status == JobStatus.DONE
        assert job.translate_progress == 1.0
        assert job.finished_at is not None

    def test_failure_state(self):
        job = Job(file_path=Path("broken.mp3"))
        job.status = JobStatus.FAILED
        job.error = "ASR model download failed"
        assert job.status == JobStatus.FAILED
        assert job.error == "ASR model download failed"
