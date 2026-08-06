from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from coding_agent_harness.domain.enums import ApprovalStatus
from coding_agent_harness.domain.models import TaskId


_HASH_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"


class ApprovalBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)

    task_id: TaskId
    action_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    diff_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    target_paths: tuple[StrictStr, ...]
    pre_image_hashes: tuple[StrictStr, ...]
    config_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    capability_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    risk_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    base_commit: StrictStr = Field(pattern=_COMMIT_PATTERN)
    status: ApprovalStatus


def verify_approval_binding(expected: ApprovalBinding, actual: ApprovalBinding) -> bool:
    return expected == actual and actual.status is ApprovalStatus.APPROVED


def can_execute_approval(binding: ApprovalBinding, *, resume_requested: StrictBool) -> bool:
    return bool(resume_requested and binding.status is ApprovalStatus.APPROVED)
