from __future__ import annotations

import pytest

from coding_agent_harness.feedback.output import SanitizedTestOutput
from coding_agent_harness.security.redaction import redact_fields, redact_text


def test_redacts_credentials_environment_assignments_paths_and_nested_fields() -> None:
    text = "OPENAI_API_KEY=sk-secret token=abc123 C:\\Users\\alice\\repo\\test.py /home/alice/repo/test.py"
    redacted = redact_text(text, secrets=("abc123", "sk-secret"))
    assert "abc123" not in redacted and "sk-secret" not in redacted
    assert "C:\\Users\\alice" not in redacted and "/home/alice" not in redacted
    nested = redact_fields({"token": "visible", "nested": [{"exception": text}]}, secrets=("visible", "abc123", "sk-secret"))
    assert nested == {"token": "[REDACTED]", "nested": [{"exception": "[REDACTED]"}]}


def test_sanitized_output_is_strict_frozen_bounded_and_utf8_safe() -> None:
    output = SanitizedTestOutput(stdout="ok", stderr="", stdout_truncated=False, stderr_truncated=False)
    with pytest.raises(Exception):
        output.stdout = "changed"
    with pytest.raises(Exception):
        SanitizedTestOutput(stdout="ok", stderr="", stdout_truncated=False, stderr_truncated=False, extra=True)
    with pytest.raises(Exception):
        SanitizedTestOutput(stdout="\ud800", stderr="", stdout_truncated=False, stderr_truncated=False)
    with pytest.raises(Exception):
        SanitizedTestOutput(stdout="x" * 1_048_577, stderr="", stdout_truncated=False, stderr_truncated=False)
