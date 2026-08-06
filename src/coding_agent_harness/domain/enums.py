"""Closed domain vocabularies defined by SPEC sections 9 and 11."""

from enum import Enum, unique


class _StringEnum(str, Enum):
    """A string enum whose JSON representation is its exact value."""


@unique
class ProtocolErrorCode(_StringEnum):
    INVALID_JSON = "invalid_json"
    INVALID_TOP_LEVEL = "invalid_top_level"
    MISSING_TYPE = "missing_type"
    INVALID_TYPE = "invalid_type"
    UNKNOWN_ACTION = "unknown_action"
    SCHEMA_VIOLATION = "schema_violation"


@unique
class ToolErrorCode(_StringEnum):
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    SAFETY_VIOLATION = "safety_violation"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    ENVIRONMENT_ERROR = "environment_error"
    EXECUTION_FAILED = "execution_failed"
    UNKNOWN_OUTCOME = "unknown_outcome"


@unique
class TestPhase(_StringEnum):
    BASELINE = "baseline"
    FOCUSED = "focused"
    POST_PATCH = "post_patch"
    RECOVERY = "recovery"
    RESUME_VALIDATION = "resume_validation"
    REQUESTED_FULL = "requested_full"


@unique
class TestRunOutcome(_StringEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    RESOURCE_LIMIT = "resource_limit"
    ENVIRONMENT_ERROR = "environment_error"
    UNPARSEABLE = "unparseable"
    CANCELLED = "cancelled"
    UNKNOWN_OUTCOME = "unknown_outcome"
    WORKSPACE_DRIFT = "workspace_drift"


@unique
class FeedbackKind(_StringEnum):
    PASSED = "passed"
    PROGRESS = "progress"
    NO_PROGRESS = "no_progress"
    CHANGED = "changed"
    REGRESSION = "regression"
    LOOP = "loop"
    ENVIRONMENT_ERROR = "environment_error"
    UNPARSEABLE = "unparseable"


@unique
class TaskStatus(_StringEnum):
    CREATED = "created"
    PREFLIGHT = "preflight"
    AWAITING_TRUST = "awaiting_trust"
    PREFLIGHT_FAILED = "preflight_failed"
    PREPARING_WORKSPACE = "preparing_workspace"
    BASELINE_TESTING = "baseline_testing"
    CANNOT_REPRODUCE = "cannot_reproduce"
    DECIDING = "deciding"
    VALIDATING_ACTION = "validating_action"
    PREPARING_PATCH = "preparing_patch"
    POLICY_CHECK = "policy_check"
    AWAITING_APPROVAL = "awaiting_approval"
    RESUME_VALIDATION = "resume_validation"
    REVALIDATING_PATCH = "revalidating_patch"
    APPLYING_PATCH = "applying_patch"
    COMPENSATION_ROLLBACK = "compensation_rollback"
    EXECUTING_NON_PATCH = "executing_non_patch"
    TESTING = "testing"
    SUCCEEDED = "succeeded"
    REGRESSION_ROLLBACK = "regression_rollback"
    RECOVERY_TESTING = "recovery_testing"
    PAUSED_FOR_HUMAN = "paused_for_human"
    STOPPED = "stopped"
    CANCELLED = "cancelled"


@unique
class ActionStatus(_StringEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    INTERRUPTED = "interrupted"
    UNKNOWN_OUTCOME = "unknown_outcome"


@unique
class PolicyOutcome(_StringEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@unique
class ApprovalStatus(_StringEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CONSUMED = "consumed"
    EXECUTED = "executed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
