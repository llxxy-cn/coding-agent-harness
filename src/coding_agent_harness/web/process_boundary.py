"""Supervised process-tree boundaries for the isolated Web UI worker."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Protocol


class ProcessBoundary(Protocol):
    """The parent-facing lifecycle contract for one worker process tree."""

    process_created: bool

    def wait(self, deadline: float) -> int | None: ...

    def confirm_termination(self) -> bool: ...

    def terminate_tree(self) -> None: ...

    def wait_for_root(self, timeout_seconds: float) -> bool: ...

    def close(self) -> None: ...


class PosixProcessBoundary:
    """A worker session whose complete process group is the termination unit."""

    process_created = True

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._pgid = os.getpgid(process.pid)

    def wait(self, deadline: float) -> int | None:
        try:
            return self._process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return None

    def confirm_termination(self) -> bool:
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        return False

    def terminate_tree(self) -> None:
        try:
            os.killpg(self._pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def wait_for_root(self, timeout_seconds: float) -> bool:
        try:
            self._process.wait(timeout=timeout_seconds)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return True

    def close(self) -> None:
        _close_streams(self._process)


if sys.platform == "win32":  # pragma: no cover - exercised on a Windows runner.
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _INVALID_DWORD = 0xFFFFFFFF
    _WAIT_OBJECT_0 = 0
    _WAIT_TIMEOUT = 0x00000102
    _INFINITE = 0xFFFFFFFF
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    _PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
    _STARTF_USESTDHANDLES = 0x00000100
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _HANDLE_FLAG_INHERIT = 0x00000001
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JobObjectBasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    class _StartupInfoW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _ProcessInformation(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class _StartupInfoExW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _StartupInfoW),
            ("lpAttributeList", wintypes.LPVOID),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    )
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.SetHandleInformation.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.CreateProcessW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoW),
        ctypes.POINTER(_ProcessInformation),
    )
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.InitializeProcThreadAttributeList.argtypes = (
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    )
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = (
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        wintypes.LPVOID,
    )
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.DeleteProcThreadAttributeList.argtypes = (wintypes.LPVOID,)
    _kernel32.DeleteProcThreadAttributeList.restype = None

    def _win_error() -> OSError:
        return ctypes.WinError(ctypes.get_last_error())

    def _handle_value(handle: object) -> int:
        if isinstance(handle, int):
            return handle
        value = getattr(handle, "value", None)
        if isinstance(value, int):
            return value
        raise TypeError("invalid Windows handle")

    def _close_windows_handle(handle: object | None) -> None:
        if handle is None:
            return
        close = getattr(handle, "Close", None)
        if callable(close):
            close()
            return
        if not _kernel32.CloseHandle(handle):
            raise _win_error()

    def _cleanup_windows_created_process(
        process: object,
        *,
        job_handle: object | None = None,
        wait_seconds: float = 5.0,
    ) -> None:
        """Failure-atomic cleanup that attempts every acquired Windows resource."""
        process_handle = getattr(process, "_handle", None)
        thread_handle = getattr(process, "_thread", None)
        _cleanup_windows_handles(
            process_handle=process_handle,
            thread_handle=thread_handle,
            job_handle=job_handle,
            wait_seconds=wait_seconds,
        )
        setattr(process, "_thread", None)
        setattr(process, "_handle", None)

    def _cleanup_windows_handles(
        *,
        process_handle: object | None,
        thread_handle: object | None,
        job_handle: object | None = None,
        wait_seconds: float = 5.0,
    ) -> None:
        """Attempt termination, bounded wait, and every close despite any failure."""
        if process_handle is not None:
            try:
                _kernel32.TerminateProcess(process_handle, 1)
            except Exception:
                pass
            try:
                milliseconds = max(0, min(_INFINITE - 1, int(wait_seconds * 1000)))
                _kernel32.WaitForSingleObject(process_handle, milliseconds)
            except Exception:
                pass
        for handle in (job_handle, thread_handle, process_handle):
            try:
                _close_windows_handle(handle)
            except Exception:
                pass

    class _WindowsCreatedProcess:
        """Small Popen-compatible owner for handles returned by CreateProcessW."""

        stdout = None
        stderr = None

        def __init__(
            self, process_info: _ProcessInformation, args: Sequence[str]
        ) -> None:
            self.args = tuple(args)
            self._handle = process_info.hProcess
            self._thread = process_info.hThread
            self.pid = process_info.dwProcessId
            self.returncode: int | None = None

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is not None:
                return self.returncode
            milliseconds = _INFINITE
            if timeout is not None:
                milliseconds = max(0, min(_INFINITE - 1, int(timeout * 1000)))
            wait_result = _kernel32.WaitForSingleObject(self._handle, milliseconds)
            if wait_result == _WAIT_TIMEOUT:
                raise subprocess.TimeoutExpired(self.args, timeout)
            if wait_result != _WAIT_OBJECT_0:
                raise _win_error()
            exit_code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(self._handle, ctypes.byref(exit_code)):
                raise _win_error()
            self.returncode = int(exit_code.value)
            return self.returncode

        def poll(self) -> int | None:
            try:
                return self.wait(timeout=0)
            except subprocess.TimeoutExpired:
                return None

        def terminate(self) -> None:
            if self.returncode is not None:
                return
            if not _kernel32.TerminateProcess(self._handle, 1):
                if self.poll() is None:
                    raise _win_error()

    def _create_windows_suspended_process(
        command: Sequence[str], *, cwd: str, env: Mapping[str, str], creationflags: int
    ) -> _WindowsCreatedProcess:
        """Retain the primary thread handle Python's Popen closes too early to resume."""
        if any("\x00" in key or "\x00" in value for key, value in env.items()):
            raise ValueError("NUL is not valid in a worker environment")
        environment_items = sorted(
            (f"{key}={value}" for key, value in env.items()), key=str.upper
        )
        environment = ctypes.create_unicode_buffer(
            "\x00".join(environment_items) + "\x00\x00"
        )
        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline(list(command))
        )
        null_input = _kernel32.CreateFileW(
            "NUL",
            _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if _handle_value(null_input) == _INVALID_HANDLE_VALUE:
            raise _win_error()
        null_output = _kernel32.CreateFileW(
            "NUL",
            _GENERIC_WRITE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if _handle_value(null_output) == _INVALID_HANDLE_VALUE:
            _close_windows_handle(null_input)
            raise _win_error()
        process_info = _ProcessInformation()
        startup = _StartupInfoExW()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = null_input
        startup.StartupInfo.hStdOutput = null_output
        startup.StartupInfo.hStdError = null_output
        attribute_size = ctypes.c_size_t()
        attribute_buffer: object | None = None
        attributes_initialized = False
        process: _WindowsCreatedProcess | None = None
        close_failure: OSError | None = None
        try:
            _kernel32.InitializeProcThreadAttributeList(
                None, 1, 0, ctypes.byref(attribute_size)
            )
            if attribute_size.value == 0:
                raise _win_error()
            attribute_buffer = ctypes.create_string_buffer(attribute_size.value)
            startup.lpAttributeList = ctypes.cast(attribute_buffer, wintypes.LPVOID)
            if not _kernel32.InitializeProcThreadAttributeList(
                startup.lpAttributeList, 1, 0, ctypes.byref(attribute_size)
            ):
                raise _win_error()
            attributes_initialized = True
            inherited_handles = (wintypes.HANDLE * 2)(null_input, null_output)
            if not _kernel32.UpdateProcThreadAttribute(
                startup.lpAttributeList,
                0,
                _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.byref(inherited_handles),
                ctypes.sizeof(inherited_handles),
                None,
                None,
            ):
                raise _win_error()
            for handle in (null_input, null_output):
                if not _kernel32.SetHandleInformation(
                    handle, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT
                ):
                    raise _win_error()
            if not _kernel32.CreateProcessW(
                None,
                command_line,
                None,
                None,
                True,
                creationflags
                | _CREATE_UNICODE_ENVIRONMENT
                | _EXTENDED_STARTUPINFO_PRESENT,
                ctypes.byref(environment),
                cwd,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(process_info),
            ):
                raise _win_error()
            try:
                process = _WindowsCreatedProcess(process_info, command)
            except BaseException:
                _cleanup_windows_handles(
                    process_handle=process_info.hProcess,
                    thread_handle=process_info.hThread,
                )
                raise
        finally:
            if attributes_initialized:
                try:
                    _kernel32.DeleteProcThreadAttributeList(startup.lpAttributeList)
                except Exception:
                    if close_failure is None:
                        close_failure = _win_error()
            for handle in (null_output, null_input):
                try:
                    _close_windows_handle(handle)
                except OSError as error:
                    if close_failure is None:
                        close_failure = error
            if close_failure is not None and process is None:
                raise close_failure
        if close_failure is not None:
            _cleanup_windows_created_process(process)
            raise close_failure
        return process

    class WindowsJobObjectBoundary:
        """A kill-on-close Job Object assigned before the suspended worker runs."""

        process_created = True

        def __init__(self, process: object) -> None:
            self._process = process
            self._process_handle = getattr(process, "_handle")
            self._thread_handle = getattr(process, "_thread", None)
            self._job_handle: object | None = _kernel32.CreateJobObjectW(None, None)
            if not self._job_handle:
                raise _win_error()
            try:
                limits = _JobObjectExtendedLimitInformation()
                limits.BasicLimitInformation.LimitFlags = (
                    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                )
                if not _kernel32.SetInformationJobObject(
                    self._job_handle,
                    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits),
                ):
                    raise _win_error()
                if not _kernel32.AssignProcessToJobObject(
                    self._job_handle, self._process_handle
                ):
                    raise _win_error()
                if self._thread_handle is None:
                    raise OSError("worker thread handle unavailable")
                if _kernel32.ResumeThread(self._thread_handle) == _INVALID_DWORD:
                    raise _win_error()
            except Exception:
                job_handle = self._job_handle
                self._job_handle = None
                _cleanup_windows_created_process(
                    self._process,
                    job_handle=job_handle,
                )
                self._process_handle = None
                self._thread_handle = None
                raise

        def wait(self, deadline: float) -> int | None:
            try:
                return self._process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return None

        def confirm_termination(self) -> bool:
            if self._job_handle is None:
                return False
            accounting = _JobObjectBasicAccountingInformation()
            if not _kernel32.QueryInformationJobObject(
                self._job_handle,
                _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
                ctypes.byref(accounting),
                ctypes.sizeof(accounting),
                None,
            ):
                return False
            return accounting.ActiveProcesses == 0

        def terminate_tree(self) -> None:
            if self._job_handle is None:
                raise OSError("job handle unavailable")
            if not _kernel32.TerminateJobObject(self._job_handle, 1):
                raise _win_error()

        def wait_for_root(self, timeout_seconds: float) -> bool:
            try:
                self._process.wait(timeout=timeout_seconds)
            except (OSError, subprocess.TimeoutExpired):
                return False
            return True

        def close(self) -> None:
            _close_streams(self._process)
            failures: list[OSError] = []
            try:
                self._close_job()
            except OSError as error:
                failures.append(error)
            try:
                _close_windows_handle(self._thread_handle)
            except OSError as error:
                failures.append(error)
            finally:
                self._thread_handle = None
            try:
                _close_windows_handle(self._process_handle)
            except OSError as error:
                failures.append(error)
            finally:
                self._process_handle = None
            if failures:
                raise failures[0]

        def _close_job(self) -> None:
            if self._job_handle is None:
                return
            job_handle = self._job_handle
            self._job_handle = None
            if not _kernel32.CloseHandle(job_handle):
                raise _win_error()

else:

    class WindowsJobObjectBoundary:  # pragma: no cover - unavailable by design off Windows.
        """Import-safe placeholder; the real boundary is defined only on Windows."""

        process_created = False

        def __init__(self, process: object) -> None:
            del process
            raise OSError("Windows Job Objects are only available on Windows")


_UNSET = object()


class FakeProcessBoundary:
    """Deterministic lifecycle fake for unit tests; it never creates a subprocess."""

    def __init__(
        self,
        *,
        wait_return: int | None = 0,
        confirm: bool = True,
        confirmations: Sequence[bool] = (),
        root_wait_returns: Sequence[bool] = (),
        process: object | None = _UNSET,
        process_created: bool | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._wait_return = wait_return
        self._confirmations = list(confirmations)
        self._last_confirmation = confirm
        self._root_wait_returns = list(root_wait_returns)
        self.termination_waits: list[float] = []
        self.process = None if process is _UNSET else process
        self.process_created = (
            (process is not None if process is not _UNSET else True)
            if process_created is None
            else process_created
        )
        self.events = events if events is not None else []

    def wait(self, deadline: float) -> int | None:
        del deadline
        self.events.append("wait")
        return self._wait_return

    def confirm_termination(self) -> bool:
        self.events.append("confirm")
        if self._confirmations:
            self._last_confirmation = self._confirmations.pop(0)
        return self._last_confirmation

    def terminate_tree(self) -> None:
        self.events.append("terminate")

    def wait_for_root(self, timeout_seconds: float) -> bool:
        self.events.append("wait_root")
        self.termination_waits.append(timeout_seconds)
        if self._root_wait_returns:
            return self._root_wait_returns.pop(0)
        return True

    def close(self) -> None:
        self.events.append("close")


def create_boundary(
    command: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    shell: bool = False,
    creationflags: int = 0,
    start_new_session: bool = False,
) -> ProcessBoundary:
    """Start one explicit worker and fail-closed if boundary setup is incomplete."""
    process: object | None = None
    try:
        if shell is not False:
            raise ValueError("worker shell execution is forbidden")
        if sys.platform == "win32":
            if start_new_session:
                raise ValueError(
                    "Windows workers use a Job Object, not start_new_session"
                )
            process = _create_windows_suspended_process(
                command,
                cwd=cwd,
                env=env,
                creationflags=creationflags,
            )
            return WindowsJobObjectBoundary(process)
        process = subprocess.Popen(
            list(command),
            shell=shell,
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        return PosixProcessBoundary(process)
    except Exception:
        if process is not None:
            _cleanup_partial_start(process)
        raise


def _cleanup_partial_start(process: object) -> None:
    """Best-effort local cleanup after a factory failure; callers remain fail-closed."""
    if sys.platform == "win32":
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=5.0)
        except Exception:
            pass
        _close_streams(process)
        for name in ("_thread", "_handle"):
            try:
                _close_windows_handle(getattr(process, name, None))
            except Exception:
                pass
        return
    try:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
    _close_streams(process)


def _close_streams(process: object) -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(process, stream_name, None)
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
