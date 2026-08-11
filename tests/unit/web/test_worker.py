import json
import importlib.util
import os
import py_compile
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from coding_agent_harness import composition
from coding_agent_harness.adapters.credentials.keyring_store import (
    KeyringCredentialStore,
)
from coding_agent_harness.adapters.process.pytest_runner import PytestTestRunner
from coding_agent_harness.adapters.process.runner import SubprocessLauncher
from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web.trace import DemoWorkerResult
from coding_agent_harness.web import worker
from coding_agent_harness.web.worker import WorkerConfig, WorkerError, run


def _write_config(tmp_path, content):
    config_path = tmp_path / "worker-config.json"
    result_path = tmp_path / "worker-result.json"
    config_path.write_text(json.dumps(content), encoding="utf-8")
    return config_path, result_path


def _make_directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("directory links are unavailable")
        completed = subprocess.run(
            ("cmd", "/c", "mklink", "/J", str(link), str(target)),
            capture_output=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            pytest.skip("directory links are unavailable")


def _run_cached_module(worktree, module_name):
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(worktree)!r}); "
                f"import {module_name}; "
                f"print({module_name}.VALUE)"
            ),
        ),
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    return completed.stdout.strip()


@pytest.mark.parametrize("value", (True, 1.0, "1"))
def test_worker_config_rejects_non_integer_schema_version_json_values(value):
    payload = json.dumps({"schema_version": value, "scenario_id": "human_review_pause"})

    with pytest.raises(ValidationError):
        WorkerConfig.model_validate_json(payload)


def test_worker_runs_fixed_feedback_scenario_and_writes_sequential_trace(tmp_path):
    config_path, result_path = _write_config(
        tmp_path, {"schema_version": 1, "scenario_id": "feedback_success"}
    )

    run(config_path=config_path, result_path=result_path)

    result = DemoWorkerResult.model_validate_json(result_path.read_bytes())

    assert result.scenario_id == "feedback_success"
    assert result.terminal_code is TaskStatus.SUCCEEDED
    assert [event.event_type.value for event in result.events] == [
        "action_selected",
        "test_completed",
        "feedback_produced",
        "action_selected",
        "test_completed",
        "feedback_produced",
        "terminal_status",
    ]


def test_worker_clears_external_worktree_bytecode_between_fixed_patch_tests(
    tmp_path,
):
    config_path, result_path = _write_config(
        tmp_path, {"schema_version": 1, "scenario_id": "feedback_success"}
    )

    run(config_path=config_path, result_path=result_path)

    result = DemoWorkerResult.model_validate_json(result_path.read_bytes())
    assert result.terminal_code is TaskStatus.SUCCEEDED


def test_worker_bytecode_cleanup_removes_a_deterministically_stale_cache(
    tmp_path,
):
    data_root = tmp_path / "data"
    worktree = data_root / "worktrees" / "fixed-worktree"
    worktree.mkdir(parents=True)
    source = worktree / "cache_target.py"
    source.write_text("VALUE = 'old'\n", encoding="utf-8")
    py_compile.compile(str(source), doraise=True)
    cache_file = Path(importlib.util.cache_from_source(str(source)))
    original_mtime = int(source.stat().st_mtime)
    original_size = source.stat().st_size
    source.write_text("VALUE = 'new'\n", encoding="utf-8")
    os.utime(source, (original_mtime, original_mtime))

    assert source.stat().st_size == original_size
    assert cache_file.exists()
    assert _run_cached_module(worktree, "cache_target") == "old"

    worker._clear_worktree_bytecode(worktree, data_root)

    assert not cache_file.exists()
    assert _run_cached_module(worktree, "cache_target") == "new"


def test_worker_bytecode_cleanup_rejects_outside_and_reparse_worktrees(
    tmp_path,
):
    data_root = tmp_path / "data"
    worktrees = data_root / "worktrees"
    worktrees.mkdir(parents=True)
    outside = tmp_path / "outside"
    external_cache = outside / "__pycache__"
    external_cache.mkdir(parents=True)
    sentinel = external_cache / "sentinel.pyc"
    sentinel.write_bytes(b"preserve")

    with pytest.raises(WorkerError, match="^demo worker failed$"):
        worker._clear_worktree_bytecode(outside, data_root)
    assert sentinel.read_bytes() == b"preserve"

    linked_worktree = worktrees / "linked-worktree"
    _make_directory_link(linked_worktree, outside)
    with pytest.raises(WorkerError, match="^demo worker failed$"):
        worker._clear_worktree_bytecode(linked_worktree, data_root)
    assert sentinel.read_bytes() == b"preserve"

    worktree = worktrees / "safe-worktree"
    worktree.mkdir()
    linked_cache = worktree / "__pycache__"
    _make_directory_link(linked_cache, external_cache)
    with pytest.raises(WorkerError, match="^demo worker failed$"):
        worker._clear_worktree_bytecode(worktree, data_root)
    assert sentinel.read_bytes() == b"preserve"


def test_worker_copies_the_authored_template_without_repository_mutation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(worker, "_initialize_repository", lambda repository: None)
    template = worker.resolve_repository_template("human_review_pause")
    expected_files = {
        path.relative_to(template): path.read_bytes()
        for path in template.rglob("*")
        if path.is_file()
    }
    repository = tmp_path / "repository"

    worker._prepare_repository(repository, "human_review_pause")

    actual_files = {
        path.relative_to(repository): path.read_bytes()
        for path in repository.rglob("*")
        if path.is_file()
    }
    assert actual_files == expected_files


@pytest.mark.parametrize(
    ("scenario_id", "expected_calls"),
    (
        ("feedback_success", 2),
        ("governance_denied", 1),
        ("human_review_pause", 1),
    ),
)
def test_worker_preserves_registry_actions_and_uses_exact_scripted_llm_calls(
    tmp_path, monkeypatch, scenario_id, expected_calls
):
    registry = ScenarioRegistry()
    scenario = registry.get(scenario_id)
    action_ids_before = tuple(id(action) for action in scenario.scripted_actions)
    action_content_before = tuple(
        action.model_dump(mode="json") for action in scenario.scripted_actions
    )
    captured_runtimes = []
    subprocess_requests = []
    real_build_demo_runtime = worker.build_demo_runtime
    real_launch = SubprocessLauncher.launch

    def capture_runtime(**kwargs):
        runtime = real_build_demo_runtime(**kwargs)
        captured_runtimes.append(runtime)
        return runtime

    def forbid_real_provider(*args, **kwargs):
        del args, kwargs
        raise AssertionError("real provider construction is forbidden")

    def forbid_keyring(*args, **kwargs):
        del args, kwargs
        raise AssertionError("keyring construction is forbidden")

    def capture_launch(self, request):
        subprocess_requests.append(request)
        return real_launch(self, request)

    monkeypatch.setattr(worker, "build_demo_runtime", capture_runtime)
    monkeypatch.setattr(composition, "build_real_llm", forbid_real_provider)
    monkeypatch.setattr(KeyringCredentialStore, "__init__", forbid_keyring)
    monkeypatch.setattr(SubprocessLauncher, "launch", capture_launch)
    config_path, result_path = _write_config(
        tmp_path, {"schema_version": 1, "scenario_id": scenario_id}
    )

    run(config_path=config_path, result_path=result_path)

    assert (
        tuple(id(action) for action in scenario.scripted_actions) == action_ids_before
    )
    assert (
        tuple(action.model_dump(mode="json") for action in scenario.scripted_actions)
        == action_content_before
    )
    assert len(captured_runtimes) == 1
    (runtime,) = captured_runtimes
    assert runtime.frozen_config.llm.model == "offline-scripted"
    assert runtime.provider_factory.actions == action_content_before
    assert len(runtime.provider_factory.clients) == 1
    assert len(runtime.provider_factory.clients[0].contexts) == expected_calls
    assert (
        DemoWorkerResult.model_validate_json(result_path.read_bytes()).scenario_id
        == scenario_id
    )
    assert all("remote" not in request.argv for request in subprocess_requests)


@pytest.mark.parametrize(
    "config",
    (
        {"schema_version": 2, "scenario_id": "human_review_pause"},
        {
            "schema_version": 1,
            "scenario_id": "human_review_pause",
            "actions": [{"type": "request_human", "reason": "browser input"}],
        },
    ),
)
def test_worker_rejects_untrusted_config_versions_and_action_inputs(tmp_path, config):
    config_path, result_path = _write_config(tmp_path, config)

    with pytest.raises(WorkerError, match="^demo worker failed$"):
        run(config_path=config_path, result_path=result_path)

    assert not result_path.exists()


def test_worker_rejects_preexisting_or_unsafe_result_paths(tmp_path):
    config_path, result_path = _write_config(
        tmp_path, {"schema_version": 1, "scenario_id": "human_review_pause"}
    )
    result_path.write_text("hostile", encoding="utf-8")

    with pytest.raises(WorkerError, match="^demo worker failed$"):
        run(config_path=config_path, result_path=result_path)

    assert result_path.read_text(encoding="utf-8") == "hostile"
    with pytest.raises(WorkerError, match="^demo worker failed$"):
        run(config_path=config_path, result_path=tmp_path / "not-worker-result.json")


def test_worker_rejects_symlink_result_path(tmp_path):
    config_path, result_path = _write_config(
        tmp_path, {"schema_version": 1, "scenario_id": "human_review_pause"}
    )
    outside = tmp_path / "outside.json"
    try:
        result_path.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(WorkerError, match="^demo worker failed$"):
        run(config_path=config_path, result_path=result_path)

    assert not outside.exists()


def test_worker_rejects_a_reparse_point_request_root_before_writing_outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    request_root_link = tmp_path / "request-root-link"
    _make_directory_link(request_root_link, outside)
    config_path = request_root_link / "worker-config.json"
    result_path = request_root_link / "worker-result.json"
    config_path.write_text(
        json.dumps({"schema_version": 1, "scenario_id": "human_review_pause"}),
        encoding="utf-8",
    )

    with pytest.raises(WorkerError, match="^demo worker failed$"):
        run(config_path=config_path, result_path=result_path)

    assert not (outside / "worker-result.json").exists()


def test_worker_git_initialization_uses_explicit_noninteractive_environment(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(
        worker.os,
        "environ",
        {"PATH": "safe-path", "GIT_DIR": "hostile-dir", "GIT_ASKPASS": "hostile"},
    )
    calls = []

    def record_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(worker.subprocess, "run", record_run)

    worker._initialize_repository(repository)

    expected_environment = {
        "PATH": "safe-path",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": os.devnull,
        "SSH_ASKPASS": os.devnull,
    }
    assert [kwargs["env"] for _, kwargs in calls] == [
        expected_environment,
        expected_environment,
        expected_environment,
    ]
    template = repository.parent / "git-template"
    hooks = repository.parent / "git-hooks"
    expected_commands = (
        ("git", "-c", f"core.hooksPath={hooks}", "init", f"--template={template}"),
        ("git", "-c", f"core.hooksPath={hooks}", "add", "--all"),
        (
            "git",
            "-c",
            f"core.hooksPath={hooks}",
            "-c",
            "user.name=Coding Agent Harness Demo",
            "-c",
            "user.email=demo@example.invalid",
            "commit",
            "-m",
            "demo baseline",
        ),
    )
    assert tuple(command for command, _ in calls) == expected_commands
    assert template.is_dir() and not tuple(template.iterdir())
    assert hooks.is_dir() and not tuple(hooks.iterdir())
    for _, kwargs in calls:
        assert kwargs == {
            "cwd": repository,
            "env": expected_environment,
            "check": True,
            "shell": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": 10,
        }


def test_worker_sanitizes_malformed_history_and_trace_mapping_failures(
    tmp_path, monkeypatch
):
    malformed_session = SimpleNamespace(
        history=(SimpleNamespace(action_type="unknown", safe_result="raw secret"),),
        status=TaskStatus.STOPPED,
    )
    with pytest.raises(WorkerError, match="^demo worker failed$") as malformed:
        worker._build_trace_events(malformed_session)
    assert "raw secret" not in str(malformed.value)

    config_path, result_path = _write_config(
        tmp_path, {"schema_version": 1, "scenario_id": "human_review_pause"}
    )

    def fail_trace_mapping(session):
        del session
        raise ValueError("raw trace detail")

    monkeypatch.setattr(worker, "_build_trace_events", fail_trace_mapping)
    with pytest.raises(WorkerError, match="^demo worker failed$") as mapped:
        run(config_path=config_path, result_path=result_path)
    assert "raw trace detail" not in str(mapped.value)
    assert not result_path.exists()


def test_worker_sets_the_internal_pytest_timeout_to_twenty_seconds():
    frozen = resolve_config(
        BUILTIN_CONFIG, {"llm": {"model": "offline-scripted"}}, {}, "real"
    )
    runtime = SimpleNamespace(
        frozen_config=frozen,
        runtime=SimpleNamespace(frozen_config=frozen),
    )

    worker._set_fixed_pytest_timeout(runtime)

    assert runtime.frozen_config.tests.timeout_seconds == 20
    assert runtime.runtime.frozen_config.tests.timeout_seconds == 20


def test_worker_uses_twenty_seconds_for_each_actual_pytest_request(
    tmp_path, monkeypatch
):
    observed_requests = []
    real_run = PytestTestRunner.run

    def capture_request(self, request):
        observed_requests.append(request)
        return real_run(self, request)

    monkeypatch.setattr(PytestTestRunner, "run", capture_request)
    config_path, result_path = _write_config(
        tmp_path, {"schema_version": 1, "scenario_id": "feedback_success"}
    )

    run(config_path=config_path, result_path=result_path)

    assert [request.timeout_seconds for request in observed_requests] == [20, 20]
