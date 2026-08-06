from __future__ import annotations

from coding_agent_harness.domain.enums import FeedbackKind
from coding_agent_harness.domain.models import FeedbackDecision
from coding_agent_harness.feedback.fingerprint import state_fingerprint
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome, ParsedTestResult


class FeedbackEngine:
    def fingerprint(self, result: ParsedTestResult) -> str:
        return state_fingerprint(result)

    def analyze(self, previous: ParsedTestResult | None, current: ParsedTestResult, *, history: tuple[ParsedTestResult, ...]) -> FeedbackDecision:
        fingerprint = self.fingerprint(current)
        if current.outcome is ParsedOutcome.ENVIRONMENT_ERROR:
            return FeedbackDecision(kind=FeedbackKind.ENVIRONMENT_ERROR, current_run_id=current.run_id, previous_run_id=None, matched_history_run_id=None, state_fingerprint_sha256=None, sanitized_summary=current.summary)
        if current.outcome is ParsedOutcome.UNPARSEABLE:
            return FeedbackDecision(kind=FeedbackKind.UNPARSEABLE, current_run_id=current.run_id, previous_run_id=None, matched_history_run_id=None, state_fingerprint_sha256=None, sanitized_summary=current.summary)
        if current.outcome is ParsedOutcome.PASSED:
            return FeedbackDecision(kind=FeedbackKind.PASSED, current_run_id=current.run_id, previous_run_id=previous.run_id if previous else None, matched_history_run_id=None, state_fingerprint_sha256=fingerprint, sanitized_summary=current.summary)
        if previous is None:
            raise ValueError("comparison feedback requires a previous result")
        for candidate in history[:-1]:
            if self.fingerprint(candidate) == fingerprint:
                return FeedbackDecision(kind=FeedbackKind.LOOP, current_run_id=current.run_id, previous_run_id=previous.run_id, matched_history_run_id=candidate.run_id, state_fingerprint_sha256=fingerprint, sanitized_summary=current.summary)
        previous_nodes, current_nodes = set(previous.node_ids), set(current.node_ids)
        if previous.outcome is ParsedOutcome.COLLECTION_ERROR and current.outcome is not ParsedOutcome.COLLECTION_ERROR:
            kind = FeedbackKind.PROGRESS
        elif current_nodes < previous_nodes:
            kind = FeedbackKind.PROGRESS
        elif current_nodes - previous_nodes:
            kind = FeedbackKind.REGRESSION
        elif self.fingerprint(previous) == fingerprint and current.source_revision == previous.source_revision:
            kind = FeedbackKind.NO_PROGRESS
        else:
            kind = FeedbackKind.CHANGED
        return FeedbackDecision(kind=kind, current_run_id=current.run_id, previous_run_id=previous.run_id, matched_history_run_id=None, state_fingerprint_sha256=fingerprint, sanitized_summary=current.summary)
