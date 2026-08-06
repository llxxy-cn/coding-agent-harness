from __future__ import annotations

import re
from enum import Enum, unique
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, field_validator

from coding_agent_harness.adapters.process.runner import BoundedRawOutput
from coding_agent_harness.domain.enums import TestPhase, TestRunOutcome
from coding_agent_harness.feedback.normalize import normalize_summary
from coding_agent_harness.security.redaction import redact_text


@unique
class ParsedOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    COLLECTION_ERROR = "collection_error"
    ENVIRONMENT_ERROR = "environment_error"
    UNPARSEABLE = "unparseable"


class ParsedTestResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)

    run_id: UUID
    phase: TestPhase
    outcome: ParsedOutcome
    node_ids: tuple[StrictStr, ...]
    exception_type: StrictStr | None
    summary: StrictStr
    in_project_frames: tuple[StrictStr, ...]
    truncated: StrictBool
    source_revision: StrictStr = "unknown"

    @field_validator("summary")
    @classmethod
    def safe_summary(cls, value: str) -> str:
        encoded = value.encode("utf-8", errors="strict")
        if not value or value != value.strip() or any(char in value for char in "\r\n") or len(encoded) > 8192:
            raise ValueError("summary is not bounded safe text")
        return value


class SanitizedParsedTestResult(ParsedTestResult):
    pass


_FAILED = re.compile(r"(?m)^FAILED\s+([^\s]+)(?:\s+-\s+(.+))?$")
_EXCEPTION = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b")
_FRAME = re.compile(r"(?m)^([^\s:]+\.py):\d+")


def parse_pytest(raw: BoundedRawOutput, execution) -> ParsedTestResult:
    run = execution.test_run
    truncated = raw.stdout_truncated or raw.stderr_truncated
    text = (raw.stdout + b"\n" + raw.stderr).decode("utf-8", errors="replace")
    if run.outcome in {TestRunOutcome.ENVIRONMENT_ERROR, TestRunOutcome.TIMED_OUT, TestRunOutcome.RESOURCE_LIMIT, TestRunOutcome.CANCELLED, TestRunOutcome.UNKNOWN_OUTCOME}:
        return ParsedTestResult(run_id=run.run_id, phase=run.phase, outcome=ParsedOutcome.ENVIRONMENT_ERROR, node_ids=(), exception_type=None, summary="pytest environment unavailable", in_project_frames=(), truncated=truncated)
    if truncated or run.outcome is TestRunOutcome.UNPARSEABLE:
        return ParsedTestResult(run_id=run.run_id, phase=run.phase, outcome=ParsedOutcome.UNPARSEABLE, node_ids=(), exception_type=None, summary="pytest output was not reliably parseable", in_project_frames=(), truncated=truncated)
    failures = _FAILED.findall(text)
    if failures:
        nodes = tuple(sorted({node for node, _ in failures}))
        detail = next((detail for _, detail in failures if detail), "pytest failure")
        exception = _EXCEPTION.search(detail)
        frames = tuple(sorted(set(_FRAME.findall(text))))[:20]
        return ParsedTestResult(run_id=run.run_id, phase=run.phase, outcome=ParsedOutcome.FAILED, node_ids=nodes, exception_type=exception.group(1) if exception else None, summary=normalize_summary(detail), in_project_frames=frames, truncated=False)
    if "ERROR collecting" in text or "SyntaxError:" in text:
        exception = _EXCEPTION.search(text)
        return ParsedTestResult(run_id=run.run_id, phase=run.phase, outcome=ParsedOutcome.COLLECTION_ERROR, node_ids=(), exception_type=exception.group(1) if exception else None, summary="pytest collection failed", in_project_frames=(), truncated=False)
    if run.outcome is TestRunOutcome.PASSED and re.search(r"\b\d+ passed\b", text):
        return ParsedTestResult(run_id=run.run_id, phase=run.phase, outcome=ParsedOutcome.PASSED, node_ids=(), exception_type=None, summary="pytest passed", in_project_frames=(), truncated=False)
    return ParsedTestResult(run_id=run.run_id, phase=run.phase, outcome=ParsedOutcome.UNPARSEABLE, node_ids=(), exception_type=None, summary="pytest output was not reliably parseable", in_project_frames=(), truncated=False)


def redact_parsed_result(result: ParsedTestResult, *, secrets: tuple[str, ...] = ()) -> SanitizedParsedTestResult:
    return SanitizedParsedTestResult(**(result.model_dump() | {
        "summary": redact_text(result.summary, secrets=secrets),
        "in_project_frames": tuple(redact_text(frame, secrets=secrets) for frame in result.in_project_frames),
    }))
