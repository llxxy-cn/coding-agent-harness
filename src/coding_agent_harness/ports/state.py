"""Persistence port for state, intents, and approval lifecycle records."""

from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

from coding_agent_harness.domain.enums import ActionStatus, ApprovalStatus, TaskStatus
from coding_agent_harness.domain.models import TaskId, ValidatedAction


SnapshotT = TypeVar("SnapshotT")


@runtime_checkable
class StateStore(Protocol[SnapshotT]):
    def load_snapshot(self, task_id: TaskId) -> SnapshotT | None: ...

    def compare_and_set_task_status(self, task_id: TaskId, expected: TaskStatus, target: TaskStatus) -> bool: ...

    def compare_and_set_action_status(self, task_id: TaskId, action_id: UUID, expected: ActionStatus, target: ActionStatus) -> bool: ...

    def log_intent(self, task_id: TaskId, action_id: UUID, action: ValidatedAction) -> None: ...

    def record_approval_decision(self, task_id: TaskId, action_id: UUID, decision: ApprovalStatus) -> None: ...

    def consume_approval(self, task_id: TaskId, action_id: UUID, target_status: ActionStatus) -> bool: ...
