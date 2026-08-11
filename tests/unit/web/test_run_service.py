"""Unit contracts for the supervised Web UI demo run lifecycle."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web import process_boundary
from coding_agent_harness.web.process_boundary import FakeProcessBoundary
from coding_agent_harness.web.run_service import (
    DemoRunService,
    RunServiceBusyError,
    RunServiceError,
)
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    DemoWorkerResult,
    TerminalStatusEvent,
)


def test_linux_process_group_with_only_zombies_is_terminated(
    tmp_path: Path,
) -> None:
    """A reaping-delayed zombie cannot continue modifying the request root."""
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    (proc_root / "101").mkdir()
    (proc_root / "101" / "stat").write_text("101 (worker) Z 1 77 0 0 0")
    (proc_root / "102").mkdir()
    (proc_root / "102" / "stat").write_text("102 (child) Z 1 77 0 0 0")

    assert (
        process_boundary._linux_process_group_members_are_all_zombies(77, proc_root)
        is True
    )


def test_linux_process_group_with_a_live_member_is_not_terminated(
    tmp_path: Path,
) -> None:
    """Changing a zombie member to a runnable process must make confirmation fail."""
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    (proc_root / "101").mkdir()
    (proc_root / "101" / "stat").write_text("101 (worker) Z 1 77 0 0 0")
    (proc_root / "102").mkdir()
    (proc_root / "102" / "stat").write_text("102 (child) S 1 77 0 0 0")

    assert (
        process_boundary._linux_process_group_members_are_all_zombies(77, proc_root)
        is False
    )


def test_posix_confirmation_waits_for_linux_group_member_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A just-killed descendant may be observed once before it reaches zombie state."""

    class Process:
        pid = 101

    sleeps: list[float] = []
    member_states = iter((False, True))
    monkeypatch.setattr(process_boundary.os, "getpgid", lambda _pid: 77, raising=False)
    monkeypatch.setattr(
        process_boundary.os, "killpg", lambda _pgid, _signal: None, raising=False
    )
    monkeypatch.setattr(process_boundary.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(process_boundary.sys, "platform", "linux")
    monkeypatch.setattr(
        process_boundary,
        "_linux_process_group_members_are_all_zombies",
        lambda _pgid: next(member_states),
    )
    monkeypatch.setattr(process_boundary.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(process_boundary.time, "sleep", sleeps.append)
    boundary = process_boundary.PosixProcessBoundary(Process())
    boundary.terminate_tree()

    assert boundary.confirm_termination() is True
    assert sleeps == [0.01]


def test_posix_confirmation_rejects_a_live_linux_group_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A descendant still able to execute must keep termination unconfirmed."""

    class Process:
        pid = 101

    monkeypatch.setattr(process_boundary.os, "getpgid", lambda _pid: 77, raising=False)
    monkeypatch.setattr(
        process_boundary.os, "killpg", lambda _pgid, _signal: None, raising=False
    )
    monkeypatch.setattr(process_boundary.sys, "platform", "linux")
    monkeypatch.setattr(
        process_boundary,
        "_linux_process_group_members_are_all_zombies",
        lambda _pgid: False,
    )

    assert (
        process_boundary.PosixProcessBoundary(Process()).confirm_termination() is False
    )


def test_non_linux_posix_confirmation_fails_closed_when_group_still_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Linux /proc state, a surviving process group remains unsafe."""

    class Process:
        pid = 101

    monkeypatch.setattr(process_boundary.os, "getpgid", lambda _pid: 77, raising=False)
    monkeypatch.setattr(
        process_boundary.os, "killpg", lambda _pgid, _signal: None, raising=False
    )
    monkeypatch.setattr(process_boundary.sys, "platform", "darwin")
    monkeypatch.setattr(
        process_boundary,
        "_linux_process_group_members_are_all_zombies",
        lambda _pgid: pytest.fail("non-Linux POSIX must not inspect /proc"),
    )

    assert (
        process_boundary.PosixProcessBoundary(Process()).confirm_termination() is False
    )


def _valid_result_bytes(scenario_id: str) -> bytes:
    scenario = ScenarioRegistry().get(scenario_id)
    events = (
        ActionSelectedEvent(action_kind=DemoActionKind.REQUEST_HUMAN, sequence=0),
        TerminalStatusEvent(
            task_status=TaskStatus.PAUSED_FOR_HUMAN,
            sequence=1,
        ),
    )
    if scenario_id != "human_review_pause":
        raise AssertionError("test fixture supports the short fixed scenario only")
    return (
        DemoWorkerResult(
            schema_version=1,
            scenario_id=scenario_id,
            events=events,
            terminal_code=TaskStatus.PAUSED_FOR_HUMAN,
        )
        .model_dump_json()
        .encode("utf-8")
    )


def _result_with_schema_version(value: object) -> bytes:
    payload = json.loads(_valid_result_bytes("human_review_pause"))
    payload["schema_version"] = value
    return json.dumps(payload).encode("utf-8")


def _write_result_factory(
    boundary: FakeProcessBoundary,
    payload: bytes | None = None,
    captures: list[tuple[list[str], dict[str, object]]] | None = None,
) -> Callable[..., FakeProcessBoundary]:
    def factory(command: list[str], **kwargs: object) -> FakeProcessBoundary:
        if captures is not None:
            captures.append((command, kwargs))
        result_path = Path(command[command.index("--result") + 1])
        result_path.write_bytes(payload or _valid_result_bytes("human_review_pause"))
        return boundary

    return factory


def _service(
    *,
    process_factory: Callable[..., FakeProcessBoundary],
    cleanup: Callable[[Path], None] | None = None,
    isolate: Callable[[Path], None] | None = None,
    lock: threading.Lock | None = None,
    monotonic_clock: Callable[[], float] = lambda: 100.0,
    startup_environment: dict[str, str] | None = None,
    termination_wait_seconds: float | None = None,
    directory_creator: Callable[[Path], None] | None = None,
    config_writer: Callable[[Path, str], None] | None = None,
) -> DemoRunService:
    kwargs: dict[str, object] = {
        "scenario_registry": ScenarioRegistry(),
        "trusted_python": "trusted-python",
        "process_factory": process_factory,
        "isolate": isolate,
        "lock": lock,
        "monotonic_clock": monotonic_clock,
        "startup_environment": startup_environment,
    }
    if cleanup is not None:
        kwargs["cleanup"] = cleanup
    if termination_wait_seconds is not None:
        kwargs["termination_wait_seconds"] = termination_wait_seconds
    if directory_creator is not None:
        kwargs["directory_creator"] = directory_creator
    if config_writer is not None:
        kwargs["config_writer"] = config_writer
    return DemoRunService(
        **kwargs,  # type: ignore[arg-type]
    )


def test_global_lock_rejects_a_second_run_without_creating_resources(
    tmp_path: Path,
) -> None:
    """Removing non-blocking lock acquisition would permit concurrent demo runs."""
    lock = threading.Lock()
    first = _service(
        process_factory=lambda *_args, **_kwargs: FakeProcessBoundary(), lock=lock
    )
    second = _service(
        process_factory=lambda *_args, **_kwargs: FakeProcessBoundary(), lock=lock
    )
    assert first._lock is second._lock is lock
    assert lock.acquire(blocking=False) is True

    try:
        with pytest.raises(RunServiceBusyError):
            second.run_scenario("human_review_pause", tmp_path)
    finally:
        lock.release()

    assert not tuple(tmp_path.iterdir())


def test_launches_isolated_worker_in_unique_roots_with_frozen_minimal_environment(
    tmp_path: Path,
) -> None:
    """Dropping -I, inheriting secrets, or reusing a root would violate isolation."""
    captures: list[tuple[list[str], dict[str, object]]] = []
    environment = {"PATH": "startup-path", "SECRET": "must-not-leak"}
    service = _service(
        process_factory=_write_result_factory(FakeProcessBoundary(), captures=captures),
        startup_environment=environment,
    )
    environment["PATH"] = "later-host-change"

    first = service.run_scenario("human_review_pause", tmp_path)
    second = service.run_scenario("human_review_pause", tmp_path)

    assert first.terminal_status is TaskStatus.PAUSED_FOR_HUMAN
    assert second.terminal_status is TaskStatus.PAUSED_FOR_HUMAN
    assert len(captures) == 2
    first_command, first_kwargs = captures[0]
    second_command, second_kwargs = captures[1]
    assert first_command[:5] == [
        "trusted-python",
        "-I",
        "-m",
        "coding_agent_harness.web.worker",
        "--config",
    ]
    assert first_command[6] == "--result"
    assert first_kwargs["shell"] is False
    assert first_kwargs["cwd"] == str(Path(first_command[5]).parent / "cwd")
    assert first_kwargs["env"] == {"PATH": "startup-path"}
    if sys.platform == "win32":
        assert first_kwargs["creationflags"] & 0x204 == 0x204
        assert first_kwargs["start_new_session"] is False
    else:
        assert first_kwargs["creationflags"] == 0
        assert first_kwargs["start_new_session"] is True
    assert second_kwargs["env"] == {"PATH": "startup-path"}
    assert Path(first_command[5]).parent != Path(second_command[5]).parent
    assert not tuple(tmp_path.iterdir())


def test_timeout_uses_injected_total_deadline_without_waiting(tmp_path: Path) -> None:
    """Replacing the total deadline with an unbounded wait would hang a request."""
    boundary = FakeProcessBoundary(wait_return=None, confirmations=(True,))
    observed_deadlines: list[float] = []
    original_wait = boundary.wait

    def record_wait(deadline: float) -> int | None:
        observed_deadlines.append(deadline)
        return original_wait(deadline)

    boundary.wait = record_wait  # type: ignore[method-assign]
    service = _service(process_factory=_write_result_factory(boundary))

    with pytest.raises(RunServiceError, match="^timeout$") as failure:
        service.run_scenario("human_review_pause", tmp_path)

    assert failure.value.code == "timeout"
    assert observed_deadlines == [160.0]
    assert boundary.events == ["wait", "terminate", "wait_root", "confirm", "close"]
    assert boundary.termination_waits == [5.0]
    assert not tuple(tmp_path.iterdir())


def test_exit_observed_after_execution_deadline_does_no_normal_result_work(
    tmp_path: Path,
) -> None:
    """A racing exit cannot reopen the normal IPC path after sixty seconds."""
    boundary = FakeProcessBoundary(wait_return=0, confirmations=(True,))
    clock_values = iter((100.0, 160.001))
    service = _service(
        process_factory=_write_result_factory(boundary),
        monotonic_clock=lambda: next(clock_values),
    )

    with pytest.raises(RunServiceError, match="^timeout$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert boundary.events == ["wait", "terminate", "wait_root", "confirm", "close"]
    assert boundary.termination_waits == [5.0]
    assert not tuple(tmp_path.iterdir())


def test_normal_exit_with_descendants_is_lifecycle_invalid_after_tree_cleanup(
    tmp_path: Path,
) -> None:
    """Accepting a root exit while descendants run would leak worker processes."""
    boundary = FakeProcessBoundary(confirmations=(False, True))
    service = _service(process_factory=_write_result_factory(boundary))

    with pytest.raises(RunServiceError, match="^worker_lifecycle_invalid$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert boundary.events == [
        "wait",
        "confirm",
        "terminate",
        "wait_root",
        "confirm",
        "close",
    ]
    assert not tuple(tmp_path.iterdir())


def test_unconfirmed_termination_isolates_root_and_outranks_cleanup_failure(
    tmp_path: Path,
) -> None:
    """Cleaning an occupied root or reporting a lower-ranked failure is unsafe."""
    events: list[str] = []
    boundary = FakeProcessBoundary(confirmations=(False, False, False))
    isolated: list[Path] = []

    def cleanup(_path: Path) -> None:
        events.append("cleanup")
        raise AssertionError("cleanup must not run for an occupied root")

    def isolate(path: Path) -> None:
        events.append("isolate")
        isolated.append(path)

    service = _service(
        process_factory=_write_result_factory(boundary),
        cleanup=cleanup,
        isolate=isolate,
    )

    with pytest.raises(RunServiceError, match="^termination_unconfirmed$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert boundary.events == [
        "wait",
        "confirm",
        "terminate",
        "wait_root",
        "confirm",
        "terminate",
        "wait_root",
        "confirm",
        "close",
    ]
    assert events == ["isolate"]
    assert len(isolated) == 1
    assert isolated[0].is_dir()


def test_timeout_root_wait_failure_is_unconfirmed_and_uses_injected_bound(
    tmp_path: Path,
) -> None:
    """A killed tree is not confirmed until the root exits inside the fixed bound."""
    boundary = FakeProcessBoundary(
        wait_return=None,
        root_wait_returns=(False, False),
    )
    isolated: list[Path] = []
    service = _service(
        process_factory=_write_result_factory(boundary),
        isolate=isolated.append,
        termination_wait_seconds=0.25,
    )

    with pytest.raises(RunServiceError, match="^termination_unconfirmed$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert boundary.events == [
        "wait",
        "terminate",
        "wait_root",
        "terminate",
        "wait_root",
        "close",
    ]
    assert boundary.termination_waits == [0.25, 0.25]
    assert len(isolated) == 1


@pytest.mark.parametrize("isolation_fails", (False, True))
def test_every_quarantine_logs_only_a_random_event_id(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    isolation_fails: bool,
) -> None:
    """A successful quarantine must be auditable without exposing its path."""
    boundary = FakeProcessBoundary(confirmations=(False, False, False))

    def isolate(_path: Path) -> None:
        if isolation_fails:
            raise OSError("private quarantine detail")

    service = _service(
        process_factory=_write_result_factory(boundary),
        isolate=isolate,
    )

    with caplog.at_level(logging.ERROR, logger="coding_agent_harness.web.run_service"):
        with pytest.raises(RunServiceError, match="^termination_unconfirmed$"):
            service.run_scenario("human_review_pause", tmp_path)

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert re.fullmatch(r"event_id=[0-9a-f]{32}", messages[0])
    assert str(tmp_path) not in messages[0]
    assert "private quarantine detail" not in messages[0]


def test_cleanup_failure_overrides_success_and_releases_lock_last(
    tmp_path: Path,
) -> None:
    """A successful trace must not hide a failed request-root cleanup or leak the lock."""
    events: list[str] = []
    lock = _RecordingLock(events)
    boundary = FakeProcessBoundary(events=events)

    def cleanup(_path: Path) -> None:
        events.append("cleanup")
        raise OSError("test cleanup failure")

    service = _service(
        process_factory=_write_result_factory(boundary),
        cleanup=cleanup,
        lock=lock,  # type: ignore[arg-type]
    )

    with pytest.raises(RunServiceError, match="^cleanup_failed$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert events == ["acquire", "wait", "confirm", "close", "cleanup", "release"]
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_default_cleanup_removes_read_only_directories_and_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only request directories and files must be removed on every platform."""
    chmod_calls: dict[Path, list[int]] = {}
    original_chmod = Path.chmod

    def record_chmod(path: Path, mode: int, **kwargs: object) -> None:
        chmod_calls.setdefault(path, []).append(mode)
        original_chmod(path, mode, **kwargs)

    monkeypatch.setattr(Path, "chmod", record_chmod)

    def factory(command: Sequence[str], **kwargs: object) -> FakeProcessBoundary:
        result_path = Path(command[command.index("--result") + 1])
        result_path.write_bytes(_valid_result_bytes("human_review_pause"))
        data_directory = result_path.parent / "data"
        readonly = data_directory / "worker-readonly.txt"
        readonly.write_bytes(b"worker artifact")
        readonly.chmod(stat.S_IREAD)
        data_directory.chmod(stat.S_IREAD)
        result_path.parent.joinpath("cwd").chmod(stat.S_IREAD)
        return FakeProcessBoundary()

    service = _service(process_factory=factory)
    view = service.run_scenario("human_review_pause", tmp_path)

    assert view.events
    assert not tuple(tmp_path.iterdir())
    directory_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    for directory_name in ("data", "cwd"):
        assert (
            chmod_calls[
                next(path for path in chmod_calls if path.name == directory_name)
            ][-1]
            & directory_mode
            == directory_mode
        )


def test_default_cleanup_rejects_symlink_components(tmp_path: Path) -> None:
    """Cleanup must fail closed instead of following a link outside the root."""
    root = tmp_path / "request-root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("must remain", encoding="utf-8")
    link = root / "linked"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(OSError, match="reparse point"):
        DemoRunService._cleanup_request_root(root)

    assert outside.read_text(encoding="utf-8") == "must remain"


def test_default_cleanup_rejects_replaced_root_link_before_resolve(
    tmp_path: Path,
) -> None:
    """A replaced request root link must never allow deletion of its target."""
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    sentinel = real_root / "outside-sentinel.txt"
    sentinel.write_text("must remain", encoding="utf-8")
    request_root = tmp_path / "request-root"
    try:
        request_root.symlink_to(real_root, target_is_directory=True)
    except OSError as error:
        if sys.platform != "win32":
            pytest.skip(f"symlink creation unavailable: {error}")
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(request_root), str(real_root)],
            capture_output=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(f"link creation unavailable: {error}")

    with pytest.raises(OSError, match="real directory"):
        DemoRunService._cleanup_request_root(request_root)

    assert sentinel.read_text(encoding="utf-8") == "must remain"


def test_partial_start_cleans_root_and_releases_lock(tmp_path: Path) -> None:
    """A launch failure before a usable handle must not leave a request directory or lock."""
    events: list[str] = []
    lock = _RecordingLock(events)

    def failed_start(*_args: object, **_kwargs: object) -> FakeProcessBoundary:
        events.append("start")
        raise OSError("launch failed")

    service = _service(
        process_factory=failed_start,
        lock=lock,  # type: ignore[arg-type]
    )

    with pytest.raises(RunServiceError, match="^internal$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert events == ["acquire", "start", "release"]
    assert not tuple(tmp_path.iterdir())
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_no_process_boundary_cleans_root_without_isolation(tmp_path: Path) -> None:
    """Treating a no-process start as unconfirmed would strand harmless roots."""
    boundary = FakeProcessBoundary(process=None)
    service = _service(
        process_factory=lambda *_args, **_kwargs: boundary,
    )

    with pytest.raises(RunServiceError, match="^internal$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert boundary.events == ["close"]
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("failed_stage", ("data", "cwd", "config"))
def test_request_root_setup_failure_is_atomic(
    tmp_path: Path,
    failed_stage: str,
) -> None:
    """A child-directory or config failure must not leak an owned cah-run root."""

    def create_directory(path: Path) -> None:
        if path.name == failed_stage:
            raise OSError("injected directory failure")
        path.mkdir(mode=0o700)

    def write_config(path: Path, _scenario_id: str) -> None:
        if failed_stage == "config":
            raise OSError("injected config failure")
        path.write_bytes(b"{}")

    service = _service(
        process_factory=lambda *_args, **_kwargs: FakeProcessBoundary(),
        directory_creator=create_directory,
        config_writer=write_config,
    )

    with pytest.raises(RunServiceError, match="^internal$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert not tuple(tmp_path.glob("cah-run-*"))


def test_request_root_atomic_cleanup_failure_is_ranked_cleanup_failed(
    tmp_path: Path,
) -> None:
    """A setup failure plus failed rollback must report cleanup_failed."""

    def create_directory(path: Path) -> None:
        if path.name == "data":
            raise OSError("injected directory failure")
        path.mkdir(mode=0o700)

    def fail_cleanup(_path: Path) -> None:
        raise OSError("injected rollback failure")

    service = _service(
        process_factory=lambda *_args, **_kwargs: FakeProcessBoundary(),
        directory_creator=create_directory,
        cleanup=fail_cleanup,
    )

    with pytest.raises(RunServiceError, match="^cleanup_failed$"):
        service.run_scenario("human_review_pause", tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_posix_request_artifacts_are_owner_only(tmp_path: Path) -> None:
    """Default umask must not weaken request-directory or config privacy."""
    captures: list[tuple[list[str], dict[str, object]]] = []
    boundary = FakeProcessBoundary(process=None)
    service = _service(
        process_factory=_write_result_factory(boundary, captures=captures),
        cleanup=lambda _path: None,
    )

    with pytest.raises(RunServiceError, match="^internal$"):
        service.run_scenario("human_review_pause", tmp_path)

    config_path = Path(captures[0][0][5])
    root = config_path.parent
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "data").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "cwd").stat().st_mode) == 0o700
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL contract")
def test_windows_request_artifacts_have_protected_owner_only_dacl(
    tmp_path: Path,
) -> None:
    """Inherited Users/Everyone ACEs must not expose request artifacts."""
    captures: list[tuple[list[str], dict[str, object]]] = []
    service = _service(
        process_factory=_write_result_factory(
            FakeProcessBoundary(process=None), captures=captures
        ),
        cleanup=lambda _path: None,
    )

    with pytest.raises(RunServiceError, match="^internal$"):
        service.run_scenario("human_review_pause", tmp_path)

    config_path = Path(captures[0][0][5])
    for path in (
        config_path.parent,
        config_path.parent / "data",
        config_path.parent / "cwd",
        config_path,
    ):
        sddl = _windows_dacl_sddl(path)
        assert sddl.startswith("D:P")
        assert re.search(r"\(A;(?:OICI)?;FA;;;S-1-[0-9-]+\)", sddl)
        assert all(alias not in sddl for alias in (";;;WD)", ";;;BU)", ";;;AU)"))
    shutil.rmtree(config_path.parent)


@pytest.mark.parametrize(
    "payload",
    (
        b'{"schema_version":1,"scenario_id":"human_review_pause","events":[],"terminal_code":"paused_for_human"} trailing',
        json.dumps(
            {
                "schema_version": 1,
                "scenario_id": "other_scenario",
                "events": [],
                "terminal_code": "paused_for_human",
            }
        ).encode(),
        _valid_result_bytes("human_review_pause") + b"\n{}",
        _result_with_schema_version(True),
        _result_with_schema_version(1.0),
    ),
)
def test_invalid_ipc_never_produces_a_trace(tmp_path: Path, payload: bytes) -> None:
    """Accepting trailing or mismatched IPC data would bypass the parent contract."""
    service = _service(
        process_factory=_write_result_factory(FakeProcessBoundary(), payload)
    )

    with pytest.raises(RunServiceError, match="^trace_incomplete$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert not tuple(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle contract")
def test_windows_handle_value_accepts_typed_handles_without_int_conversion() -> None:
    """Calling int(c_void_p) raises instead of yielding the native HANDLE value."""
    import ctypes

    assert process_boundary._handle_value(ctypes.c_void_p(1234)) == 1234
    assert process_boundary._handle_value(5678) == 5678


@pytest.mark.skipif(sys.platform != "win32", reason="Windows invalid-handle sentinel")
def test_windows_invalid_handle_sentinel_uses_pointer_width_unsigned_value() -> None:
    """A signed -1 comparison misses INVALID_HANDLE_VALUE returned as HANDLE."""
    import ctypes

    native_invalid = ctypes.c_void_p(-1).value
    assert native_invalid is not None
    assert process_boundary._INVALID_HANDLE_VALUE == native_invalid
    assert (
        process_boundary._handle_value(ctypes.c_void_p(-1))
        == process_boundary._INVALID_HANDLE_VALUE
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object contract")
def test_windows_job_is_limited_assigned_then_resumed_and_counts_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suspended root must enter the kill-on-close Job before it can run."""
    import ctypes

    calls: list[str] = []

    class FakeKernel32:
        def CreateJobObjectW(self, *_args: object) -> object:
            calls.append("create")
            return ctypes.c_void_p(41)

        def SetInformationJobObject(self, *_args: object) -> bool:
            calls.append("limit")
            return True

        def AssignProcessToJobObject(self, *_args: object) -> bool:
            calls.append("assign")
            return True

        def ResumeThread(self, *_args: object) -> int:
            calls.append("resume")
            return 1

        def QueryInformationJobObject(self, *_args: object) -> bool:
            calls.append("query")
            _args[2]._obj.ActiveProcesses = 0
            return True

        def CloseHandle(self, *_args: object) -> bool:
            calls.append("close")
            return True

    class Process:
        _handle = ctypes.c_void_p(21)
        _thread = ctypes.c_void_p(22)
        stdout = None
        stderr = None

    monkeypatch.setattr(process_boundary, "_kernel32", FakeKernel32())
    boundary = process_boundary.WindowsJobObjectBoundary(Process())

    assert calls == ["create", "limit", "assign", "resume"]
    assert boundary.confirm_termination() is True
    assert calls[-1] == "query"
    boundary.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launch cleanup contract")
def test_windows_post_create_failure_terminates_waits_and_closes_every_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A NUL-close failure after process creation must not strand a suspended root."""
    import ctypes

    calls: list[tuple[str, int]] = []

    class FakeKernel32:
        def __init__(self) -> None:
            self._next_nul = iter((10, 11))
            self._failed_close = False

        def CreateFileW(self, *_args: object) -> object:
            value = next(self._next_nul)
            calls.append(("create_nul", value))
            return ctypes.c_void_p(value)

        def SetHandleInformation(self, handle: object, *_args: object) -> bool:
            calls.append(("inherit", _native_value(handle)))
            return True

        def InitializeProcThreadAttributeList(
            self, attribute_list: object, *_args: object
        ) -> bool:
            size = _args[-1]._obj
            if attribute_list is None:
                size.value = 64
                return False
            calls.append(("initialize_attributes", 64))
            return True

        def UpdateProcThreadAttribute(self, *_args: object) -> bool:
            calls.append(("update_handle_list", 2))
            return True

        def DeleteProcThreadAttributeList(self, _attributes: object) -> None:
            calls.append(("delete_attributes", 64))

        def CreateProcessW(self, *_args: object) -> bool:
            process_info = _args[-1]._obj
            process_info.hProcess = 21
            process_info.hThread = 22
            process_info.dwProcessId = 23
            calls.append(("create_process", 21))
            return True

        def CloseHandle(self, handle: object) -> bool:
            value = _native_value(handle)
            calls.append(("close", value))
            if value == 11 and not self._failed_close:
                self._failed_close = True
                return False
            if value == 22:
                return False
            return True

        def TerminateProcess(self, handle: object, _code: int) -> bool:
            calls.append(("terminate", _native_value(handle)))
            raise OSError("termination cleanup failed")

        def WaitForSingleObject(self, handle: object, _timeout: int) -> int:
            calls.append(("wait", _native_value(handle)))
            raise OSError("wait cleanup failed")

        def GetExitCodeProcess(self, handle: object, code: object) -> bool:
            calls.append(("exit_code", _native_value(handle)))
            code._obj.value = 1
            return True

    def _native_value(handle: object) -> int:
        value = getattr(handle, "value", handle)
        assert isinstance(value, int)
        return value

    monkeypatch.setattr(process_boundary, "_kernel32", FakeKernel32())

    with pytest.raises(OSError):
        process_boundary._create_windows_suspended_process(
            ("trusted-python", "-I", "-c", "pass"),
            cwd=str(tmp_path),
            env={"PATH": "fixed"},
            creationflags=0x204,
        )

    assert ("create_process", 21) in calls
    assert ("terminate", 21) in calls
    assert ("wait", 21) in calls
    assert ("close", 22) in calls
    assert ("close", 21) in calls
    assert ("close", 10) in calls
    assert ("close", 11) in calls


@pytest.mark.skipif(sys.platform != "win32", reason="Windows partial-start cleanup")
def test_windows_partial_start_cleanup_attempts_every_step_when_each_one_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One cleanup exception must not skip the root wait or remaining handle closes."""
    calls: list[str] = []

    class FailingStream:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            calls.append(f"close_{self.name}")
            raise OSError(self.name)

    class PartialProcess:
        stdout = FailingStream("stdout")
        stderr = FailingStream("stderr")
        _thread = 31
        _handle = 32

        def terminate(self) -> None:
            calls.append("terminate")
            raise OSError("terminate")

        def wait(self, timeout: float) -> None:
            calls.append(f"wait_{timeout}")
            raise OSError("wait")

    def failing_close(handle: object | None) -> None:
        calls.append(f"close_handle_{handle}")
        raise OSError("handle")

    monkeypatch.setattr(process_boundary, "_close_windows_handle", failing_close)

    process_boundary._cleanup_partial_start(PartialProcess())

    assert calls == [
        "terminate",
        "wait_5.0",
        "close_stdout",
        "close_stderr",
        "close_handle_31",
        "close_handle_32",
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle inheritance")
def test_windows_worker_does_not_inherit_unrelated_inheritable_handle(
    tmp_path: Path,
) -> None:
    """Only the explicit NUL standard handles may cross the worker boundary."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.restype = ctypes.c_void_p
    unrelated = kernel32.CreateEventW(None, True, False, None)
    assert unrelated
    assert kernel32.SetHandleInformation(unrelated, 1, 1)
    code = (
        "import ctypes,sys; f=ctypes.c_ulong(); k=ctypes.WinDLL('kernel32'); "
        "sys.exit(7 if k.GetHandleInformation(ctypes.c_void_p(int(sys.argv[1])),ctypes.byref(f)) else 0)"
    )
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT")
        if key in os.environ
    }
    boundary = None
    try:
        boundary = process_boundary.create_boundary(
            (sys.executable, "-I", "-c", code, str(unrelated)),
            cwd=str(tmp_path),
            env=environment,
            creationflags=0x204,
        )
        assert boundary.wait(time.monotonic() + 5.0) == 0
        assert boundary.confirm_termination() is True
    finally:
        if boundary is not None:
            boundary.close()
        kernel32.CloseHandle(unrelated)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows real Job Object")
def test_windows_real_job_terminates_root_and_child(tmp_path: Path) -> None:
    """Closing the execution budget must kill both the worker root and its child."""
    child_code = "import time; time.sleep(60)"
    root_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-I','-c',{child_code!r}]); "
        "time.sleep(60)"
    )
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT")
        if key in os.environ
    }
    boundary = process_boundary.create_boundary(
        (sys.executable, "-I", "-c", root_code),
        cwd=str(tmp_path),
        env=environment,
        creationflags=0x204,
    )
    try:
        assert boundary.wait(time.monotonic() + 0.2) is None
        boundary.terminate_tree()
        assert boundary.wait_for_root(5.0) is True
        assert boundary.confirm_termination() is True
    finally:
        boundary.close()


class _RecordingLock:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._lock = threading.Lock()

    def acquire(self, blocking: bool = True) -> bool:
        self._events.append("acquire")
        return self._lock.acquire(blocking=blocking)

    def release(self) -> None:
        self._events.append("release")
        self._lock.release()


def _windows_dacl_sddl(path: Path) -> str:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    security_descriptor = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,
        4,
        None,
        None,
        None,
        None,
        ctypes.byref(security_descriptor),
    )
    assert result == 0
    text = wintypes.LPWSTR()
    try:
        assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            security_descriptor,
            1,
            4,
            ctypes.byref(text),
            None,
        )
        return text.value
    finally:
        if text:
            kernel32.LocalFree(text)
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)
