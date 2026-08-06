from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from coding_agent_harness.security.canonical import canonical_sha256
from coding_agent_harness.security.redaction import redact_text


_ASSIGNMENT = re.compile(r"(?i)\b(?:credential|token|secret|password)\s*=\s*[^\s]+")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SafeHistoryEntry(_FrozenModel):
    action_type: StrictStr
    safe_result: StrictStr = Field(max_length=8192)


class ContextSnapshot(_FrozenModel):
    user_task: StrictStr
    config_summary: StrictStr
    action_schema: tuple[StrictStr, ...]
    workspace_summary: StrictStr
    history: tuple[SafeHistoryEntry, ...]
    feedback_summary: StrictStr | None
    remaining_actions: StrictInt = Field(ge=0)
    remaining_feedback: StrictInt = Field(ge=0)


class PromptContext(_FrozenModel):
    user_task: StrictStr
    config_summary: StrictStr
    action_schema: tuple[StrictStr, ...]
    workspace_summary: StrictStr
    history: tuple[SafeHistoryEntry, ...]
    feedback_summary: StrictStr | None
    remaining_actions: StrictInt
    remaining_feedback: StrictInt
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class ContextManifest(_FrozenModel):
    history_count: StrictInt = Field(ge=0)
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


def _safe(value: str) -> str:
    return _ASSIGNMENT.sub("[REDACTED]", redact_text(value))


class ContextBuilder:
    def __init__(self, *, max_history: int = 8) -> None:
        if not 1 <= max_history <= 10:
            raise ValueError("history limit is invalid")
        self.max_history = max_history

    def build(self, snapshot: ContextSnapshot) -> PromptContext:
        history = tuple(SafeHistoryEntry(action_type=item.action_type, safe_result=_safe(item.safe_result)) for item in snapshot.history[-self.max_history:])
        values = {
            "user_task": _safe(snapshot.user_task),
            "config_summary": _safe(snapshot.config_summary),
            "action_schema": snapshot.action_schema,
            "workspace_summary": _safe(snapshot.workspace_summary),
            "history": tuple(item.model_dump() for item in history),
            "feedback_summary": _safe(snapshot.feedback_summary) if snapshot.feedback_summary else None,
            "remaining_actions": snapshot.remaining_actions,
            "remaining_feedback": snapshot.remaining_feedback,
        }
        return PromptContext(**values, sha256=canonical_sha256(values))
