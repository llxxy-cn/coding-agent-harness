"""Immutable domain value objects defined by SPEC section 11."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from .enums import FeedbackKind, ProtocolErrorCode, TestPhase, TestRunOutcome, ToolErrorCode


_HASH_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"


def _strict_utf8(value: str) -> bytes:
    return value.encode("utf-8", errors="strict")


def _validate_uuid4(value: object) -> UUID:
    if isinstance(value, UUID):
        parsed = value
    elif isinstance(value, str):
        parsed = UUID(value)
        if value != str(parsed):
            raise ValueError("UUID must use canonical lowercase hyphenated form")
    else:
        raise ValueError("UUID must be a UUID or canonical string")
    if parsed.version != 4 or parsed.variant != "specified in RFC 4122":
        raise ValueError("UUID must be RFC 4122 version 4")
    return parsed


def _validate_safe_single_line(value: str, *, max_chars: int = 2000, max_bytes: int = 8192) -> str:
    encoded = _strict_utf8(value)
    if not 1 <= len(value) <= max_chars or len(encoded) > max_bytes:
        raise ValueError("safe message length is invalid")
    if not value.strip() or value != value.strip():
        raise ValueError("safe message whitespace is invalid")
    if any(unicodedata.category(char) == "Cc" for char in value) or any(char in "\u2028\u2029" for char in value):
        raise ValueError("safe message contains a control")
    return value


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class ValidatedAction(_FrozenModel):
    """Abstract marker for a validated concrete LLM action."""

    def __init__(self, **data: object) -> None:
        if type(self) is ValidatedAction:
            raise TypeError("ValidatedAction is abstract")
        super().__init__(**data)


class ProtocolError(_FrozenModel):
    code: ProtocolErrorCode
    sanitized_message: StrictStr


class TaskId(_FrozenModel):
    value: UUID

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> UUID:
        return _validate_uuid4(value)


class ArtifactRef(_FrozenModel):
    artifact_id: UUID
    task_id: TaskId
    schema_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_.]{0,127}$")
    schema_version: StrictInt = Field(ge=1, le=65535)
    media_type: StrictStr = Field(pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$")
    byte_length: StrictInt = Field(ge=0, le=2**63 - 1)
    sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @field_validator("artifact_id", mode="before")
    @classmethod
    def validate_artifact_id(cls, value: object) -> UUID:
        return _validate_uuid4(value)


class FrozenCommand(_FrozenModel):
    argv: tuple[StrictStr, ...]

    @field_validator("argv", mode="before")
    @classmethod
    def require_json_array(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("argv must be a JSON array")
        return value

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, argv: tuple[str, ...]) -> tuple[str, ...]:
        if not 1 <= len(argv) <= 64:
            raise ValueError("argv count is invalid")
        if argv[0] == "pytest":
            pass
        elif len(argv) >= 3 and argv[:3] == ("python", "-m", "pytest"):
            pass
        else:
            raise ValueError("test command prefix is invalid")
        total = 0
        for item in argv:
            encoded = _strict_utf8(item)
            if not 1 <= len(item) <= 4096 or item != item.strip() or any(char in item for char in "\x00\r\n"):
                raise ValueError("argv item is invalid")
            total += len(encoded)
        if total > 32768:
            raise ValueError("argv byte total is invalid")
        return argv


class ToolPayload(_FrozenModel):
    """Abstract base for concrete tool payloads defined by later Tasks."""

    def __init__(self, **data: object) -> None:
        if type(self) is ToolPayload:
            raise TypeError("ToolPayload is abstract")
        super().__init__(**data)


PayloadT = TypeVar("PayloadT", bound=ToolPayload)


class ToolResult(_FrozenModel, Generic[PayloadT]):
    ok: StrictBool
    payload: PayloadT | None
    error_code: ToolErrorCode | None
    sanitized_message: StrictStr | None

    @model_validator(mode="after")
    def validate_matrix(self) -> ToolResult[PayloadT]:
        if self.ok:
            if self.payload is None or self.error_code is not None or self.sanitized_message is not None:
                raise ValueError("successful tool result fields are inconsistent")
        else:
            if self.payload is not None or self.error_code is None or self.sanitized_message is None:
                raise ValueError("failed tool result fields are inconsistent")
            _validate_safe_single_line(self.sanitized_message)
        return self


class TestRun(_FrozenModel):
    run_id: UUID
    task_id: TaskId
    phase: TestPhase
    outcome: TestRunOutcome
    command: FrozenCommand
    base_commit: StrictStr = Field(pattern=_COMMIT_PATTERN)
    config_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    environment_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    workspace_before_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    workspace_after_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    started_at: datetime
    finished_at: datetime
    duration_ms: StrictInt = Field(ge=0, le=2**63 - 1)
    exit_code: StrictInt | None
    sanitized_output_ref: ArtifactRef
    parsed_result_ref: ArtifactRef | None

    @field_validator("run_id", mode="before")
    @classmethod
    def validate_run_id(cls, value: object) -> UUID:
        return _validate_uuid4(value)

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_native_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is not timezone.utc or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("timestamp must use native UTC")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> TestRun:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at precedes started_at")
        same_workspace = self.workspace_before_sha256 == self.workspace_after_sha256
        if self.outcome is TestRunOutcome.WORKSPACE_DRIFT:
            if same_workspace or self.parsed_result_ref is not None:
                raise ValueError("workspace drift fields are inconsistent")
        elif not same_workspace:
            raise ValueError("only workspace drift may change workspace hash")

        parsed_required = self.outcome in {TestRunOutcome.PASSED, TestRunOutcome.FAILED}
        if parsed_required != (self.parsed_result_ref is not None):
            raise ValueError("parsed result presence is inconsistent")
        if self.outcome is TestRunOutcome.PASSED and self.exit_code != 0:
            raise ValueError("passed requires exit code zero")
        if self.outcome is TestRunOutcome.FAILED and (self.exit_code is None or self.exit_code == 0):
            raise ValueError("failed requires nonzero exit code")
        if self.outcome in {TestRunOutcome.TIMED_OUT, TestRunOutcome.CANCELLED, TestRunOutcome.UNKNOWN_OUTCOME} and self.exit_code is not None:
            raise ValueError("outcome requires no exit code")
        if self.outcome is TestRunOutcome.UNPARSEABLE and self.exit_code is None:
            raise ValueError("unparseable requires an exit code")
        if self.sanitized_output_ref.task_id != self.task_id or self.sanitized_output_ref.schema_id != "sanitized_test_output" or self.sanitized_output_ref.schema_version != 1 or self.sanitized_output_ref.media_type != "application/json":
            raise ValueError("sanitized output artifact contract is invalid")
        if self.parsed_result_ref is not None and (self.parsed_result_ref.task_id != self.task_id or self.parsed_result_ref.schema_id != "parsed_result" or self.parsed_result_ref.schema_version != 1 or self.parsed_result_ref.media_type != "application/json"):
            raise ValueError("parsed result artifact contract is invalid")
        return self


class FeedbackDecision(_FrozenModel):
    kind: FeedbackKind
    current_run_id: UUID
    previous_run_id: UUID | None
    matched_history_run_id: UUID | None
    state_fingerprint_sha256: StrictStr | None
    sanitized_summary: StrictStr

    @field_validator("current_run_id", "previous_run_id", "matched_history_run_id", mode="before")
    @classmethod
    def validate_optional_uuid(cls, value: object) -> UUID | None:
        return None if value is None else _validate_uuid4(value)

    @field_validator("state_fingerprint_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
            raise ValueError("fingerprint must be lowercase SHA-256")
        return value

    @field_validator("sanitized_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _validate_safe_single_line(value)

    @model_validator(mode="after")
    def validate_matrix(self) -> FeedbackDecision:
        unreliable = self.kind in {FeedbackKind.ENVIRONMENT_ERROR, FeedbackKind.UNPARSEABLE}
        if unreliable:
            if self.matched_history_run_id is not None or self.state_fingerprint_sha256 is not None:
                raise ValueError("unreliable feedback fields are inconsistent")
            return self
        if self.state_fingerprint_sha256 is None:
            raise ValueError("reliable feedback requires a fingerprint")
        if self.kind is FeedbackKind.PASSED:
            if self.matched_history_run_id is not None:
                raise ValueError("passed cannot match history")
        else:
            if self.previous_run_id is None or self.previous_run_id == self.current_run_id:
                raise ValueError("comparison feedback requires a different previous run")
        if self.kind is FeedbackKind.LOOP:
            if self.matched_history_run_id is None or self.matched_history_run_id == self.current_run_id:
                raise ValueError("loop requires a different matched run")
        elif self.matched_history_run_id is not None:
            raise ValueError("only loop may match history")
        return self
