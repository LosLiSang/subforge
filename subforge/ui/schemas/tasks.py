from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class TaskStatusItem(BaseModel):
    task_id: str
    status: str
    stage: str | None = None
    progress: float = 0.0
    completed: int | None = None
    total: int | None = None
    message: str | None = None


class ImportStatusResponse(BaseModel):
    task_id: str
    status: str
    message: str | None = None
    error: str | None = None
    progress: float | None = None
    item_id: str | None = None
    auto_process_status: str | None = None


class StartTaskRequest(BaseModel):
    model_profile_id: str | None = None
    translation_profile_id: str | None = None
    scope: str = "incomplete"
