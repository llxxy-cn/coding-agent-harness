"""Isolated entry point for fixed, offline Web UI demo scenarios."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, field_validator

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
    DemoWorkerResult,
    FeedbackProducedEvent,
    PolicyDecisionEvent,
    TerminalStatusEvent,
    TestCompletedEvent,
)

_CONFIG_BYTES_LIMIT = 4_096
_GIT_TIMEOUT_SECONDS = 10
_PYTEST_TIMEOUT_SECONDS = 20
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


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class WorkerConfig(_FrozenModel):
    """Strict, fixed IPC input: callers select only a registered scenario."""

    schema_version: StrictInt
    scenario_id: StrictStr

    @field_validator("schema_version")
    @classmethod
    def _require_schema_version_one(cls, value: int) -> int:
        if value != 1:
            raise ValueError("schema_version must be 1")
        return value

    @field_validator("scenario_id")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("scenario_id must be non-empty")
        return value


class WorkerError(RuntimeError):
    """Sanitized worker failure; never serialize failure details."""


class _RuntimeView(Protocol):
    task_id: str
    status: TaskStatus


class _SessionStoreBoundary(Protocol):
    connection: sqlite3.Connection

    def load(self, task_id: TaskId) -> CoreSession: ...


class _ApplicationBoundary(Protocol):
    session_store: _SessionStoreBoundary


class _RuntimeInternalsBoundary(Protocol):
    application: _ApplicationBoundary | None
    component_factory: object


class _DemoRuntimeBoundary(Protocol):
    runtime: _RuntimeInternalsBoundary
    frozen_config: object
    data_root: Path

    def run(
        self,
        *,
        repository: Path,
        task_description: str,
        mode: str,
        trust_repo: bool,
    ) -> _RuntimeView: ...


def _read_config(config_path: Path) -> WorkerConfig:
    try:
        content = config_path.read_bytes()
        if len(content) > _CONFIG_BYTES_LIMIT:
            raise ValueError
        return WorkerConfig.model_validate_json(content)
    except Exception:
        raise WorkerError("demo worker failed") from None


def _assert_no_link_or_reparse_components(
    path: Path, *, allow_missing_leaf: bool
) -> Path:
    raw_path = path.absolute()
    if ".." in raw_path.parts:
        raise ValueError
    components = tuple(reversed((raw_path, *raw_path.parents)))
    for component in components:
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and component == raw_path:
                continue
            raise ValueError from None
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError
    return raw_path


def _request_paths(config_path: Path, result_path: Path) -> tuple[Path, Path, Path]:
    try:
        raw_config = _assert_no_link_or_reparse_components(
            config_path, allow_missing_leaf=False
        )
        raw_result = _assert_no_link_or_reparse_components(
            result_path, allow_missing_leaf=True
        )
        if (
            raw_config.name != "worker-config.json"
            or raw_result.name != "worker-result.json"
            or raw_config.parent != raw_result.parent
            or raw_result.exists()
        ):
            raise ValueError
        config = raw_config.resolve(strict=True)
        request_root = config.parent
        if raw_result.parent.resolve(strict=True) != request_root:
            raise ValueError
        return config, raw_result, request_root
    except (OSError, ValueError):
        raise WorkerError("demo worker failed") from None


def _initialize_repository(repository: Path) -> None:
    environment = {
        name: os.environ[name] for name in _GIT_ENV_ALLOWLIST if name in os.environ
    }
    environment.update(
        {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": os.devnull,
            "SSH_ASKPASS": os.devnull,
        }
    )
    template = repository.parent / "git-template"
    hooks = repository.parent / "git-hooks"
    commands = (
        (
            "git",
            "-c",
            f"core.hooksPath={hooks}",
            "init",
            f"--template={template}",
        ),
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
    try:
        template.mkdir()
        hooks.mkdir()
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
        raise WorkerError("demo worker failed") from None


def _prepare_repository(repository: Path, template_name: str) -> None:
    try:
        if repository.exists():
            raise ValueError
        shutil.copytree(resolve_repository_template(template_name), repository)
    except (OSError, shutil.Error, ValueError):
        raise WorkerError("demo worker failed") from None
    _initialize_repository(repository)


def _test_outcome(safe_result: str) -> TestRunOutcome:
    result = safe_result.casefold()
    if result == "pytest passed":
        return TestRunOutcome.PASSED
    if not result or result in {
        "pytest environment unavailable",
        "pytest output was not reliably parseable",
    }:
        raise WorkerError("demo worker failed")
    return TestRunOutcome.FAILED


def _build_trace_events(session: CoreSession) -> tuple[DemoTraceEvent, ...]:
    """Map the safe session history sequentially, pairing each test with feedback."""
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
                raise WorkerError("demo worker failed")
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
            raise WorkerError("demo worker failed")

    events.append(TerminalStatusEvent(task_status=session.status, sequence=sequence))
    return tuple(events)


def _set_fixed_pytest_timeout(runtime: _DemoRuntimeBoundary) -> None:
    """Tighten the offline runtime's fixed test budget before it constructs tools."""
    try:
        configured = runtime.frozen_config.model_copy(
            update={
                "tests": runtime.frozen_config.tests.model_copy(
                    update={"timeout_seconds": _PYTEST_TIMEOUT_SECONDS}
                )
            }
        )
        runtime.frozen_config = configured
        runtime.runtime.frozen_config = configured
    except Exception:
        raise WorkerError("demo worker failed") from None


def _resolve_expected_worktree(worktree: Path, data_root: Path) -> Path:
    raw_data_root = _assert_no_link_or_reparse_components(
        Path(data_root), allow_missing_leaf=False
    )
    data_root_resolved = raw_data_root.resolve(strict=True)
    raw_worktrees_root = _assert_no_link_or_reparse_components(
        raw_data_root / "worktrees", allow_missing_leaf=False
    )
    worktrees_root = raw_worktrees_root.resolve(strict=True)
    raw_worktree = _assert_no_link_or_reparse_components(
        Path(worktree), allow_missing_leaf=False
    )
    resolved_worktree = raw_worktree.resolve(strict=True)
    if (
        worktrees_root.parent != data_root_resolved
        or resolved_worktree.parent != worktrees_root
    ):
        raise ValueError
    return resolved_worktree


def _clear_worktree_bytecode(worktree: Path, data_root: Path) -> None:
    try:
        root = _resolve_expected_worktree(worktree, data_root)
        directories = sorted(
            root.rglob("__pycache__"), key=lambda path: len(path.parts), reverse=True
        )
        for directory in directories:
            raw_directory = _assert_no_link_or_reparse_components(
                directory, allow_missing_leaf=False
            )
            resolved_directory = raw_directory.resolve(strict=True)
            if (
                not resolved_directory.is_dir()
                or root not in resolved_directory.parents
            ):
                raise ValueError
            _assert_no_link_or_reparse_components(
                raw_directory, allow_missing_leaf=False
            )
            shutil.rmtree(raw_directory)
    except (OSError, shutil.Error, ValueError):
        raise WorkerError("demo worker failed") from None


class _BytecodeClearingPytestRunner:
    def __init__(self, runner: object, data_root: Path) -> None:
        self._runner = runner
        self._data_root = data_root

    def run(self, request: object) -> object:
        try:
            _clear_worktree_bytecode(request.worktree, self._data_root)
            return self._runner.run(request)
        except WorkerError:
            raise
        except Exception:
            raise WorkerError("demo worker failed") from None


def _install_worktree_bytecode_cleanup(runtime: _DemoRuntimeBoundary) -> None:
    """Keep generated bytecode outside the authored repository from crossing test runs."""
    try:
        component_factory = runtime.runtime.component_factory
        if not callable(component_factory):
            raise ValueError

        def components(workspace, task_id, artifact_store, effective_config):
            built = component_factory(
                workspace, task_id, artifact_store, effective_config
            )
            built.full_test_runner.runner = _BytecodeClearingPytestRunner(
                built.full_test_runner.runner, runtime.data_root
            )
            return built

        runtime.runtime.component_factory = components
    except Exception:
        raise WorkerError("demo worker failed") from None


def _write_result(
    result_path: Path, request_root: Path, result: DemoWorkerResult
) -> None:
    try:
        checked_result = _assert_no_link_or_reparse_components(
            result_path, allow_missing_leaf=True
        )
        if checked_result.parent.resolve(strict=True) != request_root:
            raise ValueError
        payload = json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        descriptor = os.open(
            checked_result, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
    except (OSError, TypeError, ValueError):
        raise WorkerError("demo worker failed") from None


def run(*, config_path: Path, result_path: Path) -> None:
    """Run one allowlisted scenario and write a typed, fixed-schema result JSON file."""
    config_path, result_path, request_root = _request_paths(config_path, result_path)
    config = _read_config(config_path)
    registry = ScenarioRegistry()
    if config.scenario_id not in registry:
        raise WorkerError("demo worker failed")
    scenario = registry.get(config.scenario_id)
    repository = request_root / "repository"
    data_root = request_root / "data"

    _prepare_repository(repository, scenario.repository_template)
    try:
        scripted_actions = tuple(
            action.model_dump(mode="json") for action in scenario.scripted_actions
        )
        runtime = cast(
            _DemoRuntimeBoundary,
            build_demo_runtime(
                data_root=data_root,
                scripted_actions=scripted_actions,
                max_actions=scenario.max_actions,
                trusted_python=sys.executable,
            ),
        )
        _set_fixed_pytest_timeout(runtime)
        _install_worktree_bytecode_cleanup(runtime)
        try:
            view = runtime.run(
                repository=repository,
                task_description=scenario.task_description,
                mode="demo",
                trust_repo=True,
            )
            application = runtime.runtime.application
            if application is None:
                raise WorkerError("demo worker failed")
            session = application.session_store.load(TaskId(value=UUID(view.task_id)))
        finally:
            application = runtime.runtime.application
            if application is not None:
                application.session_store.connection.close()
        events = _build_trace_events(session)
        scenario.trace_contract.validate(events)
        if (
            view.status != session.status
            or view.status != scenario.expected_terminal_status
            or events[-1].task_status != view.status
        ):
            raise WorkerError("demo worker failed")
        result = DemoWorkerResult(
            schema_version=1,
            scenario_id=scenario.scenario_id,
            events=events,
            terminal_code=view.status,
        )
    except WorkerError:
        raise
    except Exception:
        raise WorkerError("demo worker failed") from None
    _write_result(result_path, request_root, result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--result", required=True)
    try:
        arguments = parser.parse_args(argv)
        run(config_path=Path(arguments.config), result_path=Path(arguments.result))
    except (SystemExit, WorkerError, Exception):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
