from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class SpyLauncher:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv, cwd, shell, env):
        self.calls.append((argv, cwd, shell, env))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(returncode=response[0], stdout=response[1], stderr=response[2])


def test_non_git_repository_is_rejected_without_continuation(tmp_path: Path) -> None:
    from coding_agent_harness.application.preflight import PreflightError, RepositoryPreflight

    launcher = SpyLauncher([(128, "", "not a git repository")])
    continued = []

    with pytest.raises(PreflightError, match="repository preflight failed"):
        RepositoryPreflight(launcher=launcher).inspect(tmp_path, on_verified=lambda facts: continued.append(facts))

    assert continued == []
    assert launcher.calls[0][0] == ("git", "rev-parse", "--show-toplevel")
    assert launcher.calls[0][1] == tmp_path.resolve()
    assert launcher.calls[0][2] is False


def test_dirty_repository_is_rejected_before_base_commit_is_read(tmp_path: Path) -> None:
    from coding_agent_harness.application.preflight import PreflightError, RepositoryPreflight

    launcher = SpyLauncher([(0, str(tmp_path.resolve()), ""), (0, " M source.py", "")])

    with pytest.raises(PreflightError, match="repository has uncommitted changes"):
        RepositoryPreflight(launcher=launcher).inspect(tmp_path)

    assert [call[0] for call in launcher.calls] == [
        ("git", "rev-parse", "--show-toplevel"),
        ("git", "status", "--porcelain"),
    ]
    assert all(call[2] is False for call in launcher.calls)
