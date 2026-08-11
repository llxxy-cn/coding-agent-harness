"""Integration contracts for supervised Web UI worker lifecycles."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web.process_boundary import (
    FakeProcessBoundary,
    create_boundary,
)
from coding_agent_harness.web.run_service import (
    DemoRunService,
    RunServiceError,
)
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    DemoWorkerResult,
    TerminalStatusEvent,
)


def _valid_result_bytes(scenario_id: str = "human_review_pause") -> bytes:
    """Construct the short registered trace without sharing production parsing."""
    if scenario_id != "human_review_pause":
        raise AssertionError("D2 fixture only represents human_review_pause")
    result = DemoWorkerResult(
        schema_version=1,
        scenario_id=scenario_id,
        events=(
            ActionSelectedEvent(
                action_kind=DemoActionKind.REQUEST_HUMAN,
                sequence=0,
            ),
            TerminalStatusEvent(
                task_status=TaskStatus.PAUSED_FOR_HUMAN,
                sequence=1,
            ),
        ),
        terminal_code=TaskStatus.PAUSED_FOR_HUMAN,
    )
    return result.model_dump_json().encode("utf-8")


def _result_writing_factory(
    boundary: FakeProcessBoundary,
    payload: bytes | None = None,
) -> Callable[..., FakeProcessBoundary]:
    """Simulate only a worker's fixed result-file boundary."""

    def factory(command: list[str], **_kwargs: object) -> FakeProcessBoundary:
        result_path = Path(command[command.index("--result") + 1])
        result_path.write_bytes(_valid_result_bytes() if payload is None else payload)
        return boundary

    return factory


def _service(
    *,
    process_factory: Callable[..., FakeProcessBoundary],
    cleanup: Callable[[Path], None] | None = None,
    isolate: Callable[[Path], None] | None = None,
    lock: threading.Lock | None = None,
    monotonic_clock: Callable[[], float] = lambda: 100.0,
    deadline_seconds: float = 60.0,
    termination_wait_seconds: float = 5.0,
) -> DemoRunService:
    return DemoRunService(
        scenario_registry=ScenarioRegistry(),
        trusted_python="trusted-python",
        process_factory=process_factory,
        monotonic_clock=monotonic_clock,
        deadline_seconds=deadline_seconds,
        termination_wait_seconds=termination_wait_seconds,
        cleanup=shutil.rmtree if cleanup is None else cleanup,
        isolate=isolate,
        lock=lock,
    )


class _RecordingLock:
    """Lock double that exposes whether finalization released it too early."""

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._lock = threading.Lock()
        self.held = False

    def acquire(self, blocking: bool = True) -> bool:
        self._events.append("acquire")
        acquired = self._lock.acquire(blocking=blocking)
        if acquired:
            self.held = True
        return acquired

    def release(self) -> None:
        assert self.held, "release must occur only after successful acquire"
        self._events.append("release")
        self.held = False
        self._lock.release()


def test_normal_completion_descendants_clean_returns_the_validated_trace(
    tmp_path: Path,
) -> None:
    """A clean worker exit with no descendants must make its trace available."""
    service = DemoRunService(
        scenario_registry=ScenarioRegistry(),
        trusted_python="trusted-python",
        process_factory=_result_writing_factory(FakeProcessBoundary()),
        monotonic_clock=lambda: 100.0,
    )

    view = service.run_scenario("human_review_pause", tmp_path)

    assert view.terminal_status is TaskStatus.PAUSED_FOR_HUMAN
    assert not tuple(tmp_path.iterdir())


def test_normal_exit_with_live_descendants_is_invalid_and_returns_no_trace(
    tmp_path: Path,
) -> None:
    """Reading a trace after an unclean normal exit would accept escaped descendants."""
    boundary = FakeProcessBoundary(confirmations=(False, True))
    service = _service(process_factory=_result_writing_factory(boundary))

    with pytest.raises(RunServiceError, match="^worker_lifecycle_invalid$") as error:
        service.run_scenario("human_review_pause", tmp_path)

    assert error.value.code == "worker_lifecycle_invalid"
    assert boundary.events == [
        "wait",
        "confirm",
        "terminate",
        "wait_root",
        "confirm",
        "close",
    ]
    assert not tuple(tmp_path.iterdir())


def test_timeout_uses_the_injected_deadline_and_returns_timeout_after_cleanup(
    tmp_path: Path,
) -> None:
    """Replacing the total deadline with an unbounded wait would hang the request."""
    boundary = FakeProcessBoundary(wait_return=None, confirmations=(True,))
    observed_deadlines: list[float] = []
    original_wait = boundary.wait

    def record_wait(deadline: float) -> int | None:
        observed_deadlines.append(deadline)
        return original_wait(deadline)

    boundary.wait = record_wait  # type: ignore[method-assign]
    service = _service(
        process_factory=_result_writing_factory(boundary),
        deadline_seconds=0.25,
    )

    with pytest.raises(RunServiceError, match="^timeout$") as error:
        service.run_scenario("human_review_pause", tmp_path)

    assert error.value.code == "timeout"
    assert observed_deadlines == [100.25]
    assert boundary.events == ["wait", "terminate", "wait_root", "confirm", "close"]
    assert not tuple(tmp_path.iterdir())


def test_timeout_with_confirmed_descendants_returns_timeout(tmp_path: Path) -> None:
    """A timed-out worker is only safely reported after its whole tree is confirmed gone."""
    boundary = FakeProcessBoundary(wait_return=None, confirmations=(True,))
    service = _service(process_factory=_result_writing_factory(boundary))

    with pytest.raises(RunServiceError, match="^timeout$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert boundary.events == ["wait", "terminate", "wait_root", "confirm", "close"]
    assert not tuple(tmp_path.iterdir())


def test_timeout_with_unconfirmed_descendants_quarantines_the_request_root(
    tmp_path: Path,
) -> None:
    """Deleting a root that may still contain a worker tree would be unsafe."""
    boundary = FakeProcessBoundary(wait_return=None, confirmations=(False, False))
    quarantined: list[Path] = []

    def isolate(path: Path) -> None:
        destination = path.with_name("quarantined-request-root")
        path.rename(destination)
        quarantined.append(destination)

    service = _service(
        process_factory=_result_writing_factory(boundary),
        isolate=isolate,
    )

    with pytest.raises(RunServiceError, match="^termination_unconfirmed$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert len(quarantined) == 1
    assert quarantined[0].is_dir()
    assert not tuple(tmp_path.glob("cah-run-*"))
    shutil.rmtree(quarantined[0])


def test_cleanup_failure_overrides_a_valid_trace(tmp_path: Path) -> None:
    """Returning success after request-root cleanup fails would leak a private root."""
    boundary = FakeProcessBoundary()
    failed_cleanup_paths: list[Path] = []

    def fail_cleanup(path: Path) -> None:
        failed_cleanup_paths.append(path)
        raise OSError("injected cleanup failure")

    service = _service(
        process_factory=_result_writing_factory(boundary),
        cleanup=fail_cleanup,
    )

    with pytest.raises(RunServiceError, match="^cleanup_failed$") as error:
        service.run_scenario("human_review_pause", tmp_path)

    assert error.value.code == "cleanup_failed"
    assert boundary.events == ["wait", "confirm", "close"]
    shutil.rmtree(failed_cleanup_paths[0])


def test_termination_unconfirmed_quarantines_without_cleanup(tmp_path: Path) -> None:
    """An unconfirmable normal-exit tree must be isolated, not recursively removed."""
    boundary = FakeProcessBoundary(confirmations=(False, False, False))
    cleanup_calls: list[Path] = []
    quarantined: list[Path] = []

    def cleanup(path: Path) -> None:
        cleanup_calls.append(path)

    def isolate(path: Path) -> None:
        destination = path.with_name("quarantined-request-root")
        path.rename(destination)
        quarantined.append(destination)

    service = _service(
        process_factory=_result_writing_factory(boundary),
        cleanup=cleanup,
        isolate=isolate,
    )

    with pytest.raises(RunServiceError, match="^termination_unconfirmed$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert cleanup_calls == []
    assert len(quarantined) == 1
    assert quarantined[0].is_dir()
    shutil.rmtree(quarantined[0])


def test_partial_worker_start_cleans_up_and_releases_its_lock(tmp_path: Path) -> None:
    """A factory error before a handle exists must not leak the lock or its root."""
    lock = threading.Lock()

    def fail_start(*_args: object, **_kwargs: object) -> FakeProcessBoundary:
        raise OSError("injected partial start failure")

    service = _service(process_factory=fail_start, lock=lock)

    with pytest.raises(RunServiceError, match="^internal$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert not tuple(tmp_path.iterdir())
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_no_worker_failure_cleans_up_without_quarantine(tmp_path: Path) -> None:
    """A no-process boundary is harmless and must not be isolated as a live tree."""
    boundary = FakeProcessBoundary(process=None)
    isolated: list[Path] = []
    service = _service(
        process_factory=lambda *_args, **_kwargs: boundary,
        isolate=isolated.append,
    )

    with pytest.raises(RunServiceError, match="^internal$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert boundary.events == ["close"]
    assert isolated == []
    assert not tuple(tmp_path.iterdir())


def test_public_error_priority_preserves_the_safest_run_scenario_outcome(
    tmp_path: Path,
) -> None:
    """Changing public failure precedence could hide unsafe teardown behind a trace."""
    quarantined: list[Path] = []
    cleanup_calls: list[Path] = []

    def fail_cleanup(path: Path) -> None:
        cleanup_calls.append(path)
        raise OSError("injected cleanup failure")

    def isolate(path: Path) -> None:
        quarantined.append(path)

    unconfirmed = _service(
        process_factory=_result_writing_factory(
            FakeProcessBoundary(confirmations=(False, False, False))
        ),
        cleanup=fail_cleanup,
        isolate=isolate,
    )
    with pytest.raises(RunServiceError, match="^termination_unconfirmed$") as error:
        unconfirmed.run_scenario("human_review_pause", tmp_path / "unconfirmed")
    assert error.value.code == "termination_unconfirmed"
    assert cleanup_calls == []
    assert len(quarantined) == 1
    shutil.rmtree(quarantined[0])

    timeout_cleanup = _service(
        process_factory=_result_writing_factory(
            FakeProcessBoundary(wait_return=None, confirmations=(True,))
        ),
        cleanup=fail_cleanup,
    )
    with pytest.raises(RunServiceError, match="^cleanup_failed$") as error:
        timeout_cleanup.run_scenario("human_review_pause", tmp_path / "timeout")
    assert error.value.code == "cleanup_failed"
    shutil.rmtree(cleanup_calls.pop())

    trace_cleanup = _service(
        process_factory=_result_writing_factory(FakeProcessBoundary(), b"{}"),
        cleanup=fail_cleanup,
    )
    with pytest.raises(RunServiceError, match="^cleanup_failed$") as error:
        trace_cleanup.run_scenario("human_review_pause", tmp_path / "trace")
    assert error.value.code == "cleanup_failed"
    shutil.rmtree(cleanup_calls.pop())

    internal_cleanup = _service(
        process_factory=_result_writing_factory(FakeProcessBoundary(process=None)),
        cleanup=fail_cleanup,
    )
    with pytest.raises(RunServiceError, match="^cleanup_failed$") as error:
        internal_cleanup.run_scenario("human_review_pause", tmp_path / "internal")
    assert error.value.code == "cleanup_failed"
    shutil.rmtree(cleanup_calls.pop())

    with pytest.raises(RunServiceError, match="^timeout$") as error:
        _service(
            process_factory=_result_writing_factory(
                FakeProcessBoundary(wait_return=None, confirmations=(True,))
            )
        ).run_scenario("human_review_pause", tmp_path / "timeout-alone")
    assert error.value.code == "timeout"

    with pytest.raises(RunServiceError, match="^trace_incomplete$") as error:
        _service(
            process_factory=_result_writing_factory(FakeProcessBoundary(), b"{}")
        ).run_scenario("human_review_pause", tmp_path / "trace-alone")
    assert error.value.code == "trace_incomplete"

    def fail_start(*_args: object, **_kwargs: object) -> FakeProcessBoundary:
        raise OSError("injected partial start failure")

    with pytest.raises(RunServiceError, match="^internal$") as error:
        _service(process_factory=fail_start).run_scenario(
            "human_review_pause", tmp_path / "internal-alone"
        )
    assert error.value.code == "internal"

    view = _service(
        process_factory=_result_writing_factory(FakeProcessBoundary())
    ).run_scenario("human_review_pause", tmp_path / "success")
    assert view.terminal_status is TaskStatus.PAUSED_FOR_HUMAN


def test_lock_is_released_after_cleanup_failure_so_the_next_run_succeeds(
    tmp_path: Path,
) -> None:
    """A return inside finalization would leave every later request permanently busy."""
    events: list[str] = []
    lock = _RecordingLock(events)
    cleanup_calls = 0
    failed_cleanup_paths: list[Path] = []

    def cleanup(path: Path) -> None:
        nonlocal cleanup_calls
        assert lock.held, "cleanup must finish before lock release"
        events.append("cleanup")
        cleanup_calls += 1
        if cleanup_calls == 1:
            failed_cleanup_paths.append(path)
            raise OSError("first cleanup fails")
        shutil.rmtree(path)

    service = _service(
        process_factory=_result_writing_factory(FakeProcessBoundary(events=events)),
        cleanup=cleanup,
        lock=lock,
    )

    with pytest.raises(RunServiceError, match="^cleanup_failed$"):
        service.run_scenario("human_review_pause", tmp_path)

    view = service.run_scenario("human_review_pause", tmp_path)

    assert view.terminal_status is TaskStatus.PAUSED_FOR_HUMAN
    assert cleanup_calls == 2
    assert events == [
        "acquire",
        "wait",
        "confirm",
        "close",
        "cleanup",
        "release",
        "acquire",
        "wait",
        "confirm",
        "close",
        "cleanup",
        "release",
    ]
    assert lock.held is False
    assert tuple(tmp_path.iterdir()) == tuple(failed_cleanup_paths)
    shutil.rmtree(failed_cleanup_paths[0])
    assert not tuple(tmp_path.iterdir())


def test_lock_is_released_only_after_close_and_isolation(tmp_path: Path) -> None:
    """Quarantine must finish before the next request can acquire the global lock."""
    events: list[str] = []
    lock = _RecordingLock(events)
    boundary = FakeProcessBoundary(confirmations=(False, False, False), events=events)
    isolated: list[Path] = []

    def isolate(path: Path) -> None:
        assert lock.held, "isolation must finish before lock release"
        events.append("isolate")
        isolated.append(path)

    service = _service(
        process_factory=_result_writing_factory(boundary),
        isolate=isolate,
        lock=lock,  # type: ignore[arg-type]
    )

    with pytest.raises(RunServiceError, match="^termination_unconfirmed$"):
        service.run_scenario("human_review_pause", tmp_path)

    assert events == [
        "acquire",
        "wait",
        "confirm",
        "terminate",
        "wait_root",
        "confirm",
        "terminate",
        "wait_root",
        "confirm",
        "close",
        "isolate",
        "release",
    ]
    assert lock.held is False
    shutil.rmtree(isolated[0])


def _worker_environment() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT")
        if key in os.environ
    }


def _wait_for_marker(path: Path, timeout_seconds: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), "child process did not start"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_windows_job_object_kills_a_real_worker_root_and_child(tmp_path: Path) -> None:
    """A Job Object must account for and kill the root plus its running child."""
    marker = tmp_path / "child-started"
    child_code = f"from pathlib import Path; import time; Path({str(marker)!r}).write_text('started'); time.sleep(60)"
    root_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-I', '-c', {child_code!r}]); "
        "time.sleep(60)"
    )
    boundary = create_boundary(
        (sys.executable, "-I", "-c", root_code),
        cwd=str(tmp_path),
        env=_worker_environment(),
        creationflags=(
            getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        ),
    )
    try:
        _wait_for_marker(marker)
        assert boundary.wait(time.monotonic() + 0.1) is None
        boundary.terminate_tree()
        assert boundary.wait_for_root(5.0) is True
        assert boundary.confirm_termination() is True
    finally:
        boundary.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_posix_killpg_kills_a_real_worker_root_and_child(tmp_path: Path) -> None:
    """A process group must account for and kill the root plus its running child."""
    marker = tmp_path / "child-started"
    child_code = f"from pathlib import Path; import time; Path({str(marker)!r}).write_text('started'); time.sleep(60)"
    root_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-I', '-c', {child_code!r}]); "
        "time.sleep(60)"
    )
    boundary = create_boundary(
        (sys.executable, "-I", "-c", root_code),
        cwd=str(tmp_path),
        env=_worker_environment(),
        start_new_session=True,
    )
    try:
        _wait_for_marker(marker)
        assert boundary.wait(time.monotonic() + 0.1) is None
        boundary.terminate_tree()
        assert boundary.wait_for_root(5.0) is True
        assert boundary.confirm_termination() is True
    finally:
        boundary.close()
