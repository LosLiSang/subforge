from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Callable

from tqdm import tqdm

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    TASK_QUEUED = "task_queued"
    ASR_PREPARING = "asr_preparing"
    ASR_STARTED = "asr_started"
    ASR_PROGRESS = "asr_progress"
    ASR_COMPLETED = "asr_completed"
    TRANSLATION_STARTED = "translation_started"
    TRANSLATION_ACTIVITY = "translation_activity"
    TRANSLATION_PROGRESS = "translation_progress"
    TRANSLATION_COMPLETED = "translation_completed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


@dataclass(frozen=True)
class ProcessingEvent:
    type: EventType
    job_id: str
    stage: str | None = None
    progress: float | None = None
    completed: int | None = None
    total: int | None = None
    message: str | None = None
    error_type: str | None = None
    occurred_at: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["type"] = self.type.value
        return data


EventSink = Callable[[ProcessingEvent], None]


def make_event(event_type: EventType, job_id: str, **kwargs) -> ProcessingEvent:
    return ProcessingEvent(
        type=event_type,
        job_id=job_id,
        occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **kwargs,
    )


class CliProgressAdapter:
    """Render processing events as CLI progress bars."""

    def __init__(self, job_names: dict[str, str], positions: dict[str, int]) -> None:
        self.job_names = job_names
        self.positions = positions
        self.bars: dict[str, tqdm] = {}

    def __call__(self, event: ProcessingEvent) -> None:
        name = self.job_names.get(event.job_id, event.job_id)
        position = self.positions.get(event.job_id, 0)
        if event.type == EventType.ASR_PREPARING:
            self._close(event.job_id)
            self.bars[event.job_id] = tqdm(
                total=1.0, desc=f"[Model] {name}", position=position,
                leave=False, unit="", bar_format="{desc}: preparing | {elapsed}",
            )
        elif event.type == EventType.ASR_STARTED:
            self._close(event.job_id)
            self.bars[event.job_id] = tqdm(
                total=1.0, desc=f"[ASR] {name}", position=position,
                leave=False, unit="", bar_format="{desc}: {percentage:3.0f}%|{bar}| {elapsed}",
            )
        elif event.type == EventType.ASR_PROGRESS:
            self._update(event.job_id, event.progress or 0.0)
        elif event.type == EventType.ASR_COMPLETED:
            self._update(event.job_id, 1.0)
            self._close(event.job_id)
        elif event.type == EventType.TRANSLATION_STARTED:
            self._close(event.job_id)
            self.bars[event.job_id] = tqdm(
                total=event.total or 0, desc=f"[Translate] {name}", position=position,
                leave=False, unit="batch",
                bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} batches",
            )
        elif event.type == EventType.TRANSLATION_PROGRESS:
            self._update(event.job_id, event.completed or 0)
        elif event.type in {
            EventType.TRANSLATION_COMPLETED, EventType.TASK_COMPLETED, EventType.TASK_FAILED,
        }:
            self._close(event.job_id)

    def _update(self, job_id: str, value: float | int) -> None:
        bar = self.bars.get(job_id)
        if bar:
            bar.n = value
            bar.refresh()

    def _close(self, job_id: str) -> None:
        bar = self.bars.pop(job_id, None)
        if bar:
            bar.close()

    def close(self) -> None:
        for job_id in list(self.bars):
            self._close(job_id)


def emit_event(sink: EventSink | None, event: ProcessingEvent) -> None:
    """Publish an event without allowing an adapter failure to break processing."""
    if sink is None:
        return
    try:
        sink(event)
    except Exception:
        logger.warning("Processing event sink failed for %s", event.type, exc_info=True)
