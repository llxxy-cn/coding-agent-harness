"""Runtime and signature contracts for the seven Task 3 ports."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from coding_agent_harness.domain.actions import GitStatusAction
from coding_agent_harness.domain.enums import ActionStatus, ApprovalStatus, TaskStatus
from coding_agent_harness.domain.models import ArtifactRef, TaskId, ToolPayload, ToolResult
from coding_agent_harness.ports.artifacts import ArtifactStore
from coding_agent_harness.ports.credentials import CredentialStore
from coding_agent_harness.ports.filesystem import FileSystemPort
from coding_agent_harness.ports.llm import LLMClient
from coding_agent_harness.ports.state import StateStore
from coding_agent_harness.ports.testing import TestRunner as RunnerPort
from coding_agent_harness.ports.workspace import WorkspacePort

from fakes import (
    FakeArtifactStore,
    FakeCredentialStore,
    FakeFileSystemPort,
    FakeLLMClient,
    FakeStateStore,
    FakeTestRunner,
    FakeWorkspacePort,
)


ROOT = Path(__file__).resolve().parents[2]
TASK_ID = TaskId(value="123e4567-e89b-42d3-a456-426614174000")
ACTION_ID = UUID("323e4567-e89b-42d3-a456-426614174000")


class ContractPayload(ToolPayload):
    value: str


def artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="223e4567-e89b-42d3-a456-426614174000",
        task_id=TASK_ID,
        schema_id="contract_payload",
        schema_version=1,
        media_type="application/json",
        byte_length=2,
        sha256="a" * 64,
    )


def test_named_fakes_satisfy_runtime_protocols_and_record_calls():
    action = GitStatusAction(type="git_status")
    tool_result = ToolResult[ContractPayload](ok=True, payload=ContractPayload(value="ok"), error_code=None, sanitized_message=None)
    llm = FakeLLMClient(response='{"type":"git_status"}')
    state = FakeStateStore(snapshot="snapshot")
    workspace = FakeWorkspacePort(result="workspace")
    filesystem = FakeFileSystemPort(result=tool_result)
    runner = FakeTestRunner(result="execution")
    credentials = FakeCredentialStore()
    artifacts = FakeArtifactStore(artifact_ref=artifact_ref(), content=b"{}")

    assert isinstance(llm, LLMClient)
    assert isinstance(state, StateStore)
    assert isinstance(workspace, WorkspacePort)
    assert isinstance(filesystem, FileSystemPort)
    assert isinstance(runner, RunnerPort)
    assert isinstance(credentials, CredentialStore)
    assert isinstance(artifacts, ArtifactStore)

    assert llm.generate("context") == '{"type":"git_status"}'
    assert state.load_snapshot(TASK_ID) == "snapshot"
    assert state.compare_and_set_task_status(TASK_ID, TaskStatus.CREATED, TaskStatus.PREFLIGHT)
    assert state.compare_and_set_action_status(TASK_ID, ACTION_ID, ActionStatus.RECEIVED, ActionStatus.VALIDATED)
    state.log_intent(TASK_ID, ACTION_ID, action)
    state.record_approval_decision(TASK_ID, ACTION_ID, ApprovalStatus.APPROVED)
    assert state.consume_approval(TASK_ID, ACTION_ID, ActionStatus.EXECUTING)
    assert workspace.execute("prepare") == "workspace"
    assert filesystem.execute(action) is tool_result
    assert runner.run("request") == "execution"
    credentials.set("secret")
    assert credentials.status() is True
    credentials.update("replacement")
    credentials.clear()
    assert credentials.status() is False
    assert artifacts.put(TASK_ID, "contract_payload", 1, "application/json", b"{}") == artifacts.artifact_ref
    assert artifacts.load(artifacts.artifact_ref) == b"{}"

    assert llm.calls == ["context"]
    assert workspace.calls == ["prepare"]
    assert filesystem.calls == [action]
    assert runner.calls == ["request"]
    assert all("secret" not in call and "replacement" not in call for call in credentials.calls)


def test_runtime_protocol_check_fails_when_required_method_is_absent():
    class MissingGenerate:
        pass

    class MissingConsumeApproval:
        def load_snapshot(self, task_id):
            return None

        def compare_and_set_task_status(self, task_id, expected, target):
            return True

        def compare_and_set_action_status(self, task_id, action_id, expected, target):
            return True

        def log_intent(self, task_id, action_id, action):
            return None

        def record_approval_decision(self, task_id, action_id, decision):
            return None

    assert not isinstance(MissingGenerate(), LLMClient)
    assert not isinstance(MissingConsumeApproval(), StateStore)


def test_protocol_signatures_are_narrow_and_domain_typed():
    assert list(inspect.signature(LLMClient.generate).parameters) == ["self", "context"]
    assert list(inspect.signature(RunnerPort.run).parameters) == ["self", "request"]
    assert set(StateStore.__dict__) >= {
        "load_snapshot",
        "compare_and_set_task_status",
        "compare_and_set_action_status",
        "log_intent",
        "record_approval_decision",
        "consume_approval",
    }
    state_source = inspect.getsource(StateStore)
    assert "TaskStatus" in state_source
    assert "ActionStatus" in state_source
    assert "evaluate" not in state_source
    assert "Policy" not in state_source
    filesystem_source = inspect.getsource(FileSystemPort)
    assert "ToolResult[PayloadT]" in filesystem_source
    assert "dict" not in filesystem_source


def test_core_layer_does_not_import_adapters():
    core_root = ROOT / "src" / "coding_agent_harness" / "core"
    if not core_root.exists():
        return
    for path in core_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            assert all("coding_agent_harness.adapters" not in name for name in imported), path
