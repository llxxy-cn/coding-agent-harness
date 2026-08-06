from uuid import uuid4

import pytest

from coding_agent_harness.domain.enums import FeedbackKind, TestPhase as DomainTestPhase
from coding_agent_harness.feedback.engine import FeedbackEngine
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome, ParsedTestResult


def result(outcome, nodes=(), summary="result", source="a"):
    return ParsedTestResult(run_id=uuid4(), phase=DomainTestPhase.POST_PATCH, outcome=outcome, node_ids=nodes, exception_type=None, summary=summary, in_project_frames=(), truncated=False, source_revision=source)


@pytest.mark.parametrize(
    ("previous", "current", "kind"),
    [
        (result(ParsedOutcome.FAILED, ("a", "b")), result(ParsedOutcome.FAILED, ("a",)), FeedbackKind.PROGRESS),
        (result(ParsedOutcome.FAILED, ("a",)), result(ParsedOutcome.FAILED, ("a", "b")), FeedbackKind.REGRESSION),
        (result(ParsedOutcome.FAILED, ("a",)), result(ParsedOutcome.FAILED, ("a",)), FeedbackKind.NO_PROGRESS),
        (result(ParsedOutcome.FAILED, ("a",), source="a"), result(ParsedOutcome.FAILED, ("a",), source="b"), FeedbackKind.CHANGED),
        (result(ParsedOutcome.COLLECTION_ERROR), result(ParsedOutcome.FAILED, ("a",)), FeedbackKind.PROGRESS),
    ],
)
def test_feedback_decision_table(previous, current, kind) -> None:
    assert FeedbackEngine().analyze(previous, current, history=()).kind is kind


def test_feedback_handles_pass_environment_unparseable_and_loop() -> None:
    engine = FeedbackEngine()
    previous = result(ParsedOutcome.FAILED, ("a",), summary="A")
    passed = result(ParsedOutcome.PASSED)
    environment = result(ParsedOutcome.ENVIRONMENT_ERROR)
    unparseable = result(ParsedOutcome.UNPARSEABLE)
    middle = result(ParsedOutcome.FAILED, ("b",), summary="B")
    looped = result(ParsedOutcome.FAILED, ("a",), summary="A")
    assert engine.analyze(previous, passed, history=()).kind is FeedbackKind.PASSED
    assert engine.analyze(None, environment, history=()).kind is FeedbackKind.ENVIRONMENT_ERROR
    assert engine.analyze(None, unparseable, history=()).kind is FeedbackKind.UNPARSEABLE
    assert engine.analyze(middle, looped, history=(previous, middle)).kind is FeedbackKind.LOOP


def test_fingerprint_is_stable_and_changes_with_state() -> None:
    first = result(ParsedOutcome.FAILED, ("b", "a"), summary="same")
    same = first.model_copy(update={"run_id": uuid4(), "node_ids": ("a", "b")})
    changed = first.model_copy(update={"run_id": uuid4(), "summary": "different"})
    engine = FeedbackEngine()
    assert engine.fingerprint(first) == engine.fingerprint(same)
    assert engine.fingerprint(first) != engine.fingerprint(changed)
