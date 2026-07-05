from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


WatchEntityType = Literal["organization", "knowledge_entity"]
WatchFrequency = Literal["daily", "weekly", "manual"]
WatchTargetStatus = Literal["active", "paused", "disabled"]


class ApiErrorResponse(BaseModel):
    error_code: str
    message: str


class WatchTargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1)
    entity_type: WatchEntityType
    frequency: WatchFrequency = "daily"


class WatchTargetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WatchTargetStatus | None = None
    frequency: WatchFrequency | None = None


class WatchTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_id: str
    entity_type: WatchEntityType
    status: WatchTargetStatus
    frequency: WatchFrequency
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int
    created_at: datetime
    updated_at: datetime


class WatchTargetListResponse(BaseModel):
    items: list[WatchTargetResponse]
    page: int
    page_size: int
    total: int
