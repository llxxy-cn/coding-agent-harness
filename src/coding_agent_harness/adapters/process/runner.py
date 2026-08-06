from __future__ import annotations

import os
import signal
import subprocess
import threading
from enum import Enum, unique
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictBytes, StrictInt, StrictStr, field_validator, model_validator


MAX_OUTPUT_BYTES = 1_048_576


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class BoundedRawOutput(_FrozenModel):
    stdout: StrictBytes
    stderr: StrictBytes
    stdout_truncated: StrictBool
    stderr_truncated: StrictBool

    @field_validator("stdout", "stderr")
    @classmethod
    def bounded_stream(cls, value: bytes) -> bytes:
        if len(value) > MAX_OUTPUT_BYTES:
            raise ValueError("raw stream exceeds capture limit")
        return value


class SanitizedTestOutput(_FrozenModel):
    stdout: StrictStr
    stderr: StrictStr
    stdout_truncated: StrictBool
    stderr_truncated: StrictBool

    @field_validator("stdout", "stderr")
    @classmethod
    def bounded_utf8_stream(cls, value: str) -> str:
        encoded = value.encode("utf-8", errors="strict")
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise ValueError("sanitized stream exceeds output limit")
        return value


class BoundedCapture:
    def __init__(self, limit: int = MAX_OUTPUT_BYTES) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("capture limit must be a positive integer")
        self.limit = limit
        self._value = b""
        self.truncated = False

    def feed(self, chunk: bytes) -> None:
        if not isinstance(chunk, bytes):
            raise TypeError("capture chunks must be bytes")
        combined = self._value + chunk
        if len(combined) <= self.limit:
            self._value = combined
            return
        head = self.limit // 2
        tail = self.limit - head
        self._value = combined[:head] + combined[-tail:]
        self.truncated = True

    @property
    def value(self) -> bytes:
        return self._value


@unique
class LaunchStatus(str, Enum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    RESOURCE_LIMIT = "resource_limit"
    ENVIRONMENT_ERROR = "environment_error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class LaunchRequest(_FrozenModel):
    argv: tuple[StrictStr, ...]
    cwd: Path
    shell: Literal[False]
    env: dict[StrictStr, StrictStr]
    timeout_seconds: StrictInt = Field(ge=1, le=600)
    stdout_limit: StrictInt = Field(default=MAX_OUTPUT_BYTES, ge=1, le=MAX_OUTPUT_BYTES)
    stderr_limit: StrictInt = Field(default=MAX_OUTPUT_BYTES, ge=1, le=MAX_OUTPUT_BYTES)


class LaunchResult(_FrozenModel):
    status: LaunchStatus
    exit_code: StrictInt | None
    stdout: StrictBytes
    stderr: StrictBytes
    stdout_truncated: StrictBool
    stderr_truncated: StrictBool

    @model_validator(mode="after")
    def validate_status(self):
        if self.status in {LaunchStatus.TIMED_OUT, LaunchStatus.CANCELLED, LaunchStatus.UNKNOWN} and self.exit_code is not None:
            raise ValueError("launch status requires no exit code")
        if self.status is LaunchStatus.COMPLETED and self.exit_code is None:
            raise ValueError("completed launch requires exit code")
        return self

    @classmethod
    def completed(cls, exit_code: int, stdout: bytes, stderr: bytes) -> "LaunchResult":
        return cls(status=LaunchStatus.COMPLETED, exit_code=exit_code, stdout=stdout, stderr=stderr, stdout_truncated=False, stderr_truncated=False)


class SubprocessLauncher:
    """Bounded process launcher; callers provide only validated launch inputs."""

    def launch(self, request: LaunchRequest) -> LaunchResult:
        stdout_capture = BoundedCapture(request.stdout_limit)
        stderr_capture = BoundedCapture(request.stderr_limit)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                list(request.argv),
                cwd=request.cwd,
                env=request.env,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except OSError:
            return LaunchResult(status=LaunchStatus.ENVIRONMENT_ERROR, exit_code=None, stdout=b"", stderr=b"", stdout_truncated=False, stderr_truncated=False)

        def drain(stream, capture: BoundedCapture) -> None:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    return
                capture.feed(chunk)

        threads = (
            threading.Thread(target=drain, args=(process.stdout, stdout_capture), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr_capture), daemon=True),
        )
        for thread in threads:
            thread.start()
        try:
            exit_code = process.wait(timeout=request.timeout_seconds)
            status = LaunchStatus.COMPLETED
        except subprocess.TimeoutExpired:
            self._terminate_tree(process)
            exit_code = None
            status = LaunchStatus.TIMED_OUT
        for thread in threads:
            thread.join(timeout=1)
        return LaunchResult(status=status, exit_code=exit_code, stdout=stdout_capture.value, stderr=stderr_capture.value, stdout_truncated=stdout_capture.truncated, stderr_truncated=stderr_capture.truncated)

    @staticmethod
    def _terminate_tree(process: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            process.kill()
