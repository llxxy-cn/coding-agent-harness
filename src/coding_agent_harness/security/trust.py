from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr


_HASH_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"


class TrustBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repository_identity: StrictStr
    base_commit: StrictStr = Field(pattern=_COMMIT_PATTERN)
    command_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    config_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    capability_hash: StrictStr = Field(pattern=_HASH_PATTERN)
    provider: StrictStr
    threat_notice_version: StrictStr
    data_categories: tuple[StrictStr, ...]
    mode: StrictStr


def verify_trust_binding(expected: TrustBinding, actual: TrustBinding) -> bool:
    return expected == actual
