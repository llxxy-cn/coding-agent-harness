from __future__ import annotations

from enum import Enum, unique

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from coding_agent_harness.domain.enums import PolicyOutcome


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


@unique
class PolicyReasonCode(str, Enum):
    ALLOWED = "allowed"
    TEST_ASSET_PROTECTION = "test_asset_protection"
    PROTECTED_CONFIG = "protected_config"
    PATH_SAFETY = "path_safety"
    BINARY_UNSUPPORTED = "binary_unsupported"
    SHELL_FORBIDDEN = "shell_forbidden"
    CAPABILITY_MISSING = "capability_missing"
    DEMO_ESCAPE = "demo_escape"
    PATCH_HARD_LIMIT = "patch_hard_limit"
    PATCH_REQUIRES_APPROVAL = "patch_requires_approval"
    SOURCE_DELETE = "source_delete"
    SENSITIVE_PATH = "sensitive_path"
    DEPENDENCY_CONFIG = "dependency_config"


class PolicyFacts(_FrozenModel):
    file_count: StrictInt = Field(default=0, ge=0)
    changed_lines: StrictInt = Field(default=0, ge=0)
    payload_bytes: StrictInt = Field(default=0, ge=0)
    touches_test_assets: StrictBool = False
    protected_config: StrictBool = False
    path_escape: StrictBool = False
    symlink: StrictBool = False
    binary: StrictBool = False
    shell: StrictBool = False
    capability_missing: StrictBool = False
    demo_escape: StrictBool = False
    source_delete: StrictBool = False
    sensitive_path: StrictBool = False
    dependency_config: StrictBool = False


class PolicyDecision(_FrozenModel):
    outcome: PolicyOutcome
    reason_code: PolicyReasonCode


class PolicyEngine:
    def evaluate(self, action, facts, config, approval) -> PolicyDecision:
        del action, config, approval
        changed_lines = getattr(
            facts,
            "changed_lines",
            getattr(facts, "added_lines", 0) + getattr(facts, "deleted_lines", 0),
        )

        deny_rules = (
            (getattr(facts, "touches_test_assets", False), PolicyReasonCode.TEST_ASSET_PROTECTION),
            (getattr(facts, "protected_config", False), PolicyReasonCode.PROTECTED_CONFIG),
            (getattr(facts, "path_escape", False) or getattr(facts, "symlink", False), PolicyReasonCode.PATH_SAFETY),
            (getattr(facts, "binary", False), PolicyReasonCode.BINARY_UNSUPPORTED),
            (getattr(facts, "shell", False), PolicyReasonCode.SHELL_FORBIDDEN),
            (getattr(facts, "capability_missing", False), PolicyReasonCode.CAPABILITY_MISSING),
            (getattr(facts, "demo_escape", False), PolicyReasonCode.DEMO_ESCAPE),
            (
                getattr(facts, "file_count", 0) > 20
                or changed_lines > 2000
                or getattr(facts, "payload_bytes", 0) > 1_048_576,
                PolicyReasonCode.PATCH_HARD_LIMIT,
            ),
        )
        for matches, reason in deny_rules:
            if matches:
                return PolicyDecision(outcome=PolicyOutcome.DENY, reason_code=reason)

        approval_rules = (
            (getattr(facts, "file_count", 0) > 5 or changed_lines > 300, PolicyReasonCode.PATCH_REQUIRES_APPROVAL),
            (getattr(facts, "source_delete", False), PolicyReasonCode.SOURCE_DELETE),
            (
                getattr(facts, "sensitive_path", False) or getattr(facts, "touches_sensitive_paths", False),
                PolicyReasonCode.SENSITIVE_PATH,
            ),
            (getattr(facts, "dependency_config", False), PolicyReasonCode.DEPENDENCY_CONFIG),
        )
        for matches, reason in approval_rules:
            if matches:
                return PolicyDecision(outcome=PolicyOutcome.REQUIRE_APPROVAL, reason_code=reason)

        return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason_code=PolicyReasonCode.ALLOWED)
