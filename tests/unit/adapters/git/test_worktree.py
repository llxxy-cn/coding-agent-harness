import os
from types import SimpleNamespace

from coding_agent_harness.adapters.git.worktree import GitWorktreeAdapter


def test_runtime_git_and_preflight_use_the_same_hardened_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "coding_agent_harness.adapters.git.worktree.os.environ",
        {"PATH": "safe-path", "GIT_DIR": "hostile-dir", "GIT_ASKPASS": "hostile"},
    )
    calls = []

    def launcher(argv, cwd, shell, env):
        calls.append((argv, cwd, shell, env))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    adapter = GitWorktreeAdapter(data_root=tmp_path / "data", launcher=launcher)

    adapter._run(("git", "worktree", "add"), tmp_path)
    adapter.preflight._run(("git", "status", "--porcelain"), tmp_path, "failed")

    expected = {
        "PATH": "safe-path",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": os.devnull,
        "SSH_ASKPASS": os.devnull,
    }
    assert [call[3] for call in calls] == [expected, expected]
