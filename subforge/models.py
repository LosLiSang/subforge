from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4


class JobStatus(Enum):
    QUEUED = "queued"
    ASR_RUNNING = "asr_running"
    TRANSLATING = "translating"
    DONE = "done"
    FAILED = "failed"


@dataclass
class SubtitleEntry:
    index: int
    start: float  # seconds
    end: float  # seconds
    text: str


@dataclass
class Job:
    file_path: Path
    source_lang: str = "ja"
    target_lang: str = "zh"
    model_size: str = "medium"
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    status: JobStatus = JobStatus.QUEUED
    asr_progress: float = 0.0
    translate_progress: float = 0.0
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
