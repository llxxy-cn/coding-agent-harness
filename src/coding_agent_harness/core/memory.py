from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from coding_agent_harness.domain.models import TaskId


class MemoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_type: StrictStr
    content: StrictStr = Field(max_length=2000)
    tags: tuple[StrictStr, ...]
    source: StrictStr
    created_at: datetime
    task_id: TaskId

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is not timezone.utc:
            raise ValueError("memory time must be native UTC")
        return value


class MemorySlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    records: tuple[MemoryRecord, ...] = Field(max_length=10)
