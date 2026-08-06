from __future__ import annotations

import re

from coding_agent_harness.adapters.process.runner import BoundedRawOutput, SanitizedTestOutput


_SENSITIVE_KEY = re.compile(r"(?:credential|password|passwd|secret|token|api[_-]?key|exception|traceback|environment|env)", re.IGNORECASE)
_ENV_ASSIGNMENT = re.compile(r"(?i)\b[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*=[^\s]+")
_WINDOWS_PATH = re.compile(r"(?i)(?:[A-Z]:\\|\\\\)[^\s\"']+")
_POSIX_PATH = re.compile(r"(?<![\w.])/(?:[^\s/]+/)+[^\s\"']+")


def redact_text(value: str, *, secrets: tuple[str, ...] = ()) -> str:
    redacted = value
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _ENV_ASSIGNMENT.sub("[REDACTED]", redacted)
    redacted = _WINDOWS_PATH.sub("[PATH]", redacted)
    redacted = _POSIX_PATH.sub("[PATH]", redacted)
    return redacted


def redact_fields(value, *, secrets: tuple[str, ...] = ()):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_fields(item, secrets=secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_fields(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_fields(item, secrets=secrets) for item in value)
    if isinstance(value, str):
        return redact_text(value, secrets=secrets)
    return value


def sanitize_output(raw: BoundedRawOutput, *, secrets: tuple[str, ...] = ()) -> SanitizedTestOutput:
    return SanitizedTestOutput(
        stdout=redact_text(raw.stdout.decode("utf-8", errors="replace"), secrets=secrets),
        stderr=redact_text(raw.stderr.decode("utf-8", errors="replace"), secrets=secrets),
        stdout_truncated=raw.stdout_truncated,
        stderr_truncated=raw.stderr_truncated,
    )
