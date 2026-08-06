"""Deterministic contract fakes for Task 3 ports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar
from uuid import UUID

from coding_agent_harness.domain.enums import ActionStatus, ApprovalStatus, TaskStatus
from coding_agent_harness.domain.models import ArtifactRef, PayloadT, TaskId, ToolResult, ValidatedAction


ContextT = TypeVar("ContextT")
SnapshotT = TypeVar("SnapshotT")
WorkspaceRequestT = TypeVar("WorkspaceRequestT")
WorkspaceResultT = TypeVar("WorkspaceResultT")
FileRequestT = TypeVar("FileRequestT", bound=ValidatedAction)
TestRequestT = TypeVar("TestRequestT")
TestExecutionT = TypeVar("TestExecutionT")


@dataclass
class FakeLLMClient(Generic[ContextT]):
    response: str | dict[str, object]
    calls: list[ContextT] = field(default_factory=list)

    def generate(self, context: ContextT) -> str | dict[str, object]:
        self.calls.append(context)
        return self.response


@dataclass
class FakeStateStore(Generic[SnapshotT]):
    snapshot: SnapshotT | None = None
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def load_snapshot(self, task_id: TaskId) -> SnapshotT | None:
        self.calls.append(("load_snapshot", task_id))
        return self.snapshot

    def compare_and_set_task_status(self, task_id: TaskId, expected: TaskStatus, target: TaskStatus) -> bool:
        self.calls.append(("compare_and_set_task_status", task_id, expected, target))
        return True

    def compare_and_set_action_status(self, task_id: TaskId, action_id: UUID, expected: ActionStatus, target: ActionStatus) -> bool:
        self.calls.append(("compare_and_set_action_status", task_id, action_id, expected, target))
        return True

    def log_intent(self, task_id: TaskId, action_id: UUID, action: ValidatedAction) -> None:
        self.calls.append(("log_intent", task_id, action_id, action))

    def record_approval_decision(self, task_id: TaskId, action_id: UUID, decision: ApprovalStatus) -> None:
        self.calls.append(("record_approval_decision", task_id, action_id, decision))

    def consume_approval(self, task_id: TaskId, action_id: UUID, target_status: ActionStatus) -> bool:
        self.calls.append(("consume_approval", task_id, action_id, target_status))
        return True


@dataclass
class FakeWorkspacePort(Generic[WorkspaceRequestT, WorkspaceResultT]):
    result: WorkspaceResultT
    calls: list[WorkspaceRequestT] = field(default_factory=list)

    def execute(self, request: WorkspaceRequestT) -> WorkspaceResultT:
        self.calls.append(request)
        return self.result


@dataclass
class FakeFileSystemPort(Generic[FileRequestT, PayloadT]):
    result: ToolResult[PayloadT]
    calls: list[FileRequestT] = field(default_factory=list)

    def execute(self, action: FileRequestT) -> ToolResult[PayloadT]:
        self.calls.append(action)
        return self.result


@dataclass
class FakeTestRunner(Generic[TestRequestT, TestExecutionT]):
    result: TestExecutionT
    calls: list[TestRequestT] = field(default_factory=list)

    def run(self, request: TestRequestT) -> TestExecutionT:
        self.calls.append(request)
        return self.result


@dataclass
class FakeCredentialStore:
    present: bool = False
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def set(self, value: str) -> None:
        self.calls.append(("set",))
        self.present = True

    def status(self) -> bool:
        self.calls.append(("status",))
        return self.present

    def update(self, value: str) -> None:
        self.calls.append(("update",))
        self.present = True

    def clear(self) -> None:
        self.calls.append(("clear",))
        self.present = False


@dataclass
class FakeArtifactStore:
    artifact_ref: ArtifactRef
    content: bytes
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def put(self, task_id: TaskId, schema_id: str, schema_version: int, media_type: str, content: bytes) -> ArtifactRef:
        self.calls.append(("put", task_id, schema_id, schema_version, media_type, content))
        return self.artifact_ref

    def load(self, artifact_ref: ArtifactRef) -> bytes:
        self.calls.append(("load", artifact_ref))
        return self.content
