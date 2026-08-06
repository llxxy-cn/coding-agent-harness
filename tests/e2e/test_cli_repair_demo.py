from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from typer.testing import CliRunner

from coding_agent_harness.domain.enums import TaskStatus


FIXTURE = Path("tests/fixtures/e2e/repairable_project").resolve()
PATCH = "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n def add(a: int, b: int) -> int:\n-    return a - b\n+    return a + b\n"
ACTIONS = (
    {"type": "read_file", "path": "calculator.py"},
    {"type": "search_code", "path": ".", "query": "return a - b", "case_sensitive": True},
    {"type": "apply_patch", "diff": PATCH},
)


def prepared_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURE, repository)
    git(repository, "init")
    git(repository, "config", "user.email", "demo@example.invalid")
    git(repository, "config", "user.name", "Demo User")
    git(repository, "config", "core.autocrlf", "false")
    git(repository, "add", "--", "calculator.py", "tests/test_calculator.py", "pyproject.toml")
    git(repository, "commit", "-m", "fixture baseline")
    return repository


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("git", *args), cwd=cwd, shell=False, check=True, text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def pytest_run(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (str(Path(".venv/Scripts/python.exe").resolve()), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"),
        cwd=cwd,
        shell=False,
        check=False,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_offline_cli_demo_repairs_only_isolated_worktree_with_real_pytest(tmp_path: Path) -> None:
    from coding_agent_harness.cli.app import build_cli
    from coding_agent_harness.composition import build_demo_runtime

    repository = prepared_repository(tmp_path)
    baseline_head = git(repository, "rev-parse", "HEAD").stdout.strip()
    baseline_status = git(repository, "status", "--porcelain").stdout
    baseline = pytest_run(repository)
    runtime = build_demo_runtime(
        data_root=tmp_path / "data",
        scripted_actions=ACTIONS,
        trusted_python=Path(".venv/Scripts/python.exe").resolve(),
    )
    cli = build_cli(demo_runtime_factory=lambda: runtime, persistent_runtime_factory=lambda: runtime)

    result = CliRunner().invoke(cli, ["run", str(repository), "repair calculator addition", "--demo", "--trust-repo"])

    assert result.exit_code == 0
    assert "status: succeeded" in result.stdout
    assert baseline.returncode != 0 and "1 failed" in baseline.stdout
    task_id = UUID(next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("task_id:")))
    worktree = tmp_path / "data" / "worktrees" / str(task_id)
    repaired = pytest_run(worktree)
    assert repaired.returncode == 0 and "1 passed" in repaired.stdout
    assert (worktree / "calculator.py").read_bytes() == b"def add(a: int, b: int) -> int:\n    return a + b\n"
    assert "return a - b" in (repository / "calculator.py").read_text(encoding="utf-8")
    assert git(repository, "rev-parse", "HEAD").stdout.strip() == baseline_head
    assert git(repository, "status", "--porcelain").stdout == baseline_status
    assert FIXTURE.joinpath("calculator.py").read_bytes() == b"def add(a: int, b: int) -> int:\n    return a - b\n"


def test_new_demo_runtime_reads_persisted_success_status(tmp_path: Path) -> None:
    from coding_agent_harness.composition import build_demo_runtime

    repository = prepared_repository(tmp_path)
    first = build_demo_runtime(data_root=tmp_path / "data", scripted_actions=ACTIONS, trusted_python=Path(".venv/Scripts/python.exe").resolve())
    created = first.run(repository=repository, task_description="repair", mode="demo", trust_repo=True)
    second = build_demo_runtime(data_root=tmp_path / "data", scripted_actions=(), trusted_python=Path(".venv/Scripts/python.exe").resolve())

    loaded = second.status(UUID(created.task_id))

    assert loaded.status is TaskStatus.SUCCEEDED
    assert loaded.task_id == created.task_id
