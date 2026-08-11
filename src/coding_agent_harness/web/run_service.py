"""Fail-closed orchestration for one fixed, offline demo worker run."""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, cast
from uuid import uuid4

from pydantic import ValidationError

from coding_agent_harness.demo.scenarios import ScenarioConfig, ScenarioRegistry

from .app import RunServiceBusyError as _AppRunServiceBusyError
from .process_boundary import ProcessBoundary, create_boundary
from .trace import DemoWorkerResult, ExecutionTraceView, TerminalStatusEvent

_ENV_ALLOWLIST = (
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
_EXECUTION_DEADLINE_SECONDS = 60.0
_TERMINATION_WAIT_SECONDS = 5.0
_WORKER_RESULT_MAX_BYTES = 64 * 1024
_WORKER_RESULT_MAX_EVENTS = 64
_RUN_LOCK = threading.Lock()
_LOGGER = logging.getLogger(__name__)

RunOutcome = Literal[
    "success",
    "busy",
    "timeout",
    "trace_incomplete",
    "worker_lifecycle_invalid",
    "termination_unconfirmed",
    "cleanup_failed",
    "internal",
]

_ERROR_RANK: Mapping[RunOutcome, int] = {
    "termination_unconfirmed": 0,
    "cleanup_failed": 1,
    "timeout": 2,
    "trace_incomplete": 2,
    "worker_lifecycle_invalid": 2,
    "internal": 2,
    "success": 3,
}


class RunServiceBusyError(_AppRunServiceBusyError):
    """The fixed signal used by the HTTP boundary for global-lock contention."""


class RunServiceError(RuntimeError):
    """A fixed, public-safe run failure code; no paths or exception details."""

    def __init__(self, code: ExcludeBusyOutcome) -> None:
        self.code = code
        super().__init__(code)


ExcludeBusyOutcome = Literal[
    "timeout",
    "trace_incomplete",
    "worker_lifecycle_invalid",
    "termination_unconfirmed",
    "cleanup_failed",
    "internal",
]


class _LockBoundary(Protocol):
    def acquire(self, blocking: bool = True) -> bool: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class _PendingResult:
    outcome: RunOutcome
    view: ExecutionTraceView | None = None


class _RequestRootCreationError(RuntimeError):
    def __init__(self, *, cleanup_failed: bool) -> None:
        self.cleanup_failed = cleanup_failed
        super().__init__("request root creation failed")


if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class _TokenUser(ctypes.Structure):
        _fields_ = [("User", _SidAndAttributes)]

    class _TokenGroups(ctypes.Structure):
        _fields_ = [
            ("GroupCount", wintypes.DWORD),
            ("Groups", _SidAndAttributes * 1),
        ]

    _security_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _security_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _security_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.ULONG),
    )
    _security_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    _security_advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    _security_advapi32.OpenProcessToken.restype = wintypes.BOOL
    _security_advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    _security_advapi32.GetTokenInformation.restype = wintypes.BOOL
    _security_advapi32.ConvertSidToStringSidW.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    _security_advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _security_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _security_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _security_kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    _security_kernel32.CreateDirectoryW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.POINTER(_SecurityAttributes),
    )
    _security_kernel32.CreateDirectoryW.restype = wintypes.BOOL
    _security_kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _security_kernel32.CreateFileW.restype = wintypes.HANDLE
    _WINDOWS_INVALID_HANDLE = ctypes.c_void_p(-1).value

    def _current_user_private_sddl() -> str:
        token = wintypes.HANDLE()
        if not _security_advapi32.OpenProcessToken(
            _security_kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_string = wintypes.LPWSTR()
        try:
            size = wintypes.DWORD()
            _security_advapi32.GetTokenInformation(
                token, 1, None, 0, ctypes.byref(size)
            )
            buffer = ctypes.create_string_buffer(size.value)
            if not _security_advapi32.GetTokenInformation(
                token, 1, buffer, size, ctypes.byref(size)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
            if not _security_advapi32.ConvertSidToStringSidW(
                token_user.User.Sid, ctypes.byref(sid_string)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            # Container/object inheritance keeps every descendant private while
            # allowing this same user to create the request-root contents.
            user_sid = sid_string.value
            restricted_size = wintypes.DWORD()
            _security_advapi32.GetTokenInformation(
                token, 11, None, 0, ctypes.byref(restricted_size)
            )
            restricted_aces = ""
            if restricted_size.value:
                restricted_buffer = ctypes.create_string_buffer(restricted_size.value)
                if not _security_advapi32.GetTokenInformation(
                    token,
                    11,
                    restricted_buffer,
                    restricted_size,
                    ctypes.byref(restricted_size),
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                groups = ctypes.cast(
                    restricted_buffer, ctypes.POINTER(_TokenGroups)
                ).contents
                groups_address = (
                    ctypes.addressof(restricted_buffer) + _TokenGroups.Groups.offset
                )
                for index in range(groups.GroupCount):
                    group = _SidAndAttributes.from_address(
                        groups_address + index * ctypes.sizeof(_SidAndAttributes)
                    )
                    restricted_sid = wintypes.LPWSTR()
                    if not _security_advapi32.ConvertSidToStringSidW(
                        group.Sid, ctypes.byref(restricted_sid)
                    ):
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        # A restricted token must also pass access checks through
                        # one of its restricting SIDs. Never add the broad
                        # Everyone SID; the per-sandbox/logon SIDs preserve the
                        # owner-only boundary while keeping restricted hosts usable.
                        if restricted_sid.value != "S-1-1-0":
                            restricted_aces += f"(A;OICI;GA;;;{restricted_sid.value})"
                    finally:
                        _security_kernel32.LocalFree(restricted_sid)
            return f"D:P(A;OICI;GA;;;{user_sid}){restricted_aces}"
        finally:
            if sid_string:
                _security_kernel32.LocalFree(sid_string)
            _security_kernel32.CloseHandle(token)

    _WINDOWS_PRIVATE_SDDL = _current_user_private_sddl()

    @contextmanager
    def _private_security_attributes():
        descriptor = wintypes.LPVOID()
        if not _security_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            _WINDOWS_PRIVATE_SDDL,
            1,
            ctypes.byref(descriptor),
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = _SecurityAttributes(
            ctypes.sizeof(_SecurityAttributes), descriptor, False
        )
        try:
            yield ctypes.byref(attributes)
        finally:
            _security_kernel32.LocalFree(descriptor)


def _create_private_directory(path: Path) -> None:
    if sys.platform != "win32":
        path.mkdir(mode=0o700)
        return
    with _private_security_attributes() as attributes:
        if not _security_kernel32.CreateDirectoryW(str(path), attributes):
            error = ctypes.get_last_error()
            if error == 183:
                raise FileExistsError(str(path))
            raise ctypes.WinError(error)


def _write_private_config(path: Path, scenario_id: str) -> None:
    encoded = json.dumps(
        {"schema_version": 1, "scenario_id": scenario_id},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("ascii")
    if sys.platform == "win32":
        with _private_security_attributes() as attributes:
            handle = _security_kernel32.CreateFileW(
                str(path),
                0x40000000,
                0,
                attributes,
                1,
                0x80,
                None,
            )
        handle_value = getattr(handle, "value", handle)
        if handle_value == _WINDOWS_INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            descriptor = msvcrt.open_osfhandle(handle_value, os.O_WRONLY)
        except Exception:
            _security_kernel32.CloseHandle(handle)
            raise
    else:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as config_file:
        config_file.write(encoded)
        config_file.flush()
        os.fsync(config_file.fileno())


class DemoRunService:
    """Own every request root and worker lifecycle under one non-blocking lock."""

    def __init__(
        self,
        *,
        scenario_registry: ScenarioRegistry,
        trusted_python: str | Path = sys.executable,
        process_factory: Callable[..., ProcessBoundary] = create_boundary,
        monotonic_clock: Callable[[], float] = time.monotonic,
        deadline_seconds: float = _EXECUTION_DEADLINE_SECONDS,
        termination_wait_seconds: float = _TERMINATION_WAIT_SECONDS,
        startup_environment: Mapping[str, str] | None = None,
        cleanup: Callable[[Path], None] | None = None,
        isolate: Callable[[Path], None] | None = None,
        lock: _LockBoundary | None = None,
        directory_creator: Callable[[Path], None] = _create_private_directory,
        config_writer: Callable[[Path, str], None] = _write_private_config,
    ) -> None:
        if deadline_seconds <= 0 or termination_wait_seconds <= 0:
            raise ValueError("deadlines must be positive")
        source_environment = (
            os.environ if startup_environment is None else startup_environment
        )
        self._scenario_registry = scenario_registry
        self._trusted_python = str(trusted_python)
        self._process_factory = process_factory
        self._monotonic = monotonic_clock
        self._deadline_seconds = deadline_seconds
        self._termination_wait_seconds = termination_wait_seconds
        self._environment = {
            key: source_environment[key]
            for key in _ENV_ALLOWLIST
            if key in source_environment
        }
        self._cleanup = self._cleanup_request_root if cleanup is None else cleanup
        self._isolate = isolate if isolate is not None else self._rename_to_quarantine
        self._lock = _RUN_LOCK if lock is None else lock
        self._directory_creator = directory_creator
        self._config_writer = config_writer

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        """Run a fixed scenario once, prioritizing safety failures over its trace."""
        pending_result = _PendingResult("success")
        worker_handle: ProcessBoundary | None = None
        config_file_handle: BinaryIO | None = None
        result_file_handle: BinaryIO | None = None
        request_root: Path | None = None
        lock_acquired = False
        request_root_created = False
        process_created = False
        termination_confirmed = False

        try:
            if not self._lock.acquire(blocking=False):
                pending_result = _PendingResult("busy")
            else:
                lock_acquired = True
                if scenario_id not in self._scenario_registry:
                    pending_result = _PendingResult("internal")
                else:
                    scenario = self._scenario_registry.get(scenario_id)
                    deadline = self._monotonic() + self._deadline_seconds
                    request_root = self._create_request_root(Path(request_root_parent))
                    request_root_created = True
                    config_path = request_root / "worker-config.json"
                    result_path = request_root / "worker-result.json"
                    self._config_writer(config_path, scenario.scenario_id)
                    worker_handle = self._start_worker(
                        config_path=config_path,
                        result_path=result_path,
                        cwd=request_root / "cwd",
                    )
                    process_created = worker_handle.process_created
                    if not process_created:
                        pending_result = self._prefer(pending_result, "internal")
                    else:
                        exit_code = worker_handle.wait(deadline)
                        # Crossing the execution deadline is terminal even if the
                        # process reports an exit concurrently. Only bounded
                        # termination/confirmation work is permitted afterwards.
                        if exit_code is None or self._monotonic() >= deadline:
                            termination_confirmed = self._terminate_and_confirm(
                                worker_handle
                            )
                            pending_result = self._prefer(
                                pending_result,
                                "timeout"
                                if termination_confirmed
                                else "termination_unconfirmed",
                            )
                        elif self._confirm(worker_handle):
                            termination_confirmed = True
                            try:
                                result, result_file_handle = self._read_worker_result(
                                    result_path, scenario
                                )
                                pending_result = _PendingResult(
                                    "success",
                                    ExecutionTraceView.from_events(result.events),
                                )
                            except Exception:  # noqa: BLE001 - invalid IPC is a fixed trace failure.
                                pending_result = self._prefer(
                                    pending_result, "trace_incomplete"
                                )
                        else:
                            termination_confirmed = self._terminate_and_confirm(
                                worker_handle
                            )
                            pending_result = self._prefer(
                                pending_result,
                                "worker_lifecycle_invalid"
                                if termination_confirmed
                                else "termination_unconfirmed",
                            )
        except _RequestRootCreationError as error:
            pending_result = self._prefer(
                pending_result,
                "cleanup_failed" if error.cleanup_failed else "internal",
            )
        except Exception:  # noqa: BLE001 - all details are intentionally discarded.
            pending_result = self._prefer(pending_result, "internal")
        finally:
            # 1. File handles first: their contents never escape the parent boundary.
            self._close_file(result_file_handle)
            self._close_file(config_file_handle)

            # 2. Any still-unconfirmed created process is killed and checked again.
            if (
                worker_handle is not None
                and process_created
                and not termination_confirmed
            ):
                termination_confirmed = self._terminate_and_confirm(worker_handle)
                if not termination_confirmed:
                    pending_result = self._prefer(
                        pending_result, "termination_unconfirmed"
                    )

            # 3. Release process/thread/Job handles only after termination is settled.
            if worker_handle is not None:
                try:
                    worker_handle.close()
                except Exception:  # noqa: BLE001 - fail closed without diagnostics.
                    pending_result = self._prefer(pending_result, "internal")

            # 4. The exact cleanup predicate deliberately separates no-worker failures.
            safe_to_cleanup = request_root_created and (
                not process_created or termination_confirmed
            )

            # 5. Never delete a root that may still contain a live process tree.
            if request_root is not None and request_root_created:
                if safe_to_cleanup:
                    try:
                        self._cleanup(request_root)
                    except Exception:  # noqa: BLE001 - cleanup failure overrides trace success.
                        pending_result = self._prefer(pending_result, "cleanup_failed")
                else:
                    pending_result = self._prefer(
                        pending_result, "termination_unconfirmed"
                    )
                    _LOGGER.error("event_id=%s", secrets.token_hex(16))
                    try:
                        self._isolate(request_root)
                    except Exception:  # noqa: BLE001 - retain the root without path logging.
                        pass

            # 6. The global lock is deliberately the final cleanup action.
            if lock_acquired:
                self._lock.release()

        # 7. One response is generated after the state machine has fully unwound.
        if pending_result.outcome == "busy":
            raise RunServiceBusyError("busy")
        if pending_result.outcome != "success":
            raise RunServiceError(cast(ExcludeBusyOutcome, pending_result.outcome))
        if pending_result.view is None:
            raise RunServiceError("internal")
        return pending_result.view

    def _start_worker(
        self, *, config_path: Path, result_path: Path, cwd: Path
    ) -> ProcessBoundary:
        command = [
            self._trusted_python,
            "-I",
            "-m",
            "coding_agent_harness.web.worker",
            "--config",
            str(config_path),
            "--result",
            str(result_path),
        ]
        if sys.platform == "win32":
            return self._process_factory(
                command,
                cwd=str(cwd),
                env=dict(self._environment),
                shell=False,
                creationflags=(
                    getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                ),
                start_new_session=False,
            )
        return self._process_factory(
            command,
            cwd=str(cwd),
            env=dict(self._environment),
            shell=False,
            creationflags=0,
            start_new_session=True,
        )

    def _create_request_root(self, request_root_parent: Path) -> Path:
        request_root_parent.mkdir(parents=True, exist_ok=True)
        for _ in range(16):
            request_root = request_root_parent / f"cah-run-{uuid4().hex}"
            try:
                self._directory_creator(request_root)
            except FileExistsError:
                continue
            try:
                self._directory_creator(request_root / "data")
                self._directory_creator(request_root / "cwd")
            except Exception:
                try:
                    self._cleanup(request_root)
                except Exception:
                    raise _RequestRootCreationError(cleanup_failed=True) from None
                raise _RequestRootCreationError(cleanup_failed=False) from None
            return request_root
        raise OSError("unable to allocate request root")

    def _read_worker_result(
        self, result_path: Path, scenario: ScenarioConfig
    ) -> tuple[DemoWorkerResult, BinaryIO]:
        result_file = result_path.open("rb")
        try:
            raw = result_file.read(_WORKER_RESULT_MAX_BYTES + 1)
            if len(raw) > _WORKER_RESULT_MAX_BYTES:
                raise ValueError
            result = self._decode_worker_result(raw)
            if result.scenario_id != scenario.scenario_id:
                raise ValueError
            if len(result.events) > _WORKER_RESULT_MAX_EVENTS:
                raise ValueError
            if result.terminal_code != scenario.expected_terminal_status:
                raise ValueError
            if result.terminal_code != scenario.trace_contract.required_terminal_status:
                raise ValueError
            scenario.trace_contract.validate(result.events)
            terminal_event = result.events[-1]
            if not isinstance(terminal_event, TerminalStatusEvent):
                raise ValueError
            if terminal_event.task_status != result.terminal_code:
                raise ValueError
            return result, result_file
        except Exception:
            result_file.close()
            raise

    @staticmethod
    def _decode_worker_result(raw: bytes) -> DemoWorkerResult:
        try:
            decoded = raw.decode("utf-8")
            parsed, position = json.JSONDecoder(
                object_pairs_hook=_reject_duplicate_json_keys
            ).raw_decode(decoded)
            if decoded[position:].strip():
                raise ValueError
            if (
                not isinstance(parsed, dict)
                or type(parsed.get("schema_version")) is not int
                or parsed["schema_version"] != 1
            ):
                raise ValueError
            return DemoWorkerResult.model_validate(parsed)
        except (UnicodeDecodeError, ValueError, ValidationError, TypeError):
            raise ValueError("invalid worker result") from None

    @staticmethod
    def _close_file(file_handle: BinaryIO | None) -> None:
        if file_handle is not None:
            try:
                file_handle.close()
            except OSError:
                pass

    @staticmethod
    def _confirm(worker_handle: ProcessBoundary) -> bool:
        try:
            return worker_handle.confirm_termination() is True
        except Exception:  # noqa: BLE001 - an uncheckable process tree is unsafe.
            return False

    def _terminate_and_confirm(self, worker_handle: ProcessBoundary) -> bool:
        termination_requested = True
        try:
            worker_handle.terminate_tree()
        except Exception:  # noqa: BLE001 - then termination remains unconfirmed.
            termination_requested = False
        try:
            root_exited = worker_handle.wait_for_root(self._termination_wait_seconds)
        except Exception:  # noqa: BLE001 - root exit could not be confirmed.
            return False
        if not termination_requested or root_exited is not True:
            return False
        return self._confirm(worker_handle)

    @staticmethod
    def _prefer(current: _PendingResult, candidate: RunOutcome) -> _PendingResult:
        if _ERROR_RANK[candidate] < _ERROR_RANK[current.outcome]:
            return _PendingResult(candidate)
        return current

    @staticmethod
    def _rename_to_quarantine(request_root: Path) -> None:
        request_root.rename(
            request_root.with_name(
                f"{request_root.name}-quarantine-{secrets.token_hex(16)}"
            )
        )

    @staticmethod
    def _cleanup_request_root(request_root: Path) -> None:
        """Delete only a verified request tree, handling read-only artifacts."""

        def has_reparse_point(path: Path) -> bool:
            attributes = getattr(
                path.stat(follow_symlinks=False), "st_file_attributes", 0
            )
            return bool(attributes & 0x400)

        if request_root.is_symlink() or has_reparse_point(request_root):
            raise OSError("request root is not a real directory")
        root = request_root.resolve(strict=True)
        if not root.is_dir():
            raise OSError("request root is not a real directory")

        def remove(path: Path) -> None:
            if path.is_symlink() or has_reparse_point(path):
                raise OSError("reparse point in request tree")
            if path.is_dir():
                # Restore directory write permission before opening/enumerating
                # children; Windows otherwise rejects traversal of read-only dirs.
                path.chmod(path.stat().st_mode | stat.S_IWRITE)
                for child in path.iterdir():
                    if child.is_symlink() or has_reparse_point(child):
                        raise OSError("reparse point in request tree")
                    child.resolve(strict=False).relative_to(root)
                    remove(child)
                for _attempt in range(2):
                    try:
                        path.rmdir()
                        break
                    except OSError:
                        if _attempt:
                            raise
                        path.chmod(path.stat().st_mode | stat.S_IWRITE)
            else:
                path.chmod(path.stat().st_mode | stat.S_IWRITE)
                for _attempt in range(2):
                    try:
                        path.unlink()
                        break
                    except OSError:
                        if _attempt:
                            raise
                        path.chmod(path.stat().st_mode | stat.S_IWRITE)

        remove(root)


def _reject_duplicate_json_keys(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
