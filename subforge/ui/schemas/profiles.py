from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class TestConnectionResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: float | None = None


class ModelCheckResponse(BaseModel):
    cached: bool
    path: str | None = None
