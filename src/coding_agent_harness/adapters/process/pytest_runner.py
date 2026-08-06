from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from coding_agent_harness.adapters.process.runner import BoundedRawOutput, LaunchRequest, LaunchResult, LaunchStatus, SanitizedTestOutput
from coding_agent_harness.domain.enums import TestPhase, TestRunOutcome
from coding_agent_harness.domain.models import ArtifactRef, FrozenCommand, TaskId, TestRun
from coding_agent_harness.security.canonical import canonical_bytes, canonical_sha256
from coding_agent_harness.security.redaction import redact_fields, sanitize_output


_HASH_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
_SAFE_ENV_KEYS = frozenset({"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "PATHEXT"})
_SHELL_TOKENS = frozenset({"|", "||", "&", "&&", ";", ">", ">>", "<", "<<", "`"})


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False, arbitrary_types_allowed=True)


class TestRequest(_FrozenModel):
    task_id: TaskId
    phase: TestPhase
    command: FrozenCommand
    base_commit: StrictStr = Field(pattern=_COMMIT_PATTERN)
    config_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    worktree: Path
    environment: dict[StrictStr, StrictStr]
    timeout_seconds: StrictInt = Field(ge=1, le=600)

    @field_validator("worktree")
    @classmethod
    def absolute_worktree(cls, value: Path) -> Path:
        resolved = value.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("worktree must be a directory")
        return resolved


class TestExecution(_FrozenModel):
    test_run: TestRun
    raw_output: BoundedRawOutput
    sanitized_output: SanitizedTestOutput


class Launcher(Protocol):
    def launch(self, request: LaunchRequest) -> LaunchResult: ...


class ArtifactStoreLike(Protocol):
    def put(self, task_id: TaskId, schema_id: str, schema_version: int, media_type: str, content: bytes) -> ArtifactRef: ...
    def load(self, artifact_ref: ArtifactRef) -> bytes: ...


class PytestTestRunner:
    def __init__(
        self,
        *,
        launcher: Launcher,
        artifact_store: ArtifactStoreLike,
        workspace_hasher: Callable[[Path], str],
        parser: Callable[[BoundedRawOutput, int], BaseModel | None],
        trusted_python: str,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        trusted_path = Path(trusted_python)
        if not trusted_path.is_absolute():
            raise ValueError("trusted Python must be an absolute path")
        self.launcher = launcher
        self.artifact_store = artifact_store
        self.workspace_hasher = workspace_hasher
        self.parser = parser
        self.trusted_python = trusted_python
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock

    def run(self, request: TestRequest) -> TestExecution:
        argv = self._resolve_argv(request.command)
        env = self._clean_environment(request.environment)
        workspace_before = self.workspace_hasher(request.worktree)
        started_at = self.wall_clock()
        monotonic_start = self.monotonic_clock()
        result = self.launcher.launch(LaunchRequest(argv=argv, cwd=request.worktree, shell=False, env=env, timeout_seconds=request.timeout_seconds))
        monotonic_end = self.monotonic_clock()
        finished_at = self.wall_clock()
        workspace_after = self.workspace_hasher(request.worktree)

        raw = BoundedRawOutput(stdout=result.stdout, stderr=result.stderr, stdout_truncated=result.stdout_truncated, stderr_truncated=result.stderr_truncated)
        secrets = tuple(value for key, value in request.environment.items() if key.upper() not in _SAFE_ENV_KEYS)
        sanitized = sanitize_output(raw, secrets=secrets)
        sanitized_ref = self._store_and_verify(request.task_id, "sanitized_test_output", canonical_bytes(sanitized.model_dump(mode="python")))

        parsed_ref = None
        outcome, exit_code = self._classify(result)
        workspace_drift = workspace_before != workspace_after
        if workspace_drift:
            outcome = TestRunOutcome.WORKSPACE_DRIFT
        elif result.status is LaunchStatus.COMPLETED:
            parsed = self.parser(raw, result.exit_code)
            if parsed is None:
                outcome = TestRunOutcome.UNPARSEABLE
            else:
                safe_parsed = redact_fields(parsed.model_dump(mode="python"), secrets=secrets)
                parsed_ref = self._store_and_verify(request.task_id, "parsed_result", canonical_bytes(safe_parsed))
                outcome = TestRunOutcome.PASSED if result.exit_code == 0 else TestRunOutcome.FAILED

        test_run = TestRun(
            run_id=uuid4(), task_id=request.task_id, phase=request.phase, outcome=outcome,
            command=request.command, base_commit=request.base_commit, config_sha256=request.config_sha256,
            environment_sha256=canonical_sha256(env), workspace_before_sha256=workspace_before,
            workspace_after_sha256=workspace_after, started_at=started_at, finished_at=finished_at,
            duration_ms=max(0, int((monotonic_end - monotonic_start) * 1000)), exit_code=exit_code,
            sanitized_output_ref=sanitized_ref, parsed_result_ref=parsed_ref,
        )
        return TestExecution(test_run=test_run, raw_output=raw, sanitized_output=sanitized)

    def _resolve_argv(self, command: FrozenCommand) -> tuple[str, ...]:
        logical = command.argv
        if any(item in _SHELL_TOKENS or "$(" in item for item in logical):
            raise ValueError("shell syntax is forbidden")
        if logical[0] == "pytest":
            return (self.trusted_python, "-m", "pytest", *logical[1:])
        if logical[:3] == ("python", "-m", "pytest"):
            return (self.trusted_python, "-m", "pytest", *logical[3:])
        raise ValueError("untrusted test executable")

    @staticmethod
    def _clean_environment(environment: Mapping[str, str]) -> dict[str, str]:
        return {key.upper(): value for key, value in environment.items() if key.upper() in _SAFE_ENV_KEYS}

    @staticmethod
    def _classify(result: LaunchResult) -> tuple[TestRunOutcome, int | None]:
        mapping = {
            LaunchStatus.TIMED_OUT: TestRunOutcome.TIMED_OUT,
            LaunchStatus.RESOURCE_LIMIT: TestRunOutcome.RESOURCE_LIMIT,
            LaunchStatus.ENVIRONMENT_ERROR: TestRunOutcome.ENVIRONMENT_ERROR,
            LaunchStatus.CANCELLED: TestRunOutcome.CANCELLED,
            LaunchStatus.UNKNOWN: TestRunOutcome.UNKNOWN_OUTCOME,
        }
        return mapping.get(result.status, TestRunOutcome.UNPARSEABLE), result.exit_code

    def _store_and_verify(self, task_id: TaskId, schema_id: str, content: bytes) -> ArtifactRef:
        ref = self.artifact_store.put(task_id, schema_id, 1, "application/json", content)
        if ref.task_id != task_id or ref.schema_id != schema_id or ref.schema_version != 1 or ref.media_type != "application/json" or ref.byte_length != len(content) or ref.sha256 != hashlib.sha256(content).hexdigest():
            raise ValueError("artifact integrity validation failed")
        loaded = self.artifact_store.load(ref)
        if len(loaded) != ref.byte_length or hashlib.sha256(loaded).hexdigest() != ref.sha256:
            raise ValueError("artifact integrity validation failed")
        return ref
