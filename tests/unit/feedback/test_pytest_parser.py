from types import SimpleNamespace
from uuid import uuid4

from coding_agent_harness.adapters.process.runner import BoundedRawOutput
from coding_agent_harness.domain.enums import TestPhase as DomainTestPhase, TestRunOutcome as DomainTestRunOutcome
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome, parse_pytest


def execution(outcome=DomainTestRunOutcome.FAILED, phase=DomainTestPhase.POST_PATCH):
    return SimpleNamespace(test_run=SimpleNamespace(run_id=uuid4(), outcome=outcome, phase=phase))


def raw(text: str, truncated: bool = False) -> BoundedRawOutput:
    return BoundedRawOutput(stdout=text.encode(), stderr=b"", stdout_truncated=truncated, stderr_truncated=False)


def test_parses_pass_failure_and_collection_error_without_raw_output() -> None:
    passed = parse_pytest(raw("3 passed in 0.10s\n"), execution(DomainTestRunOutcome.PASSED))
    failed = parse_pytest(raw("FAILED tests/test_a.py::test_one - AssertionError: bad\nFAILED tests/test_b.py::test_two - ValueError: no\n2 failed in 0.10s\n"), execution())
    collection = parse_pytest(raw("ERROR collecting tests/test_bad.py\nE   SyntaxError: invalid syntax\n"), execution())
    assert passed.outcome is ParsedOutcome.PASSED
    assert failed.node_ids == ("tests/test_a.py::test_one", "tests/test_b.py::test_two")
    assert failed.outcome is ParsedOutcome.FAILED and failed.exception_type == "AssertionError"
    assert collection.outcome is ParsedOutcome.COLLECTION_ERROR
    assert not hasattr(failed, "raw_output")


def test_never_guesses_pass_for_unparseable_or_truncated_output() -> None:
    assert parse_pytest(raw("unrecognized text"), execution(DomainTestRunOutcome.UNPARSEABLE)).outcome is ParsedOutcome.UNPARSEABLE
    assert parse_pytest(raw("1 passed in 0.1s", truncated=True), execution(DomainTestRunOutcome.PASSED)).outcome is ParsedOutcome.UNPARSEABLE


def test_environment_outcomes_are_classified_without_exposing_exception_text() -> None:
    result = parse_pytest(raw("secret interpreter failure"), execution(DomainTestRunOutcome.ENVIRONMENT_ERROR))
    assert result.outcome is ParsedOutcome.ENVIRONMENT_ERROR
    assert "secret" not in result.summary
