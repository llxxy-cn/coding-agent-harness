from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from typer.testing import CliRunner

from coding_agent_harness.domain.enums import TaskStatus


TASK_ID = "123e4567-e89b-42d3-a456-426614174000"
SECRET = "sk-test-cli-secret"


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def run(self, *, repository: Path, task_description: str, mode: str, trust_repo: bool):
        self.calls.append(("run", repository, task_description, mode, trust_repo))
        return SimpleNamespace(task_id=TASK_ID, status=TaskStatus.SUCCEEDED, safe_summary="repair completed")

    def status(self, task_id: UUID):
        self.calls.append(("status", task_id))
        if str(task_id) == TASK_ID:
            return SimpleNamespace(task_id=TASK_ID, status=TaskStatus.PAUSED_FOR_HUMAN, safe_summary="human review required")
        raise KeyError("database details must not leak")

    def resume(self, task_id: UUID):
        self.calls.append(("resume", task_id))
        if str(task_id) == TASK_ID:
            return SimpleNamespace(task_id=TASK_ID, status=TaskStatus.SUCCEEDED, safe_summary="repair completed")
        raise ValueError("internal state details must not leak")


class FakeCredentialStore:
    def __init__(self, present: bool = False) -> None:
        self.present = present
        self.calls: list[str] = []

    def set(self, value: str) -> None:
        self.calls.append("set")
        self.present = True

    def status(self) -> bool:
        self.calls.append("status")
        return self.present

    def update(self, value: str) -> None:
        self.calls.append("update")
        self.present = True

    def clear(self) -> None:
        self.calls.append("clear")
        self.present = False


class BombFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("external adapter must not be constructed")


def _cli(*, runtime=None, credential_store=None, real_provider_factory=None):
    from coding_agent_harness.cli.app import build_cli

    return build_cli(
        runtime_factory=(lambda: runtime or FakeRuntime()),
        credential_store_factory=(lambda: credential_store or FakeCredentialStore()),
        real_provider_factory=real_provider_factory or BombFactory(),
    )


def test_help_succeeds_and_console_entry_point_is_registered() -> None:
    import tomllib

    result = CliRunner().invoke(_cli(), ["--help"])
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert result.exit_code == 0
    assert project["scripts"] == {"coding-agent-harness": "coding_agent_harness.cli.app:main"}
    assert "key" in result.stdout and "credential" not in result.stdout


def test_key_commands_use_hidden_input_and_never_print_secret() -> None:
    store = FakeCredentialStore()
    cli = _cli(credential_store=store)
    runner = CliRunner()

    set_result = runner.invoke(cli, ["key", "set"], input=f"{SECRET}\n")
    status_result = runner.invoke(cli, ["key", "status"])
    update_result = runner.invoke(cli, ["key", "update"], input="sk-test-updated\n")
    clear_result = runner.invoke(cli, ["key", "clear"])

    combined = set_result.stdout + status_result.stdout + update_result.stdout + clear_result.stdout
    assert all(result.exit_code == 0 for result in (set_result, status_result, update_result, clear_result))
    assert store.calls == ["set", "status", "update", "clear"]
    assert "configured" in status_result.stdout
    assert SECRET not in combined and "sk-test-updated" not in combined


def test_demo_run_completes_without_keyring_or_real_provider(tmp_path: Path) -> None:
    from coding_agent_harness.composition import build_demo_runtime

    keyring_factory = BombFactory()
    provider_factory = BombFactory()
    runtime = build_demo_runtime(keyring_factory=keyring_factory, provider_factory=provider_factory)
    cli = _cli(runtime=runtime, credential_store=keyring_factory, real_provider_factory=provider_factory)

    result = CliRunner().invoke(cli, ["run", str(tmp_path), "fix counter", "--demo", "--trust-repo"])

    assert result.exit_code == 0
    assert TASK_ID in result.stdout
    assert TaskStatus.SUCCEEDED.value in result.stdout
    assert keyring_factory.calls == 0 and provider_factory.calls == 0


def test_real_run_without_key_fails_before_runtime_or_provider(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    provider_factory = BombFactory()
    store = FakeCredentialStore(present=False)

    result = CliRunner().invoke(_cli(runtime=runtime, credential_store=store, real_provider_factory=provider_factory), ["run", str(tmp_path), "fix counter", "--trust-repo"])

    assert result.exit_code != 0
    assert "credential is not configured" in result.stdout
    assert SECRET not in result.stdout
    assert runtime.calls == [] and provider_factory.calls == 0


def test_status_and_resume_validate_task_id_and_return_safe_summaries() -> None:
    runtime = FakeRuntime()
    cli = _cli(runtime=runtime)
    runner = CliRunner()

    status_result = runner.invoke(cli, ["status", TASK_ID])
    resume_result = runner.invoke(cli, ["resume", TASK_ID])
    invalid_result = runner.invoke(cli, ["status", "not-a-uuid"])

    assert status_result.exit_code == 0 and "human review required" in status_result.stdout
    assert resume_result.exit_code == 0 and "repair completed" in resume_result.stdout
    assert invalid_result.exit_code != 0 and "invalid task id" in invalid_result.stdout


def test_cli_maps_repo_task_and_resume_failures_without_internal_text(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    cli = _cli(runtime=runtime)
    runner = CliRunner()

    missing_repo = runner.invoke(cli, ["run", str(tmp_path / "missing"), "fix", "--demo", "--trust-repo"])
    missing_task = runner.invoke(cli, ["status", "223e4567-e89b-42d3-a456-426614174000"])
    bad_resume = runner.invoke(cli, ["resume", "223e4567-e89b-42d3-a456-426614174000"])

    combined = missing_repo.stdout + missing_task.stdout + bad_resume.stdout
    assert missing_repo.exit_code != 0 and "repository is invalid" in missing_repo.stdout
    assert missing_task.exit_code != 0 and "task not found" in missing_task.stdout
    assert bad_resume.exit_code != 0 and "task cannot be resumed" in bad_resume.stdout
    assert "database details" not in combined and "internal state details" not in combined


def test_cli_routes_demo_and_persistent_real_runtime_without_fallback(tmp_path: Path) -> None:
    from coding_agent_harness.cli.app import build_cli

    demo_runtime = FakeRuntime()
    real_runtime = FakeRuntime()
    demo_factory_calls: list[str] = []
    real_factory_calls: list[str] = []

    def demo_factory():
        demo_factory_calls.append("demo")
        return demo_runtime

    def real_factory():
        real_factory_calls.append("real")
        return real_runtime

    cli = build_cli(
        demo_runtime_factory=demo_factory,
        persistent_runtime_factory=real_factory,
        credential_store_factory=lambda: FakeCredentialStore(present=True),
    )
    runner = CliRunner()

    demo_result = runner.invoke(cli, ["run", str(tmp_path), "demo repair", "--demo", "--trust-repo"])
    real_result = runner.invoke(cli, ["run", str(tmp_path), "real repair", "--trust-repo"])
    status_result = runner.invoke(cli, ["status", TASK_ID])
    resume_result = runner.invoke(cli, ["resume", TASK_ID])

    assert all(result.exit_code == 0 for result in (demo_result, real_result, status_result, resume_result))
    assert demo_factory_calls == ["demo"]
    assert real_factory_calls == ["real", "real", "real"]
    assert demo_runtime.calls[0][3] == "demo"
    assert real_runtime.calls[0][3] == "real"


def test_default_cli_real_run_uses_default_real_runtime_only(tmp_path: Path, monkeypatch) -> None:
    from coding_agent_harness.cli.app import build_cli

    real_runtime = FakeRuntime()
    calls: list[str] = []

    def build_real():
        calls.append("real")
        return real_runtime

    def build_demo():
        raise AssertionError("demo runtime must not be constructed")

    monkeypatch.setattr("coding_agent_harness.composition.build_default_real_runtime", build_real)
    monkeypatch.setattr("coding_agent_harness.composition.build_demo_runtime", build_demo)

    result = CliRunner().invoke(build_cli(), ["run", str(tmp_path), "real repair", "--trust-repo"])

    assert result.exit_code == 0
    assert calls == ["real"]
    assert real_runtime.calls == [("run", tmp_path.resolve(), "real repair", "real", True)]
