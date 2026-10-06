from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    library_root: str | None = None
    proxy_url: str | None = None
    asr_concurrency: int = 1
    remote_asr_concurrency: int = 20
    remote_asr_task_concurrency: int = 20
    translate_workers: int = 20
    translation_prompt: str | None = None
    token_mode: bool = False
    no_auth: bool = False
    has_deepgram_key: bool = False
    has_fixed_token: bool = False


class SettingsUpdateRequest(BaseModel):
    proxy_url: str | None = None
    asr_concurrency: int | None = None
    remote_asr_concurrency: int | None = None
    remote_asr_task_concurrency: int | None = None
    translate_workers: int | None = None
    translation_prompt: str | None = None
    fixed_token: str | None = None
    no_auth: bool | None = None
    deepgram_api_key: str | None = None
