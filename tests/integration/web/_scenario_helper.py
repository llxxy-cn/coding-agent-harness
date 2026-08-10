"""In-process helpers for fixed, offline Web UI demo scenarios."""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from coding_agent_harness.composition import build_demo_runtime
from coding_agent_harness.core.harness import CoreSession
from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.demo.workspaces import resolve_repository_template
from coding_agent_harness.domain.enums import PolicyOutcome, TaskStatus, TestRunOutcome
from coding_agent_harness.domain.models import TaskId
from coding_agent_harness.security.policy import PolicyReasonCode
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    DemoFeedbackCode,
    DemoTraceEvent,
    FeedbackProducedEvent,
    PolicyDecisionEvent,
    TerminalStatusEvent,
    TestCompletedEvent,
)

_SETUP_FAILURE = "demo scenario setup failed"
_TRACE_FAILURE = "demo trace construction failed"
_GIT_TIMEOUT_SECONDS = 10
_GIT_ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "PATHEXT",
)


class ScenarioSetupError(RuntimeError):
    """Fixed, sanitized failure for isolated demo-repository setup."""


class ScenarioTraceError(RuntimeError):
    """Fixed, sanitized failure when the session cannot form a safe trace."""


class _RuntimeView(Protocol):
    """Private view boundary returned by the existing composed demo runtime."""

    task_id: str
    status: TaskStatus
    safe_summary: str


class _SessionStoreBoundary(Protocol):
    connection: sqlite3.Connection

    def load(self, task_id: TaskId) -> CoreSession: ...


class _ApplicationBoundary(Protocol):
    session_store: _SessionStoreBoundary


class _RuntimeInternalsBoundary(Protocol):
    application: _ApplicationBoundary | None


class _DemoRuntimeBoundary(Protocol):
    """Narrow typed facade over build_demo_runtime's private test API."""

    runtime: _RuntimeInternalsBoundary

    def run(
        self,
        *,
        repository: Path,
        task_description: str,
        mode: str,
        trust_repo: bool,
    ) -> _RuntimeView: ...


def _initialize_repository(repository: Path) -> None:
    """Create an isolated baseline commit without using user Git configuration."""
    environment = {
        name: os.environ[name] for name in _GIT_ENV_ALLOWLIST if name in os.environ
    }
    environment.update(
        {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    template = repository.parent / "git-template"
    commands = (
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
    try:
        template.mkdir()
        for command in commands:
            subprocess.run(
                command,
                cwd=repository,
                env=environment,
                check=True,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ScenarioSetupError(_SETUP_FAILURE) from None


def _test_outcome(safe_result: str) -> TestRunOutcome:
    result = safe_result.casefold()
    if result == "pytest passed":
        return TestRunOutcome.PASSED
    if not result or result in {
        "pytest environment unavailable",
        "pytest output was not reliably parseable",
    }:
        raise ScenarioTraceError(_TRACE_FAILURE)
    return TestRunOutcome.FAILED


def _finalize_request_root(request_root: Path) -> None:
    """Remove bytecode and clear temporary Git read-only bits for test cleanup."""
    try:
        bytecode_directories = sorted(
            request_root.rglob("__pycache__"),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in bytecode_directories:
            shutil.rmtree(directory)
        for path in request_root.rglob("*"):
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
    except (OSError, shutil.Error):
        raise ScenarioSetupError(_SETUP_FAILURE) from None


def _build_trace_events(session: CoreSession) -> tuple[DemoTraceEvent, ...]:
    """Map safe session history in order, keeping each test and feedback paired."""
    events: list[DemoTraceEvent] = []
    sequence = 0
    previous_test_outcome: TestRunOutcome | None = None

    for entry in session.history:
        if entry.action_type == "apply_patch":
            events.append(
                ActionSelectedEvent(
                    action_kind=DemoActionKind.APPLY_PATCH,
                    sequence=sequence,
                )
            )
            sequence += 1
        elif entry.action_type == "request_human":
            events.append(
                ActionSelectedEvent(
                    action_kind=DemoActionKind.REQUEST_HUMAN,
                    sequence=sequence,
                )
            )
            sequence += 1
        elif entry.action_type == "full_test":
            outcome = _test_outcome(entry.safe_result)
            events.append(TestCompletedEvent(outcome=outcome, sequence=sequence))
            sequence += 1
            if previous_test_outcome is None and outcome is TestRunOutcome.FAILED:
                feedback_code = DemoFeedbackCode.INITIAL_FAILURE
            elif outcome is TestRunOutcome.PASSED:
                feedback_code = DemoFeedbackCode.PASSED
            else:
                feedback_code = DemoFeedbackCode.CHANGED
            events.append(
                FeedbackProducedEvent(
                    feedback_code=feedback_code,
                    sequence=sequence,
                )
            )
            sequence += 1
            previous_test_outcome = outcome
        elif entry.action_type == "policy_deny":
            if entry.safe_result != PolicyReasonCode.TEST_ASSET_PROTECTION.value:
                raise ScenarioTraceError(_TRACE_FAILURE)
            events.append(
                ActionSelectedEvent(
                    action_kind=DemoActionKind.APPLY_PATCH,
                    sequence=sequence,
                )
            )
            sequence += 1
            events.append(
                PolicyDecisionEvent(
                    decision=PolicyOutcome.DENY,
                    reason_code=PolicyReasonCode.TEST_ASSET_PROTECTION,
                    sequence=sequence,
                )
            )
            sequence += 1
        else:
            raise ScenarioTraceError(_TRACE_FAILURE)

    events.append(TerminalStatusEvent(task_status=session.status, sequence=sequence))
    return tuple(events)


def run_scenario(
    scenario_id: str,
    tmp_path: Path,
) -> tuple[tuple[DemoTraceEvent, ...], _RuntimeView, CoreSession]:
    """Run one fixed scenario in an isolated temporary Git repository."""
    registry = ScenarioRegistry()
    if scenario_id not in registry:
        raise ValueError("unknown demo scenario")
    config = registry.get(scenario_id)
    request_root = Path(tmp_path) / "request_root"
    repository = request_root / "repository"

    try:
        request_root.mkdir()
        shutil.copytree(resolve_repository_template(config.repository_template), repository)
        attributes_path = repository / ".gitattributes"
        attributes_path.write_text("* text=auto eol=lf\n", encoding="utf-8", newline="\n")
        bytecode_guard_path = repository / "conftest.py"
        bytecode_guard_path.write_text(
            "import sys\n\nsys.dont_write_bytecode = True\n",
            encoding="utf-8",
            newline="\n",
        )
        pytest_config_path = repository / "pytest.ini"
        pytest_config_path.write_text(
            "[pytest]\naddopts = --assert=plain\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, shutil.Error, ValueError):
        raise ScenarioSetupError(_SETUP_FAILURE) from None
    _initialize_repository(repository)

    try:
        scripted_actions = tuple(
            action.model_dump(mode="json") for action in config.scripted_actions
        )
        runtime = cast(
            _DemoRuntimeBoundary,
            build_demo_runtime(
                data_root=request_root / "data",
                scripted_actions=scripted_actions,
                max_actions=config.max_actions,
                trusted_python=sys.executable,
            ),
        )
        try:
            view = runtime.run(
                repository=repository,
                task_description=config.task_description,
                mode="demo",
                trust_repo=True,
            )
            application = runtime.runtime.application
            if application is None:
                raise ScenarioTraceError(_TRACE_FAILURE)
            loaded_session = application.session_store.load(
                TaskId(value=UUID(view.task_id))
            )
            session = CoreSession.model_validate(loaded_session.model_dump(mode="python"))
        finally:
            application = runtime.runtime.application
            if application is not None:
                application.session_store.connection.close()
    except Exception:
        raise ScenarioTraceError(_TRACE_FAILURE) from None
    try:
        events = _build_trace_events(session)
        config.trace_contract.validate(events)
    except ScenarioTraceError:
        raise
    except Exception:
        raise ScenarioTraceError(_TRACE_FAILURE) from None
    _finalize_request_root(request_root)
    return events, view, session
