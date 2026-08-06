from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.domain.models import TaskId


TASK_ID = TaskId(value="123e4567-e89b-42d3-a456-426614174000")
BASE_COMMIT = "a" * 40


def _config():
    return resolve_config(BUILTIN_CONFIG, {"llm": {"model": "gpt-test-model"}}, {}, "real")


class WorktreeLauncher:
    def __init__(self, repository: Path) -> None:
        self.repository = repository.resolve()
        self.calls = []

    def __call__(self, argv, cwd, shell, env):
        self.calls.append((argv, cwd, shell, env))
        if argv == ("git", "rev-parse", "--show-toplevel"):
            return SimpleNamespace(returncode=0, stdout=str(self.repository), stderr="")
        if argv == ("git", "status", "--porcelain"):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv == ("git", "rev-parse", "HEAD"):
            return SimpleNamespace(returncode=0, stdout=BASE_COMMIT, stderr="")
        if argv[:4] == ("git", "worktree", "add", "--detach"):
            Path(argv[4]).mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="prepared", stderr="")
        raise AssertionError(f"unexpected git argv: {argv}")


def test_clean_repository_creates_generated_isolated_verified_worktree(tmp_path: Path, monkeypatch) -> None:
    from coding_agent_harness.adapters.git.worktree import GitWorktreeAdapter, VerifiedWorkspace

    repository = tmp_path / "source"
    repository.mkdir()
    data_root = tmp_path / "data"
    launcher = WorktreeLauncher(repository)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-propagate")
    adapter = GitWorktreeAdapter(data_root=data_root, launcher=launcher)

    workspace = adapter.prepare(repository=repository, task_id=TASK_ID, frozen_config=_config(), trust_repo=True)

    assert isinstance(workspace, VerifiedWorkspace)
    assert workspace.root.parent == (data_root / "worktrees").resolve()
    assert repository.resolve() not in workspace.root.parents
    assert workspace.base_commit == BASE_COMMIT and workspace.isolated is True
    assert launcher.calls[-1][0] == ("git", "worktree", "add", "--detach", str(workspace.root), BASE_COMMIT)
    assert all(call[1] == repository.resolve() and call[2] is False for call in launcher.calls)
    assert all("OPENAI_API_KEY" not in call[3] for call in launcher.calls)
    assert all(not {"fetch", "pull", "clone"}.intersection(call[0]) for call in launcher.calls)


def test_resume_rejects_missing_or_drifted_verified_worktree(tmp_path: Path) -> None:
    from coding_agent_harness.adapters.git.worktree import GitWorktreeAdapter, WorkspaceError

    repository = tmp_path / "source"
    repository.mkdir()
    launcher = WorktreeLauncher(repository)
    adapter = GitWorktreeAdapter(data_root=tmp_path / "data", launcher=launcher)
    workspace = adapter.prepare(repository=repository, task_id=TASK_ID, frozen_config=_config(), trust_repo=True)
    workspace.root.rmdir()

    with pytest.raises(WorkspaceError, match="workspace validation failed"):
        adapter.validate_resume(workspace=workspace, frozen_config=_config())

    assert all("worktree" not in call[0] or call[0][1:3] == ("worktree", "add") for call in launcher.calls)
