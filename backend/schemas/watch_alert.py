from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


WatchEntityType = Literal["organization", "knowledge_entity"]
WatchFrequency = Literal["daily", "weekly", "manual"]
WatchTargetStatus = Literal["active", "paused", "disabled"]
SignalType = Literal[
    "new_intelligence",
    "website_change",
    "new_news",
    "new_video",
    "leadership_change",
    "contact_change",
    "score_change",
    "relation_change",
]
SignalSeverity = Literal["low", "medium", "high", "critical"]
WatchRunStatus = Literal["pending", "running", "success", "failed", "skipped"]


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


class WatchRunResponse(BaseModel):
    run_id: str
    watch_target_id: str
    status: WatchRunStatus
    items_found: int
    signals_created: int
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    watch_target_id: str
    entity_id: str
    signal_type: SignalType
    title: str
    summary: str | None = None
    severity: SignalSeverity
    evidence_id: str | None = None
    source_url: str | None = None
    old_value_json: dict | list | str | int | float | bool | None = None
    new_value_json: dict | list | str | int | float | bool | None = None
    detected_at: datetime
    created_at: datetime
    metadata_json: dict | list | str | int | float | bool | None = None


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    page: int
    page_size: int
    total: int
