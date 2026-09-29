from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class CreatorCreateRequest(BaseModel):
    name: str
    kind: Literal["voice_actor", "circle"] = "voice_actor"


class CreatorManageRequest(BaseModel):
    action: Literal["rename", "merge", "delete"]
    creator_id: str
    new_name: str | None = None
    target_creator_id: str | None = None
