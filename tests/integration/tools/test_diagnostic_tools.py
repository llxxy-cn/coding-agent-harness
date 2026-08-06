from types import SimpleNamespace
import pytest

from coding_agent_harness.adapters.git.readonly import ReadonlyGitAdapter
from coding_agent_harness.adapters.process.diagnostic import DiagnosticRunner
from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.domain.actions import RunDiagnosticAction


def test_diagnostic_runner_uses_frozen_template_and_shell_false(tmp_path) -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    calls = []
    def launch(argv, cwd, shell, env):
        calls.append((argv, cwd, shell, env))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    runner = DiagnosticRunner(tmp_path, config.capabilities, launcher=launch)
    result = runner.run(RunDiagnosticAction(type="run_diagnostic", diagnostic_id="ruff_check", arguments=[]))
    assert result.ok and result.payload.exit_code == 0
    assert runner.last_argv == ("ruff", "check", ".")
    assert runner.last_shell is False
    assert len(calls) == 1 and calls[0][1] == tmp_path.resolve() and calls[0][2] is False


def test_unknown_and_demo_disabled_diagnostics_have_zero_side_effects(tmp_path) -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "demo")
    calls = []
    runner = DiagnosticRunner(tmp_path, config.capabilities, launcher=lambda *args: calls.append(args))
    result = runner.run(RunDiagnosticAction(type="run_diagnostic", diagnostic_id="ruff_check", arguments=[]))
    assert not result.ok
    assert runner.invocations == []
    assert calls == []


def test_diagnostic_environment_failure_is_precise(tmp_path) -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    def fail(*args):
        raise OSError("launcher unavailable")
    runner = DiagnosticRunner(tmp_path, config.capabilities, launcher=fail)
    result = runner.run(RunDiagnosticAction(type="run_diagnostic", diagnostic_id="ruff_check", arguments=[]))
    assert not result.ok and result.error_code.value == "environment_error"


def test_diagnostic_timeout_is_precise_and_sanitized(tmp_path) -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    runner = DiagnosticRunner(tmp_path, config.capabilities, launcher=lambda *args: (_ for _ in ()).throw(TimeoutError("secret argv/path")))
    result = runner.run(RunDiagnosticAction(type="run_diagnostic", diagnostic_id="ruff_check", arguments=[]))
    assert not result.ok and result.error_code.value == "timeout"
    assert result.sanitized_message == "diagnostic timed out"


def test_process_adapters_require_explicit_launcher(tmp_path) -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    with pytest.raises(TypeError):
        DiagnosticRunner(tmp_path, config.capabilities)
    with pytest.raises(TypeError):
        ReadonlyGitAdapter(tmp_path, "a" * 40)


def test_git_adapters_use_frozen_argv_and_spy_launcher(tmp_path) -> None:
    calls = []
    def launch(argv, cwd, shell, env):
        calls.append((argv, cwd, shell, env))
        return SimpleNamespace(returncode=0, stdout=" M a.py\n?? new.py\n", stderr="")
    adapter = ReadonlyGitAdapter(tmp_path, "a" * 40, launcher=launch)
    assert adapter.status().ok
    assert adapter.diff().ok
    assert calls[0][0] == ("git", "status", "--porcelain=v1")
    assert calls[1][0] == ("git", "diff", "a" * 40, "--")
    assert calls[0][1] == tmp_path.resolve() and calls[0][2] is False
    assert calls[0][3].get("OPENAI_API_KEY") is None
