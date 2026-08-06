"""Contract tests for immutable domain models in SPEC section 11."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import unique
from uuid import UUID

import pytest
from pydantic import StrictStr

from coding_agent_harness.domain.enums import (
    ActionStatus,
    ApprovalStatus,
    FeedbackKind,
    PolicyOutcome,
    TaskStatus,
    TestPhase as HarnessTestPhase,
    TestRunOutcome as HarnessTestRunOutcome,
    ToolErrorCode,
)
from coding_agent_harness.domain.models import (
    ArtifactRef,
    FeedbackDecision,
    FrozenCommand,
    TaskId,
    TestRun as HarnessTestRun,
    ToolPayload,
    ToolResult,
)


TASK_UUID = "123e4567-e89b-42d3-a456-426614174000"
RUN_UUID = "223e4567-e89b-42d3-a456-426614174000"
PREVIOUS_UUID = "323e4567-e89b-42d3-a456-426614174000"
MATCHED_UUID = "423e4567-e89b-42d3-a456-426614174000"
OUTPUT_UUID = "523e4567-e89b-42d3-a456-426614174000"
PARSED_UUID = "623e4567-e89b-42d3-a456-426614174000"
HASH_A, HASH_B = "a" * 64, "b" * 64


class EmptyTestPayload(ToolPayload):
    marker: StrictStr


def task_id() -> TaskId:
    return TaskId(value=TASK_UUID)


def artifact_ref(artifact_id=OUTPUT_UUID, schema_id="sanitized_test_output", task=None) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        task_id=task or task_id(),
        schema_id=schema_id,
        schema_version=1,
        media_type="application/json",
        byte_length=12,
        sha256=HASH_A,
    )


def test_task_id_is_canonical_frozen_rfc4122_uuid4():
    value = task_id()
    assert value.value == UUID(TASK_UUID)
    assert value.model_dump(mode="json") == {"value": TASK_UUID}
    with pytest.raises(Exception):
        value.value = UUID(RUN_UUID)
    for invalid in ["00000000-0000-0000-0000-000000000000", "123e4567-e89b-12d3-a456-426614174000", TASK_UUID.upper(), TASK_UUID.replace("-", ""), "{" + TASK_UUID + "}", 1, TASK_UUID.encode()]:
        with pytest.raises(Exception):
            TaskId(value=invalid)


def test_artifact_ref_has_exact_fields_and_constraints():
    ref = artifact_ref()
    assert set(type(ref).model_fields) == {"artifact_id", "task_id", "schema_id", "schema_version", "media_type", "byte_length", "sha256"}
    base = ref.model_dump()
    for mutation in [{"artifact_id": "00000000-0000-0000-0000-000000000000"}, {"schema_id": "Bad"}, {"schema_version": 0}, {"schema_version": True}, {"media_type": "Application/JSON"}, {"media_type": "application/json; charset=utf-8"}, {"byte_length": -1}, {"byte_length": True}, {"sha256": "A" * 64}, {"sha256": "a" * 63}]:
        with pytest.raises(Exception):
            ArtifactRef(**(base | mutation))
    for forbidden in ["path", "uri", "created_at", "content", "compression", "sensitivity"]:
        with pytest.raises(Exception):
            ArtifactRef(**(base | {forbidden: "x"}))


@pytest.mark.parametrize("argv", [["pytest"], ["pytest", "-q"], ["python", "-m", "pytest"], ["python", "-m", "pytest", "tests/test_a.py"]])
def test_frozen_command_accepts_only_two_prefixes_and_freezes_array(argv):
    command = FrozenCommand(argv=argv)
    assert command.argv == tuple(argv)
    with pytest.raises(Exception):
        command.argv = ("pytest",)


@pytest.mark.parametrize("argv", [[], ["python.exe", "-m", "pytest"], ["python3", "-m", "pytest"], ["py", "-m", "pytest"], ["python", "pytest"], ["python", "-m", "unittest"], ["/usr/bin/pytest"], ["pytest", ""], ["pytest", " leading"], ["pytest", "trailing "], ["pytest", "x\n"], ["pytest", "\ud800"], ["pytest"] + ["x"] * 64, ["pytest", "x" * 4097], ["pytest"] + ["x" * 4096] * 9])
def test_frozen_command_rejects_invalid_prefix_shape_and_bounds(argv):
    with pytest.raises(Exception):
        FrozenCommand(argv=argv)


def test_frozen_command_requires_json_array_and_forbids_execution_context():
    with pytest.raises(Exception):
        FrozenCommand(argv=("pytest",))
    for field in ["command", "cwd", "env", "timeout", "shell", "config_sha256", "source"]:
        with pytest.raises(Exception):
            FrozenCommand(argv=["pytest"], **{field: "x"})


def test_tool_payload_is_abstract_frozen_and_extra_forbidden():
    with pytest.raises(TypeError):
        ToolPayload()
    payload = EmptyTestPayload(marker="empty")
    with pytest.raises(Exception):
        payload.marker = "changed"
    with pytest.raises(Exception):
        EmptyTestPayload(marker="empty", extra="x")


def test_tool_result_has_four_required_fields_and_exact_matrix():
    payload = EmptyTestPayload(marker="empty")
    assert ToolResult[EmptyTestPayload](ok=True, payload=payload, error_code=None, sanitized_message=None).payload is payload
    assert ToolResult[EmptyTestPayload](ok=False, payload=None, error_code=ToolErrorCode.NOT_FOUND, sanitized_message="Target was not found.").error_code is ToolErrorCode.NOT_FOUND
    invalid = [
        {"ok": True, "payload": None, "error_code": None, "sanitized_message": None},
        {"ok": True, "payload": payload, "error_code": ToolErrorCode.CONFLICT, "sanitized_message": None},
        {"ok": True, "payload": payload, "error_code": None, "sanitized_message": "message"},
        {"ok": False, "payload": payload, "error_code": ToolErrorCode.CONFLICT, "sanitized_message": "Conflict."},
        {"ok": False, "payload": None, "error_code": None, "sanitized_message": "Conflict."},
        {"ok": False, "payload": None, "error_code": ToolErrorCode.CONFLICT, "sanitized_message": None},
    ]
    for values in invalid:
        with pytest.raises(Exception):
            ToolResult[EmptyTestPayload](**values)
    for missing in ["ok", "payload", "error_code", "sanitized_message"]:
        values = {"ok": True, "payload": payload, "error_code": None, "sanitized_message": None}
        values.pop(missing)
        with pytest.raises(Exception):
            ToolResult[EmptyTestPayload](**values)


@pytest.mark.parametrize("message", ["", "   ", " leading", "trailing ", "line\nbreak", "tab\there", "\u2028", "\ud800", "x" * 2001, "😀" * 2049])
def test_tool_result_failure_message_is_safe_and_bounded(message):
    with pytest.raises(Exception):
        ToolResult[EmptyTestPayload](ok=False, payload=None, error_code=ToolErrorCode.CONFLICT, sanitized_message=message)


def run_values(**changes):
    values = dict(
        run_id=RUN_UUID,
        task_id=task_id(),
        phase=HarnessTestPhase.BASELINE,
        outcome=HarnessTestRunOutcome.CANCELLED,
        command=FrozenCommand(argv=["pytest"]),
        base_commit="a" * 40,
        config_sha256=HASH_A,
        environment_sha256=HASH_B,
        workspace_before_sha256=HASH_A,
        workspace_after_sha256=HASH_A,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=0,
        exit_code=None,
        sanitized_output_ref=artifact_ref(),
        parsed_result_ref=None,
    )
    return values | changes


def test_test_run_pass_fail_and_workspace_drift_matrix():
    parsed = artifact_ref(PARSED_UUID, "parsed_result")
    assert HarnessTestRun(**run_values(outcome=HarnessTestRunOutcome.PASSED, exit_code=0, parsed_result_ref=parsed)).exit_code == 0
    assert HarnessTestRun(**run_values(outcome=HarnessTestRunOutcome.FAILED, exit_code=1, parsed_result_ref=parsed)).exit_code == 1
    assert HarnessTestRun(**run_values(outcome=HarnessTestRunOutcome.WORKSPACE_DRIFT, exit_code=0, workspace_after_sha256=HASH_B)).parsed_result_ref is None
    for values in [run_values(outcome=HarnessTestRunOutcome.PASSED, exit_code=1, parsed_result_ref=parsed), run_values(outcome=HarnessTestRunOutcome.PASSED, exit_code=0), run_values(outcome=HarnessTestRunOutcome.FAILED, exit_code=0, parsed_result_ref=parsed), run_values(outcome=HarnessTestRunOutcome.FAILED, exit_code=1), run_values(outcome=HarnessTestRunOutcome.FAILED, exit_code=1, parsed_result_ref=parsed, workspace_after_sha256=HASH_B), run_values(outcome=HarnessTestRunOutcome.WORKSPACE_DRIFT, workspace_after_sha256=HASH_A)]:
        with pytest.raises(Exception):
            HarnessTestRun(**values)


@pytest.mark.parametrize(("outcome", "exit_code"), [(HarnessTestRunOutcome.TIMED_OUT, None), (HarnessTestRunOutcome.RESOURCE_LIMIT, None), (HarnessTestRunOutcome.RESOURCE_LIMIT, 137), (HarnessTestRunOutcome.ENVIRONMENT_ERROR, None), (HarnessTestRunOutcome.ENVIRONMENT_ERROR, 2), (HarnessTestRunOutcome.UNPARSEABLE, 0), (HarnessTestRunOutcome.UNPARSEABLE, 1), (HarnessTestRunOutcome.CANCELLED, None), (HarnessTestRunOutcome.UNKNOWN_OUTCOME, None)])
def test_test_run_nonparsed_outcome_matrix(outcome, exit_code):
    assert HarnessTestRun(**run_values(outcome=outcome, exit_code=exit_code)).outcome is outcome


def test_test_run_rejects_time_exit_and_artifact_contract_violations():
    for outcome, code in [(HarnessTestRunOutcome.TIMED_OUT, 1), (HarnessTestRunOutcome.CANCELLED, 1), (HarnessTestRunOutcome.UNKNOWN_OUTCOME, 1), (HarnessTestRunOutcome.UNPARSEABLE, None)]:
        with pytest.raises(Exception):
            HarnessTestRun(**run_values(outcome=outcome, exit_code=code))
    for started, finished in [(datetime(2026, 1, 1), datetime(2026, 1, 1)), (datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8))), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))), (datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc))]:
        with pytest.raises(Exception):
            HarnessTestRun(**run_values(started_at=started, finished_at=finished))
    other_task = TaskId(value="723e4567-e89b-42d3-a456-426614174000")
    for ref in [artifact_ref(task=other_task), artifact_ref(schema_id="parsed_result")]:
        with pytest.raises(Exception):
            HarnessTestRun(**run_values(sanitized_output_ref=ref))


def test_test_run_utc_json_uses_z_and_all_fields_are_required():
    run = HarnessTestRun(**run_values())
    dumped = run.model_dump(mode="json")
    assert dumped["started_at"].endswith("Z") and dumped["finished_at"].endswith("Z")
    for field in type(run).model_fields:
        values = run.model_dump()
        values.pop(field)
        with pytest.raises(Exception):
            HarnessTestRun(**values)


@pytest.mark.parametrize(("kind", "previous", "matched", "fingerprint"), [(FeedbackKind.PASSED, None, None, HASH_A), (FeedbackKind.PROGRESS, PREVIOUS_UUID, None, HASH_A), (FeedbackKind.NO_PROGRESS, PREVIOUS_UUID, None, HASH_A), (FeedbackKind.CHANGED, PREVIOUS_UUID, None, HASH_A), (FeedbackKind.REGRESSION, PREVIOUS_UUID, None, HASH_A), (FeedbackKind.LOOP, PREVIOUS_UUID, MATCHED_UUID, HASH_A), (FeedbackKind.ENVIRONMENT_ERROR, None, None, None), (FeedbackKind.UNPARSEABLE, None, None, None)])
def test_feedback_decision_eight_row_matrix(kind, previous, matched, fingerprint):
    decision = FeedbackDecision(kind=kind, current_run_id=RUN_UUID, previous_run_id=previous, matched_history_run_id=matched, state_fingerprint_sha256=fingerprint, sanitized_summary="Stable feedback summary.")
    assert decision.kind is kind


def test_feedback_decision_rejects_cross_field_and_summary_violations():
    valid = dict(kind=FeedbackKind.PROGRESS, current_run_id=RUN_UUID, previous_run_id=PREVIOUS_UUID, matched_history_run_id=None, state_fingerprint_sha256=HASH_A, sanitized_summary="Stable feedback summary.")
    for mutation in [{"previous_run_id": None}, {"previous_run_id": RUN_UUID}, {"matched_history_run_id": MATCHED_UUID}, {"state_fingerprint_sha256": None}, {"state_fingerprint_sha256": "A" * 64}, {"sanitized_summary": ""}, {"sanitized_summary": " leading"}, {"sanitized_summary": "line\nbreak"}, {"sanitized_summary": "tab\there"}]:
        with pytest.raises(Exception):
            FeedbackDecision(**(valid | mutation))


ENUM_VALUES = [
    (TaskStatus, ["created", "preflight", "awaiting_trust", "preflight_failed", "preparing_workspace", "baseline_testing", "cannot_reproduce", "deciding", "validating_action", "preparing_patch", "policy_check", "awaiting_approval", "resume_validation", "revalidating_patch", "applying_patch", "compensation_rollback", "executing_non_patch", "testing", "succeeded", "regression_rollback", "recovery_testing", "paused_for_human", "stopped", "cancelled"]),
    (ActionStatus, ["received", "validated", "awaiting_approval", "ready", "executing", "succeeded", "failed", "rejected", "interrupted", "unknown_outcome"]),
    (PolicyOutcome, ["allow", "deny", "require_approval"]),
    (ApprovalStatus, ["pending", "approved", "consumed", "executed", "denied", "cancelled", "expired"]),
    (ToolErrorCode, ["invalid_request", "not_found", "safety_violation", "unsupported", "conflict", "timeout", "resource_limit", "environment_error", "execution_failed", "unknown_outcome"]),
    (HarnessTestPhase, ["baseline", "focused", "post_patch", "recovery", "resume_validation", "requested_full"]),
    (HarnessTestRunOutcome, ["passed", "failed", "timed_out", "resource_limit", "environment_error", "unparseable", "cancelled", "unknown_outcome", "workspace_drift"]),
    (FeedbackKind, ["passed", "progress", "no_progress", "changed", "regression", "loop", "environment_error", "unparseable"]),
]


@pytest.mark.parametrize(("enum_type", "expected"), ENUM_VALUES)
def test_closed_enums_have_exact_values_no_aliases_and_strict_input(enum_type, expected):
    assert [member.value for member in enum_type] == expected
    assert len(enum_type.__members__) == len(expected)
    assert unique(enum_type) is enum_type
    for member in enum_type:
        assert member.name == member.name.upper()
        assert enum_type(member.value) is member
        with pytest.raises(ValueError):
            enum_type(member.value.upper())
        with pytest.raises(ValueError):
            enum_type(" " + member.value)
