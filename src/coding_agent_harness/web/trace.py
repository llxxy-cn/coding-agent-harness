"""Typed DemoTraceEvent events, contracts, and ExecutionTraceView for the Web UI trace layer."""

from __future__ import annotations

from enum import Enum, unique
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from coding_agent_harness.domain.enums import PolicyOutcome, TaskStatus, TestRunOutcome
from coding_agent_harness.security.policy import PolicyReasonCode


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


@unique
class DemoEventType(str, Enum):
    ACTION_SELECTED = "action_selected"
    POLICY_DECISION = "policy_decision"
    TEST_COMPLETED = "test_completed"
    FEEDBACK_PRODUCED = "feedback_produced"
    TERMINAL_STATUS = "terminal_status"


@unique
class DemoActionKind(str, Enum):
    LIST_FILES = "list_files"
    READ_FILE = "read_file"
    SEARCH_CODE = "search_code"
    APPLY_PATCH = "apply_patch"
    RUN_TESTS = "run_tests"
    GIT_DIFF = "git_diff"
    GIT_STATUS = "git_status"
    RUN_DIAGNOSTIC = "run_diagnostic"
    REQUEST_HUMAN = "request_human"


@unique
class DemoFeedbackCode(str, Enum):
    INITIAL_FAILURE = "initial_failure"
    PASSED = "passed"
    CHANGED = "changed"
    PROGRESS = "progress"
    NO_PROGRESS = "no_progress"
    REGRESSION = "regression"
    LOOP = "loop"
    ENVIRONMENT_ERROR = "environment_error"
    UNPARSEABLE = "unparseable"


class ActionSelectedEvent(_FrozenModel):
    event_type: Literal[DemoEventType.ACTION_SELECTED] = DemoEventType.ACTION_SELECTED
    action_kind: DemoActionKind
    sequence: StrictInt = Field(ge=0)


class PolicyDecisionEvent(_FrozenModel):
    event_type: Literal[DemoEventType.POLICY_DECISION] = DemoEventType.POLICY_DECISION
    decision: PolicyOutcome
    reason_code: PolicyReasonCode
    sequence: StrictInt = Field(ge=0)


class TestCompletedEvent(_FrozenModel):
    __test__: ClassVar[bool] = False

    event_type: Literal[DemoEventType.TEST_COMPLETED] = DemoEventType.TEST_COMPLETED
    outcome: TestRunOutcome
    sequence: StrictInt = Field(ge=0)


class FeedbackProducedEvent(_FrozenModel):
    event_type: Literal[DemoEventType.FEEDBACK_PRODUCED] = DemoEventType.FEEDBACK_PRODUCED
    feedback_code: DemoFeedbackCode
    sequence: StrictInt = Field(ge=0)


class TerminalStatusEvent(_FrozenModel):
    event_type: Literal[DemoEventType.TERMINAL_STATUS] = DemoEventType.TERMINAL_STATUS
    task_status: TaskStatus
    sequence: StrictInt = Field(ge=0)


DemoTraceEvent = Annotated[
    ActionSelectedEvent
    | PolicyDecisionEvent
    | TestCompletedEvent
    | FeedbackProducedEvent
    | TerminalStatusEvent,
    Field(discriminator="event_type"),
]


class DemoWorkerResult(_FrozenModel):
    schema_version: Literal[1]
    scenario_id: StrictStr
    events: tuple[DemoTraceEvent, ...]
    terminal_code: TaskStatus


class EventCountRule(_FrozenModel):
    event_type: DemoEventType
    min_count: StrictInt = Field(ge=0)
    max_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_count_bounds(self) -> EventCountRule:
        if self.max_count < self.min_count:
            raise ValueError("max_count must be >= min_count")
        return self


class ScenarioTraceContract(_FrozenModel):
    count_rules: tuple[EventCountRule, ...]
    allowed_transitions: tuple[tuple[DemoEventType, DemoEventType], ...]
    required_terminal_status: TaskStatus
    max_events: StrictInt = Field(ge=1)

    def validate(self, events: tuple[DemoTraceEvent, ...]) -> None:
        if len(events) > self.max_events:
            raise ValueError("event count exceeds max_events")

        for index, event in enumerate(events):
            if event.sequence != index:
                raise ValueError("event sequence must be continuous starting from 0")

        counts: dict[DemoEventType, int] = {}
        for event in events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        for rule in self.count_rules:
            observed = counts.get(rule.event_type, 0)
            if not (rule.min_count <= observed <= rule.max_count):
                raise ValueError(
                    f"event count for {rule.event_type.value} outside "
                    f"[{rule.min_count}, {rule.max_count}]"
                )

        allowed = set(self.allowed_transitions)
        for previous, current in zip(events, events[1:]):
            if (previous.event_type, current.event_type) not in allowed:
                raise ValueError("transition not allowed")

        terminal_events = [e for e in events if isinstance(e, TerminalStatusEvent)]
        if len(terminal_events) != 1:
            raise ValueError("exactly one terminal status event required")
        terminal_event = terminal_events[0]
        if events[-1] is not terminal_event:
            raise ValueError("terminal status event must be at the end")
        if terminal_event.task_status != self.required_terminal_status:
            raise ValueError("terminal status does not match required_terminal_status")


class ExecutionTraceView(_FrozenModel):
    events: tuple[DemoTraceEvent, ...]
    terminal_status: TaskStatus

    @model_validator(mode="after")
    def validate_terminal_consistency(self) -> ExecutionTraceView:
        if self.events:
            last = self.events[-1]
            if not isinstance(last, TerminalStatusEvent):
                raise ValueError("last event must be a terminal status event")
            if last.task_status != self.terminal_status:
                raise ValueError("terminal_status does not match last event")
        return self

    @classmethod
    def from_events(cls, events: tuple[DemoTraceEvent, ...]) -> ExecutionTraceView:
        terminal_events = [e for e in events if isinstance(e, TerminalStatusEvent)]
        if len(terminal_events) != 1:
            raise ValueError("events must contain exactly one terminal status event")
        terminal_event = terminal_events[0]
        if events[-1] is not terminal_event:
            raise ValueError("terminal status event must be at the end")
        return cls(events=events, terminal_status=terminal_event.task_status)

    def display_text(self, event: DemoTraceEvent) -> str:
        if isinstance(event, ActionSelectedEvent):
            return f"action selected: {event.action_kind.value}"
        if isinstance(event, PolicyDecisionEvent):
            return f"policy decision: {event.decision.value} ({event.reason_code.value})"
        if isinstance(event, TestCompletedEvent):
            return f"test completed: {event.outcome.value}"
        if isinstance(event, FeedbackProducedEvent):
            return f"feedback produced: {event.feedback_code.value}"
        if isinstance(event, TerminalStatusEvent):
            return f"terminal status: {event.task_status.value}"
        raise ValueError(f"unknown event type: {event!r}")
