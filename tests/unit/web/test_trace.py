"""Contract tests for typed DemoTraceEvent events and ExecutionTraceView (Web UI v0.2.0 Task A0)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from coding_agent_harness.domain.enums import PolicyOutcome, TaskStatus, TestRunOutcome as DomainTestRunOutcome
from coding_agent_harness.security.policy import PolicyReasonCode
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    DemoEventType,
    DemoFeedbackCode,
    DemoTraceEvent,
    DemoWorkerResult,
    EventCountRule,
    ExecutionTraceView,
    FeedbackProducedEvent,
    PolicyDecisionEvent,
    ScenarioTraceContract,
    TerminalStatusEvent,
    TestCompletedEvent,
)


def action(seq: int = 0, kind: DemoActionKind = DemoActionKind.LIST_FILES) -> ActionSelectedEvent:
    return ActionSelectedEvent(action_kind=kind, sequence=seq)


def policy(seq: int = 0) -> PolicyDecisionEvent:
    return PolicyDecisionEvent(
        decision=PolicyOutcome.ALLOW,
        reason_code=PolicyReasonCode.ALLOWED,
        sequence=seq,
    )


def make_test_completed(seq: int = 0) -> TestCompletedEvent:
    return TestCompletedEvent(outcome=DomainTestRunOutcome.PASSED, sequence=seq)


def feedback(seq: int = 0, code: DemoFeedbackCode = DemoFeedbackCode.PASSED) -> FeedbackProducedEvent:
    return FeedbackProducedEvent(feedback_code=code, sequence=seq)


def terminal(seq: int = 1, status: TaskStatus = TaskStatus.SUCCEEDED) -> TerminalStatusEvent:
    return TerminalStatusEvent(task_status=status, sequence=seq)


def basic_contract() -> ScenarioTraceContract:
    return ScenarioTraceContract(
        count_rules=(
            EventCountRule(event_type=DemoEventType.ACTION_SELECTED, min_count=1, max_count=10),
            EventCountRule(event_type=DemoEventType.TERMINAL_STATUS, min_count=1, max_count=1),
        ),
        allowed_transitions=(
            (DemoEventType.ACTION_SELECTED, DemoEventType.TERMINAL_STATUS),
        ),
        required_terminal_status=TaskStatus.SUCCEEDED,
        max_events=10,
    )


def test_frozen_models_reject_mutation() -> None:
    event = action(seq=0)
    with pytest.raises((ValidationError, TypeError)):
        event.sequence = 99  # type: ignore[misc]


def test_demo_worker_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DemoWorkerResult(
            schema_version=1,
            scenario_id="scn-1",
            events=(action(0), terminal(1)),
            terminal_code=TaskStatus.SUCCEEDED,
            rogue_field="nope",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        (
            {"event_type": "action_selected", "action_kind": "list_files", "sequence": 0},
            ActionSelectedEvent,
        ),
        (
            {"event_type": "policy_decision", "decision": "allow", "reason_code": "allowed", "sequence": 0},
            PolicyDecisionEvent,
        ),
        (
            {"event_type": "test_completed", "outcome": "passed", "sequence": 0},
            TestCompletedEvent,
        ),
        (
            {"event_type": "feedback_produced", "feedback_code": "passed", "sequence": 0},
            FeedbackProducedEvent,
        ),
        (
            {"event_type": "terminal_status", "task_status": "succeeded", "sequence": 0},
            TerminalStatusEvent,
        ),
    ],
)
def test_discriminated_union_dispatches_by_event_type(payload: dict[str, object], expected_type: type[DemoTraceEvent]) -> None:
    adapter = TypeAdapter(DemoTraceEvent)
    event = adapter.validate_python(payload)
    assert type(event) is expected_type


def test_discriminated_union_rejects_unknown_event_type() -> None:
    adapter = TypeAdapter(DemoTraceEvent)
    with pytest.raises(ValidationError):
        adapter.validate_python({"event_type": "not_a_real_type", "sequence": 0})


def test_demo_feedback_code_initial_failure_exists() -> None:
    assert DemoFeedbackCode.INITIAL_FAILURE.value == "initial_failure"


def test_from_events_rejects_missing_terminal() -> None:
    with pytest.raises(ValueError):
        ExecutionTraceView.from_events((action(0),))


def test_from_events_rejects_terminal_not_at_end() -> None:
    with pytest.raises(ValueError):
        ExecutionTraceView.from_events((terminal(0), action(1)))


def test_from_events_rejects_multiple_terminals() -> None:
    with pytest.raises(ValueError):
        ExecutionTraceView.from_events((terminal(0), terminal(1)))


def test_from_events_succeeds_with_valid_events() -> None:
    view = ExecutionTraceView.from_events((action(0), terminal(1)))
    assert view.terminal_status == TaskStatus.SUCCEEDED
    assert len(view.events) == 2
    assert isinstance(view.events[0], ActionSelectedEvent)
    assert isinstance(view.events[1], TerminalStatusEvent)


def test_direct_construction_rejects_mismatched_terminal_status() -> None:
    events = (action(0), terminal(1, status=TaskStatus.SUCCEEDED))
    with pytest.raises(ValueError):
        ExecutionTraceView(events=events, terminal_status=TaskStatus.STOPPED)


def test_direct_construction_rejects_non_terminal_last_event() -> None:
    events = (action(0), action(1))
    with pytest.raises(ValueError):
        ExecutionTraceView(events=events, terminal_status=TaskStatus.SUCCEEDED)


def test_direct_construction_succeeds_when_consistent() -> None:
    events = (action(0), terminal(1, status=TaskStatus.SUCCEEDED))
    view = ExecutionTraceView(events=events, terminal_status=TaskStatus.SUCCEEDED)
    assert view.terminal_status == TaskStatus.SUCCEEDED
    assert len(view.events) == 2


def test_validate_rejects_bad_transition() -> None:
    contract = basic_contract()
    events = (action(0), action(1), terminal(2))
    with pytest.raises(ValueError):
        contract.validate(events)


def test_validate_rejects_bad_counts() -> None:
    contract = ScenarioTraceContract(
        count_rules=(
            EventCountRule(event_type=DemoEventType.ACTION_SELECTED, min_count=2, max_count=10),
            EventCountRule(event_type=DemoEventType.TERMINAL_STATUS, min_count=1, max_count=1),
        ),
        allowed_transitions=((DemoEventType.ACTION_SELECTED, DemoEventType.TERMINAL_STATUS),),
        required_terminal_status=TaskStatus.SUCCEEDED,
        max_events=10,
    )
    events = (action(0), terminal(1))
    with pytest.raises(ValueError):
        contract.validate(events)


def test_validate_rejects_bad_sequence() -> None:
    contract = basic_contract()
    events = (action(0), terminal(5))
    with pytest.raises(ValueError):
        contract.validate(events)


def test_validate_rejects_wrong_terminal_status() -> None:
    contract = basic_contract()
    events = (action(0), terminal(1, status=TaskStatus.STOPPED))
    with pytest.raises(ValueError):
        contract.validate(events)


def test_validate_rejects_too_many_events() -> None:
    contract = ScenarioTraceContract(
        count_rules=(
            EventCountRule(event_type=DemoEventType.ACTION_SELECTED, min_count=1, max_count=10),
            EventCountRule(event_type=DemoEventType.TERMINAL_STATUS, min_count=1, max_count=1),
        ),
        allowed_transitions=((DemoEventType.ACTION_SELECTED, DemoEventType.TERMINAL_STATUS),),
        required_terminal_status=TaskStatus.SUCCEEDED,
        max_events=1,
    )
    events = (action(0), terminal(1))
    with pytest.raises(ValueError):
        contract.validate(events)


def test_validate_succeeds_with_valid_events() -> None:
    contract = basic_contract()
    events = (action(0), terminal(1))
    contract.validate(events)


def test_display_text_returns_fixed_strings() -> None:
    view = ExecutionTraceView.from_events((action(0), terminal(1)))
    assert view.display_text(action(0)) == "action selected: list_files"
    assert view.display_text(policy(0)) == "policy decision: allow (allowed)"
    assert view.display_text(make_test_completed(0)) == "test completed: passed"
    assert view.display_text(feedback(0)) == "feedback produced: passed"
    assert view.display_text(terminal(1)) == "terminal status: succeeded"


def test_display_text_uses_all_action_kinds() -> None:
    view = ExecutionTraceView.from_events((action(0), terminal(1)))
    expected = {
        DemoActionKind.LIST_FILES: "action selected: list_files",
        DemoActionKind.READ_FILE: "action selected: read_file",
        DemoActionKind.SEARCH_CODE: "action selected: search_code",
        DemoActionKind.APPLY_PATCH: "action selected: apply_patch",
        DemoActionKind.RUN_TESTS: "action selected: run_tests",
        DemoActionKind.GIT_DIFF: "action selected: git_diff",
        DemoActionKind.GIT_STATUS: "action selected: git_status",
        DemoActionKind.RUN_DIAGNOSTIC: "action selected: run_diagnostic",
        DemoActionKind.REQUEST_HUMAN: "action selected: request_human",
    }
    for kind, text in expected.items():
        assert view.display_text(action(0, kind=kind)) == text


def test_demo_worker_result_accepts_valid_data() -> None:
    result = DemoWorkerResult(
        schema_version=1,
        scenario_id="scn-001",
        events=(action(0), terminal(1)),
        terminal_code=TaskStatus.SUCCEEDED,
    )
    assert result.schema_version == 1
    assert result.scenario_id == "scn-001"
    assert len(result.events) == 2
    assert result.terminal_code == TaskStatus.SUCCEEDED
    assert isinstance(result.events[0], ActionSelectedEvent)
    assert isinstance(result.events[1], TerminalStatusEvent)


def test_event_count_rule_max_ge_min() -> None:
    with pytest.raises(ValidationError):
        EventCountRule(event_type=DemoEventType.ACTION_SELECTED, min_count=5, max_count=2)
    valid = EventCountRule(event_type=DemoEventType.ACTION_SELECTED, min_count=1, max_count=1)
    assert valid.min_count == 1
    assert valid.max_count == 1
