from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class SubtitleEntrySchema(BaseModel):
    index: int | None = None
    start: float
    end: float
    text: str


class SubtitlesResponse(BaseModel):
    source_language: str = "ja"
    target_language: str = "zh"
    source: list[SubtitleEntrySchema] = Field(default_factory=list)
    target: list[SubtitleEntrySchema] = Field(default_factory=list)


class SubtitleEditRequest(BaseModel):
    language: str
    index: int
    start: float
    end: float
    text: str


class SubtitleStructureRequest(BaseModel):
    language: str
    action: Literal["split", "merge"]
    index: int
    split_at: float | None = None
    merge_with: Literal["previous", "next"] | None = None


class SegmentReprocessRequest(BaseModel):
    start: float
    end: float
    asr_profile_id: str
    llm_profile_id: str


class SegmentCandidateResponse(BaseModel):
    processor: str
    target_start: float
    target_end: float
    warnings: list[str] = Field(default_factory=list)
    source_entries: list[SubtitleEntrySchema] = Field(default_factory=list)
    target_entries: list[SubtitleEntrySchema] = Field(default_factory=list)
    current_source: list[SubtitleEntrySchema] = Field(default_factory=list)
    current_target: list[SubtitleEntrySchema] = Field(default_factory=list)
