from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, StrictStr

from coding_agent_harness.adapters.process.pytest_runner import PytestTestRunner, TestRequest as RunnerRequest
from coding_agent_harness.adapters.process.runner import LaunchResult, LaunchStatus
from coding_agent_harness.domain.enums import TestPhase as RunPhase, TestRunOutcome as RunOutcome
from coding_agent_harness.domain.models import ArtifactRef, FrozenCommand, TaskId


HASH_A = "a" * 64
HASH_B = "b" * 64
TASK_ID = TaskId(value=UUID("123e4567-e89b-42d3-a456-426614174000"))


class ParsedResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    summary: StrictStr


class SpyLauncher:
    def __init__(self, result: LaunchResult) -> None:
        self.result = result
        self.requests = []

    def launch(self, request):
        self.requests.append(request)
        return self.result


class FakeArtifactStore:
    def __init__(self) -> None:
        self.contents: dict[UUID, bytes] = {}
        self.refs: list[ArtifactRef] = []

    def put(self, task_id, schema_id, schema_version, media_type, content):
        artifact_id = UUID(int=len(self.refs) + 1, version=4)
        ref = ArtifactRef(artifact_id=artifact_id, task_id=task_id, schema_id=schema_id, schema_version=schema_version, media_type=media_type, byte_length=len(content), sha256=hashlib.sha256(content).hexdigest())
        self.refs.append(ref)
        self.contents[artifact_id] = content
        return ref

    def load(self, artifact_ref):
        return self.contents[artifact_ref.artifact_id]


class SequenceClock:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


def request(root: Path, command=None, environment=None) -> RunnerRequest:
    return RunnerRequest(
        task_id=TASK_ID,
        phase=RunPhase.BASELINE,
        command=command or FrozenCommand(argv=["python", "-m", "pytest", "-q"]),
        base_commit="a" * 40,
        config_sha256=HASH_A,
        worktree=root,
        environment=environment or {},
        timeout_seconds=120,
    )


def runner(root: Path, result: LaunchResult, hashes=(HASH_A, HASH_A), parser=lambda raw, code: ParsedResult(summary="safe")):
    launcher = SpyLauncher(result)
    store = FakeArtifactStore()
    trusted_python = str((root / "trusted-python").resolve())
    wall = SequenceClock((datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=9)))
    mono = SequenceClock((10.0, 10.125))
    hash_values = iter(hashes)
    adapter = PytestTestRunner(
        launcher=launcher,
        artifact_store=store,
        workspace_hasher=lambda path: next(hash_values),
        parser=parser,
        wall_clock=wall,
        monotonic_clock=mono,
        trusted_python=trusted_python,
    )
    return adapter, launcher, store, trusted_python


def test_uses_trusted_python_fixed_cwd_shell_false_and_allowlisted_environment(tmp_path: Path) -> None:
    result = LaunchResult(status=LaunchStatus.COMPLETED, exit_code=0, stdout=b"ok", stderr=b"", stdout_truncated=False, stderr_truncated=False)
    adapter, launcher, _, trusted_python = runner(tmp_path, result)
    execution = adapter.run(request(tmp_path, environment={"SYSTEMROOT": "C:/Windows", "TEMP": "C:/Temp", "PATH": "evil", "OPENAI_API_KEY": "secret", "AWS_SECRET_ACCESS_KEY": "cloud", "GITHUB_TOKEN": "git"}))
    launched = launcher.requests[0]
    assert launched.argv == (trusted_python, "-m", "pytest", "-q")
    assert launched.cwd == tmp_path.resolve() and launched.shell is False
    assert launched.env == {"SYSTEMROOT": "C:/Windows", "TEMP": "C:/Temp"}
    assert execution.test_run.outcome is RunOutcome.PASSED


@pytest.mark.parametrize("argv", [["pytest", "-q", "|"] , ["pytest", ">", "out"], ["python", "-m", "pytest", "&&", "whoami"]])
def test_rejects_shell_syntax_before_launch(tmp_path: Path, argv) -> None:
    adapter, launcher, _, _ = runner(tmp_path, LaunchResult.completed(0, b"", b""))
    with pytest.raises(ValueError):
        adapter.run(request(tmp_path, FrozenCommand(argv=argv)))
    assert launcher.requests == []


@pytest.mark.parametrize(
    ("status", "exit_code", "parsed", "outcome", "expected_code", "has_parsed"),
    [
        (LaunchStatus.COMPLETED, 0, True, RunOutcome.PASSED, 0, True),
        (LaunchStatus.COMPLETED, 2, True, RunOutcome.FAILED, 2, True),
        (LaunchStatus.COMPLETED, 0, False, RunOutcome.UNPARSEABLE, 0, False),
        (LaunchStatus.TIMED_OUT, None, False, RunOutcome.TIMED_OUT, None, False),
        (LaunchStatus.CANCELLED, None, False, RunOutcome.CANCELLED, None, False),
        (LaunchStatus.UNKNOWN, None, False, RunOutcome.UNKNOWN_OUTCOME, None, False),
        (LaunchStatus.RESOURCE_LIMIT, 137, False, RunOutcome.RESOURCE_LIMIT, 137, False),
        (LaunchStatus.ENVIRONMENT_ERROR, 2, False, RunOutcome.ENVIRONMENT_ERROR, 2, False),
    ],
)
def test_outcome_exit_code_and_artifact_matrix(tmp_path: Path, status, exit_code, parsed, outcome, expected_code, has_parsed) -> None:
    launch = LaunchResult(status=status, exit_code=exit_code, stdout=b"safe", stderr=b"", stdout_truncated=False, stderr_truncated=False)
    parser = (lambda raw, code: ParsedResult(summary="safe")) if parsed else (lambda raw, code: None)
    adapter, _, store, _ = runner(tmp_path, launch, parser=parser)
    execution = adapter.run(request(tmp_path))
    run = execution.test_run
    assert run.outcome is outcome and run.exit_code == expected_code
    assert run.sanitized_output_ref.schema_id == "sanitized_test_output"
    assert (run.parsed_result_ref is not None) is has_parsed
    assert all(ref.schema_id != "raw_test_output" for ref in store.refs)


@pytest.mark.parametrize("exit_code", [0, 3, None])
def test_workspace_drift_overrides_parseable_and_nonparseable_results(tmp_path: Path, exit_code) -> None:
    status = LaunchStatus.COMPLETED if exit_code is not None else LaunchStatus.UNKNOWN
    adapter, _, store, _ = runner(tmp_path, LaunchResult(status=status, exit_code=exit_code, stdout=b"", stderr=b"", stdout_truncated=False, stderr_truncated=False), hashes=(HASH_A, HASH_B))
    execution = adapter.run(request(tmp_path))
    assert execution.test_run.outcome is RunOutcome.WORKSPACE_DRIFT
    assert execution.test_run.exit_code == exit_code
    assert execution.test_run.parsed_result_ref is None
    assert [ref.schema_id for ref in store.refs] == ["sanitized_test_output"]


def test_raw_output_is_transient_sanitized_artifact_is_verified_and_duration_is_monotonic(tmp_path: Path) -> None:
    secret = b"OPENAI_API_KEY=secret C:\\Users\\alice\\repo\\test.py"
    adapter, _, store, _ = runner(tmp_path, LaunchResult(status=LaunchStatus.COMPLETED, exit_code=0, stdout=secret, stderr=b"", stdout_truncated=True, stderr_truncated=False))
    execution = adapter.run(request(tmp_path, environment={"OPENAI_API_KEY": "secret"}))
    assert execution.raw_output.stdout == secret
    persisted = store.load(execution.test_run.sanitized_output_ref)
    assert b"secret" not in persisted and b"Users" not in persisted
    assert execution.test_run.duration_ms == 125
    assert execution.test_run.finished_at - execution.test_run.started_at == timedelta(seconds=9)


def test_artifact_reference_is_revalidated_before_return(tmp_path: Path) -> None:
    adapter, _, store, _ = runner(tmp_path, LaunchResult.completed(0, b"ok", b""))
    original_put = store.put
    def corrupt(*args, **kwargs):
        ref = original_put(*args, **kwargs)
        return ref.model_copy(update={"schema_id": "wrong"})
    store.put = corrupt
    with pytest.raises(ValueError, match="artifact integrity"):
        adapter.run(request(tmp_path))
