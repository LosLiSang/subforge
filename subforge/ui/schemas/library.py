from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class CreatorInfo(BaseModel):
    creator_id: str
    name: str
    kind: str = "voice_actor"
    item_count: int = 0


class TrackInfo(BaseModel):
    track_id: str
    item_id: str
    title: str
    duration: float = 0.0
    duration_label: str = "--:--"
    size: int = 0
    status: str = "playable"
    source_language: str = "ja"
    target_language: str = "zh"
    has_media: bool = True
    has_source_sub: bool = False
    has_target_sub: bool = False
    latest_task: dict[str, Any] | None = None


class ItemSummary(BaseModel):
    item_id: str
    title: str
    original_title: str | None = None
    rj_code: str | None = None
    release_date: str | None = None
    kind: str = "stream_archive"
    tags: list[str] = Field(default_factory=list)
    creator_ids: list[str] = Field(default_factory=list)
    creators: list[CreatorInfo] = Field(default_factory=list)
    cover_url: str
    cover_source: str | None = None
    track_count: int = 0
    total_duration: float = 0.0
    total_duration_label: str = "--:--"
    total_size: int = 0
    subtitle_status: str = "none"  # "none" | "jp" | "zh" | "bilingual"
    created_at: str | None = None
    updated_at: str | None = None


class ItemListResponse(BaseModel):
    items: list[ItemSummary]
    total: int
    page: int
    limit: int
    total_pages: int
    pages: int = 1
    all_tags: list[str] = Field(default_factory=list)
    tag_counts: dict[str, int] = Field(default_factory=dict)
    all_creators: list[CreatorInfo] = Field(default_factory=list)


class ItemDetailResponse(BaseModel):
    item: ItemSummary
    tracks: list[TrackInfo]
    overview: dict[str, Any]
    available_profiles: dict[str, Any]


class ItemEditRequest(BaseModel):
    title: str
    original_title: str | None = None
    rj_code: str | None = None
    release_date: str | None = None
    tags: list[str] = Field(default_factory=list)
    creator_ids: list[str] = Field(default_factory=list)


class ImportFolderPreviewGroup(BaseModel):
    title: str
    rj_code: str | None = None
    tracks: list[dict[str, Any]]


class ImportFolderPreviewResponse(BaseModel):
    folder_name: str
    groups: list[ImportFolderPreviewGroup]
