import shutil
import subprocess

import pytest

from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.domain.models import ValidatedAction
from coding_agent_harness.web.trace import (
    DemoActionKind,
    ScenarioTraceContract,
    TerminalStatusEvent,
)

from . import _scenario_helper
from ._scenario_helper import ScenarioTraceError, run_scenario


@pytest.mark.parametrize(
    ("scenario_id", "expected_status", "expected_action", "expected_trace"),
    (
        (
            "feedback_success",
            TaskStatus.SUCCEEDED,
            DemoActionKind.APPLY_PATCH,
            (
                {"event_type": "action_selected", "action_kind": "apply_patch", "sequence": 0},
                {"event_type": "test_completed", "outcome": "failed", "sequence": 1},
                {"event_type": "feedback_produced", "feedback_code": "initial_failure", "sequence": 2},
                {"event_type": "action_selected", "action_kind": "apply_patch", "sequence": 3},
                {"event_type": "test_completed", "outcome": "passed", "sequence": 4},
                {"event_type": "feedback_produced", "feedback_code": "passed", "sequence": 5},
                {"event_type": "terminal_status", "task_status": "succeeded", "sequence": 6},
            ),
        ),
        (
            "governance_denied",
            TaskStatus.STOPPED,
            DemoActionKind.APPLY_PATCH,
            (
                {"event_type": "action_selected", "action_kind": "apply_patch", "sequence": 0},
                {
                    "event_type": "policy_decision",
                    "decision": "deny",
                    "reason_code": "test_asset_protection",
                    "sequence": 1,
                },
                {"event_type": "terminal_status", "task_status": "stopped", "sequence": 2},
            ),
        ),
        (
            "human_review_pause",
            TaskStatus.PAUSED_FOR_HUMAN,
            DemoActionKind.REQUEST_HUMAN,
            (
                {"event_type": "action_selected", "action_kind": "request_human", "sequence": 0},
                {
                    "event_type": "terminal_status",
                    "task_status": "paused_for_human",
                    "sequence": 1,
                },
            ),
        ),
    ),
)
def test_run_scenario_serializes_fixed_actions_only_at_runtime_boundary(
    scenario_id,
    expected_status,
    expected_action,
    expected_trace,
    tmp_path,
):
    registry = ScenarioRegistry()
    config = registry.get(scenario_id)
    actions_before = config.scripted_actions
    action_ids_before = tuple(id(action) for action in actions_before)

    assert isinstance(actions_before, tuple)
    assert all(isinstance(action, ValidatedAction) for action in actions_before)

    events, view, session = run_scenario(scenario_id, tmp_path)

    assert registry.get(scenario_id).scripted_actions is actions_before
    assert tuple(id(action) for action in config.scripted_actions) == action_ids_before
    assert all(isinstance(action, ValidatedAction) for action in config.scripted_actions)
    assert events[0].action_kind is expected_action
    assert isinstance(events[-1], TerminalStatusEvent)
    assert events[-1].task_status is expected_status
    assert view.status is expected_status
    assert session.status is expected_status
    assert tuple(event.model_dump(mode="json") for event in events) == expected_trace


@pytest.mark.parametrize(
    ("scenario_id", "repository_files", "worktree_files"),
    (
        (
            "feedback_success",
            {
                "calculator.py": b"def add(a, b):\n    return a - b\n",
                "tests/test_calculator.py": (
                    b"from calculator import add\n\n\ndef test_add():\n"
                    b"    assert add(1, 2) == 3\n"
                ),
            },
            {
                "calculator.py": b"def add(a, b):\n    return a + b\n",
                "tests/test_calculator.py": (
                    b"from calculator import add\n\n\ndef test_add():\n"
                    b"    assert add(1, 2) == 3\n"
                ),
            },
        ),
        (
            "governance_denied",
            {
                "calculator.py": b"def add(a, b):\n    return a + b\n",
                "tests/test_calculator.py": (
                    b"from calculator import add\n\n\ndef test_add():\n"
                    b"    assert add(1, 2) == 3\n"
                ),
            },
            {
                "calculator.py": b"def add(a, b):\n    return a + b\n",
                "tests/test_calculator.py": (
                    b"from calculator import add\n\n\ndef test_add():\n"
                    b"    assert add(1, 2) == 3\n"
                ),
            },
        ),
        (
            "human_review_pause",
            {
                "service.py": b'def health():\n    return "ok"\n',
                "tests/test_service.py": (
                    b"from service import health\n\n\ndef test_health():\n"
                    b'    assert health() == "ok"\n'
                ),
            },
            {
                "service.py": b'def health():\n    return "ok"\n',
                "tests/test_service.py": (
                    b"from service import health\n\n\ndef test_health():\n"
                    b'    assert health() == "ok"\n'
                ),
            },
        ),
    ),
)
def test_run_scenario_preserves_exact_fixture_bytes(
    scenario_id,
    repository_files,
    worktree_files,
    tmp_path,
):
    run_scenario(scenario_id, tmp_path)

    repository = tmp_path / "request_root" / "repository"
    worktrees = tmp_path / "request_root" / "data" / "worktrees"
    (worktree,) = tuple(worktrees.iterdir())
    for relative_path, expected in repository_files.items():
        assert repository.joinpath(relative_path).read_bytes() == expected
    for relative_path, expected in worktree_files.items():
        assert worktree.joinpath(relative_path).read_bytes() == expected
    for root in (repository, worktree):
        assert (root / ".gitattributes").read_bytes() == b"* text=auto eol=lf\n"
        assert (root / "conftest.py").read_bytes() == (
            b"import sys\n\nsys.dont_write_bytecode = True\n"
        )
        assert (root / "pytest.ini").read_bytes() == (
            b"[pytest]\naddopts = --assert=plain\n"
        )
        assert not tuple(root.rglob("*.pyc"))
        assert not tuple(root.rglob("__pycache__"))


@pytest.mark.parametrize(
    "scenario_id",
    ("feedback_success", "governance_denied", "human_review_pause"),
)
def test_run_scenario_releases_request_root_for_immediate_removal(
    scenario_id,
    tmp_path,
):
    run_scenario(scenario_id, tmp_path)
    request_root = tmp_path / "request_root"

    shutil.rmtree(request_root)

    assert not request_root.exists()


def test_git_commands_have_exact_isolated_boundary(monkeypatch, tmp_path):
    repository = tmp_path / "request_root" / "repository"
    repository.mkdir(parents=True)
    monkeypatch.setattr(
        _scenario_helper.os,
        "environ",
        {
            "PATH": "fixed-path",
            "SYSTEMROOT": "fixed-system-root",
            "GIT_DIR": "redirected.git",
            "GIT_CONFIG_PARAMETERS": "'core.hooksPath=host-hooks'",
            "UNRELATED": "excluded",
        },
    )
    calls = []

    def record_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(_scenario_helper.subprocess, "run", record_run)

    _scenario_helper._initialize_repository(repository)

    template = repository.parent / "git-template"
    assert template.is_dir()
    assert not tuple(template.iterdir())
    assert tuple(command for command, _ in calls) == (
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "init",
            f"--template={template}",
        ),
        ("git", "-c", "core.hooksPath=/dev/null", "add", "--all"),
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Coding Agent Harness Demo",
            "-c",
            "user.email=demo@example.invalid",
            "commit",
            "-m",
            "demo baseline",
        ),
    )
    expected_environment = {
        "PATH": "fixed-path",
        "SYSTEMROOT": "fixed-system-root",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": _scenario_helper.os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
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


def test_git_timeout_is_fixed_and_sanitized(monkeypatch, tmp_path):
    repository = tmp_path / "request_root" / "repository"
    repository.mkdir(parents=True)
    observed_timeouts = []

    def time_out(command, **kwargs):
        observed_timeouts.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(_scenario_helper.subprocess, "run", time_out)

    with pytest.raises(_scenario_helper.ScenarioSetupError) as error:
        _scenario_helper._initialize_repository(repository)

    assert str(error.value) == "demo scenario setup failed"
    assert observed_timeouts == [10]


def test_run_scenario_ignores_hostile_git_environment(monkeypatch, tmp_path):
    redirected_git_dir = tmp_path / "redirected.git"
    redirected_work_tree = tmp_path / "redirected-worktree"
    redirected_index = tmp_path / "redirected.index"
    redirected_objects = tmp_path / "redirected-objects"
    injected_template = tmp_path / "injected-template"
    for name, value in {
        "GIT_DIR": redirected_git_dir,
        "GIT_WORK_TREE": redirected_work_tree,
        "GIT_INDEX_FILE": redirected_index,
        "GIT_OBJECT_DIRECTORY": redirected_objects,
        "GIT_TEMPLATE_DIR": injected_template,
        "GIT_CONFIG_PARAMETERS": "'core.hooksPath=hooks'",
    }.items():
        monkeypatch.setenv(name, str(value))

    events, _, _ = run_scenario("human_review_pause", tmp_path)

    assert isinstance(events[-1], TerminalStatusEvent)
    assert not redirected_git_dir.exists()
    assert not redirected_work_tree.exists()
    assert not redirected_index.exists()
    assert not redirected_objects.exists()


def test_run_scenario_sanitizes_unexpected_trace_mapping_error(monkeypatch, tmp_path):
    def fail_trace_mapping(session):
        del session
        raise ValueError("raw session detail")

    monkeypatch.setattr(_scenario_helper, "_build_trace_events", fail_trace_mapping)

    with pytest.raises(ScenarioTraceError) as error:
        run_scenario("human_review_pause", tmp_path)

    assert str(error.value) == "demo trace construction failed"
    assert "raw session detail" not in str(error.value)


def test_run_scenario_sanitizes_unexpected_contract_error(monkeypatch, tmp_path):
    def fail_contract_validation(self, events):
        del self, events
        raise ValueError("raw contract detail")

    monkeypatch.setattr(ScenarioTraceContract, "validate", fail_contract_validation)

    with pytest.raises(ScenarioTraceError) as error:
        run_scenario("human_review_pause", tmp_path)

    assert str(error.value) == "demo trace construction failed"
    assert "raw contract detail" not in str(error.value)
