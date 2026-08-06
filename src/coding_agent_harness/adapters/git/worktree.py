from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator

from coding_agent_harness.application.preflight import PreflightError, RepositoryPreflight
from coding_agent_harness.config.models import FrozenConfig
from coding_agent_harness.domain.models import TaskId
from coding_agent_harness.security.canonical import canonical_sha256


_MAX_GIT_OUTPUT = 65_536
_SAFE_ENV = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "LANG", "LC_ALL"})


class WorkspaceError(RuntimeError):
    pass


class VerifiedWorkspace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: TaskId
    root: Path
    repository_root: Path
    repository_identity_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    base_commit: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")
    config_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    capability_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    isolated: StrictBool

    @field_validator("root", "repository_root")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        return value.resolve()


class GitWorktreeAdapter:
    verified = True

    def __init__(self, *, data_root: str | Path, launcher: Callable) -> None:
        self.data_root = Path(data_root).resolve()
        self.worktrees_root = self.data_root / "worktrees"
        self.launcher = launcher
        self.preflight = RepositoryPreflight(launcher=launcher)

    def prepare(self, *, repository: str | Path, task_id: TaskId, frozen_config: FrozenConfig, trust_repo: bool) -> VerifiedWorkspace:
        if trust_repo is not True:
            raise WorkspaceError("repository trust is required")
        try:
            facts = self.preflight.inspect(repository)
        except PreflightError as exc:
            raise WorkspaceError(str(exc)) from None
        root = (self.worktrees_root / str(task_id.value)).resolve()
        if self.worktrees_root.resolve() not in root.parents or root == facts.root or facts.root in root.parents:
            raise WorkspaceError("workspace path is invalid")
        argv = ("git", "worktree", "add", "--detach", str(root), facts.base_commit)
        self._run(argv, facts.root)
        if not root.exists() or not root.is_dir() or root.is_symlink():
            raise WorkspaceError("workspace creation failed")
        return VerifiedWorkspace(
            task_id=task_id,
            root=root,
            repository_root=facts.root,
            repository_identity_sha256=facts.identity_sha256,
            base_commit=facts.base_commit,
            config_sha256=frozen_config.sha256,
            capability_sha256=canonical_sha256(frozen_config.capabilities.model_dump(mode="json")),
            isolated=True,
        )

    def validate_resume(self, *, workspace: VerifiedWorkspace, frozen_config: FrozenConfig) -> VerifiedWorkspace:
        root = workspace.root.resolve()
        if not root.exists() or not root.is_dir() or root.is_symlink() or self.worktrees_root.resolve() not in root.parents:
            raise WorkspaceError("workspace validation failed")
        if workspace.config_sha256 != frozen_config.sha256 or workspace.capability_sha256 != canonical_sha256(frozen_config.capabilities.model_dump(mode="json")):
            raise WorkspaceError("workspace validation failed")
        try:
            facts = self.preflight.inspect(workspace.repository_root)
        except PreflightError:
            raise WorkspaceError("workspace validation failed") from None
        if facts.identity_sha256 != workspace.repository_identity_sha256 or facts.base_commit != workspace.base_commit:
            raise WorkspaceError("workspace validation failed")
        return workspace

    def _run(self, argv: tuple[str, ...], cwd: Path) -> None:
        env = {key: value for key, value in os.environ.items() if key.upper() in _SAFE_ENV}
        try:
            result = self.launcher(argv, cwd, False, env)
            stdout = getattr(result, "stdout", "") or ""
            stderr = getattr(result, "stderr", "") or ""
            if getattr(result, "returncode", 1) != 0 or not isinstance(stdout, str) or not isinstance(stderr, str):
                raise WorkspaceError("workspace creation failed")
            if len(stdout.encode("utf-8", errors="strict")) > _MAX_GIT_OUTPUT or len(stderr.encode("utf-8", errors="strict")) > _MAX_GIT_OUTPUT:
                raise WorkspaceError("workspace creation failed")
        except WorkspaceError:
            raise
        except Exception:
            raise WorkspaceError("workspace creation failed") from None
