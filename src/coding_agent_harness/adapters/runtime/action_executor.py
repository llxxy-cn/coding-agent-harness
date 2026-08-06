from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from coding_agent_harness.adapters.filesystem.local_filesystem import LocalFileSystem
from coding_agent_harness.adapters.git.readonly import ReadonlyGitAdapter
from coding_agent_harness.adapters.process.diagnostic import DiagnosticRunner
from coding_agent_harness.adapters.process.pytest_runner import PytestTestRunner, TestRequest
from coding_agent_harness.core.harness import ActionExecution
from coding_agent_harness.domain.actions import (
    ApplyPatchAction,
    GitDiffAction,
    GitStatusAction,
    ListFilesAction,
    ReadFileAction,
    RunDiagnosticAction,
    RunTestsAction,
    SearchCodeAction,
)
from coding_agent_harness.domain.enums import TestPhase
from coding_agent_harness.domain.models import FrozenCommand, TaskId
from coding_agent_harness.feedback.pytest_parser import parse_pytest
from coding_agent_harness.patching.applier import apply as apply_patch
from coding_agent_harness.patching.models import PatchSnapshot
from coding_agent_harness.patching.parser import prepare


class _ParsedMarker(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exit_code: StrictInt
    summary: StrictStr


def workspace_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8", errors="strict")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


class WorkspacePatchPreparer:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=True)

    def prepare(self, action: ApplyPatchAction):
        return prepare(action.diff, PatchSnapshot.from_root(self.root))


@dataclass(frozen=True)
class PatchSafetyFacts:
    path_escape: bool
    symlink: bool
    binary: bool
    shell: bool
    capability_missing: bool
    demo_escape: bool


class WorkspacePatchSafetyResolver:
    def __init__(self, root: str | Path, capabilities) -> None:
        self.root = Path(root).resolve(strict=True)
        self.capabilities = capabilities

    def resolve(self, prepared) -> PatchSafetyFacts:
        root = self.root
        path_escape = False
        symlink = False
        binary = False
        for plan in prepared.files:
            candidate = (root / plan.path).resolve()
            path_escape = path_escape or (candidate != root and root not in candidate.parents)
            symlink = symlink or (root / plan.path).is_symlink()
            binary = binary or any(b"\x00" in value[:8192] for value in (plan.pre_image, plan.post_image) if value is not None)
        return PatchSafetyFacts(
            path_escape=path_escape,
            symlink=symlink,
            binary=binary,
            shell=False,
            capability_missing=self.capabilities.mode != "real",
            demo_escape=self.capabilities.mode == "demo",
        )


class CoreTestRunner:
    def __init__(self, *, runner: PytestTestRunner, task_id: TaskId, root: Path, base_commit: str, config, environment: dict[str, str] | None = None) -> None:
        self.runner = runner
        self.task_id = task_id
        self.root = root
        self.base_commit = base_commit
        self.config = config
        self.environment = dict(environment or os.environ)

    def run(self) -> ActionExecution:
        return self._run(TestPhase.POST_PATCH, FrozenCommand(argv=list(self.config.tests.default_command)))

    def run_action(self, action: RunTestsAction) -> ActionExecution:
        phase = TestPhase.FOCUSED if action.scope == "focused" else TestPhase.REQUESTED_FULL
        argv = self.config.tests.default_command + action.targets
        return self._run(phase, FrozenCommand(argv=list(argv)))

    def _run(self, phase: TestPhase, command: FrozenCommand) -> ActionExecution:
        execution = self.runner.run(TestRequest(
            task_id=self.task_id,
            phase=phase,
            command=command,
            base_commit=self.base_commit,
            config_sha256=self.config.sha256,
            worktree=self.root,
            environment=self.environment,
            timeout_seconds=self.config.tests.timeout_seconds,
        ))
        parsed = parse_pytest(execution.raw_output, execution)
        return ActionExecution(
            safe_summary=parsed.summary,
            source_revision=workspace_sha256(self.root),
            test_run=execution.test_run,
            parsed_result=parsed,
            unknown_outcome=execution.test_run.outcome.value == "unknown_outcome",
        )


def parsed_marker(raw, exit_code: int):
    text = (raw.stdout + raw.stderr).decode("utf-8", errors="replace")
    if not text.strip():
        return None
    return _ParsedMarker(exit_code=exit_code, summary="pytest output parsed")


class ProductionActionExecutor:
    def __init__(self, *, root: Path, base_commit: str, filesystem, git, diagnostics, patch_applier, test_runner) -> None:
        self.root = root
        self.base_commit = base_commit
        self.filesystem = filesystem
        self.git = git
        self.diagnostics = diagnostics
        self.patch_applier = patch_applier
        self.test_runner = test_runner

    @classmethod
    def for_workspace(cls, *, root, base_commit, capabilities, git_launcher, diagnostic_launcher, patch_applier=apply_patch, test_runner=None):
        resolved = Path(root).resolve(strict=True)
        return cls(
            root=resolved,
            base_commit=base_commit,
            filesystem=LocalFileSystem(resolved),
            git=ReadonlyGitAdapter(resolved, base_commit, git_launcher),
            diagnostics=DiagnosticRunner(resolved, capabilities, diagnostic_launcher),
            patch_applier=patch_applier,
            test_runner=test_runner,
        )

    def execute(self, action) -> ActionExecution:
        if isinstance(action, (ListFilesAction, ReadFileAction, SearchCodeAction)):
            result = self.filesystem.execute(action)
        elif isinstance(action, GitStatusAction):
            result = self.git.status()
        elif isinstance(action, GitDiffAction):
            result = self.git.diff()
        elif isinstance(action, RunDiagnosticAction):
            result = self.diagnostics.run(action)
        elif isinstance(action, RunTestsAction) and self.test_runner is not None:
            return self.test_runner.run_action(action)
        else:
            return ActionExecution(safe_summary="action is not supported", source_revision=self._revision())
        if not result.ok:
            return ActionExecution(safe_summary=result.sanitized_message or "tool execution failed", source_revision=self._revision())
        summary = json.dumps(result.payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return ActionExecution(safe_summary=summary, source_revision=self._revision())

    def execute_patch(self, action: ApplyPatchAction, prepared) -> ActionExecution:
        result = self.patch_applier(prepared, True, self.root)
        if getattr(result, "ok", False):
            return ActionExecution(safe_summary="patch applied", source_revision=self._revision())
        unknown = getattr(result, "error_code", "") == "unknown_outcome"
        return ActionExecution(safe_summary="patch application failed", source_revision=self._revision(), unknown_outcome=unknown)

    def _revision(self) -> str:
        return workspace_sha256(self.root)
