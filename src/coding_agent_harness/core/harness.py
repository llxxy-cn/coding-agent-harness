from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from coding_agent_harness.core.context import ContextBuilder, ContextSnapshot, SafeHistoryEntry
from coding_agent_harness.core.patch_policy import policy_facts_from_prepared
from coding_agent_harness.domain.actions import ApplyPatchAction, RequestHumanAction, RunTestsAction, parse_action
from coding_agent_harness.domain.enums import FeedbackKind, PolicyOutcome, TaskStatus, TestPhase, TestRunOutcome
from coding_agent_harness.domain.models import ProtocolError, TaskId, TestRun
from coding_agent_harness.feedback.pytest_parser import ParsedTestResult
from coding_agent_harness.security.policy import PolicyFacts


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


class ActionExecution(_FrozenModel):
    safe_summary: StrictStr
    source_revision: StrictStr
    test_run: TestRun | None = None
    parsed_result: ParsedTestResult | None = None
    unknown_outcome: StrictBool = False


class CoreSession(_FrozenModel):
    task_id: TaskId
    user_task: StrictStr
    config_summary: StrictStr
    workspace_summary: StrictStr
    status: TaskStatus = TaskStatus.DECIDING
    history: tuple[SafeHistoryEntry, ...] = ()
    previous_result: ParsedTestResult | None = None
    result_history: tuple[ParsedTestResult, ...] = ()
    feedback_summary: StrictStr | None = None
    action_count: StrictInt = 0
    feedback_count: StrictInt = 0


class CoreOutcome(_FrozenModel):
    status: TaskStatus
    action_count: StrictInt
    feedback_count: StrictInt
    reason: StrictStr


class SessionStore(Protocol):
    def load(self, task_id: TaskId) -> CoreSession: ...
    def save(self, session: CoreSession) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions = {}

    def load(self, task_id: TaskId) -> CoreSession:
        return self._sessions[str(task_id.value)]

    def save(self, session: CoreSession) -> None:
        self._sessions[str(session.task_id.value)] = session


class HarnessCore:
    def __init__(self, *, llm, session_store: SessionStore, context_builder: ContextBuilder, policy_engine, action_executor, full_test_runner, feedback_engine, patch_preparer=None, patch_safety_resolver=None, max_actions: int = 40, max_feedback: int = 8) -> None:
        self.llm = llm
        self.session_store = session_store
        self.context_builder = context_builder
        self.policy_engine = policy_engine
        self.action_executor = action_executor
        self.full_test_runner = full_test_runner
        self.feedback_engine = feedback_engine
        self.patch_preparer = patch_preparer
        self.patch_safety_resolver = patch_safety_resolver
        self.max_actions = max_actions
        self.max_feedback = max_feedback

    def run(self, task_id: TaskId) -> CoreOutcome:
        while True:
            outcome = self.step(task_id)
            if outcome.status is not TaskStatus.DECIDING:
                return outcome

    def step(self, task_id: TaskId) -> CoreOutcome:
        session = self.session_store.load(task_id)
        if session.status is not TaskStatus.DECIDING:
            return self._outcome(session, "not_deciding")
        if session.action_count >= self.max_actions or session.feedback_count >= self.max_feedback:
            return self._save(session.model_copy(update={"status": TaskStatus.STOPPED}), "budget_exhausted")
        context = self.context_builder.build(ContextSnapshot(
            user_task=session.user_task, config_summary=session.config_summary,
            action_schema=("list_files", "read_file", "search_code", "apply_patch", "run_tests", "git_diff", "git_status", "request_human"),
            workspace_summary=session.workspace_summary, history=session.history,
            feedback_summary=session.feedback_summary,
            remaining_actions=self.max_actions - session.action_count,
            remaining_feedback=self.max_feedback - session.feedback_count,
        ))
        raw = self.llm.generate(context)
        session = session.model_copy(update={"action_count": session.action_count + 1})
        action = parse_action(raw)
        if isinstance(action, ProtocolError):
            session = self._append(session, "protocol_error", action.sanitized_message)
            if session.action_count >= self.max_actions:
                session = session.model_copy(update={"status": TaskStatus.STOPPED})
                return self._save(session, "budget_exhausted")
            self.session_store.save(session)
            return self._outcome(session, "protocol_error")
        if isinstance(action, RequestHumanAction):
            session = self._append(session, "request_human", "human review requested").model_copy(update={"status": TaskStatus.PAUSED_FOR_HUMAN})
            return self._save(session, "request_human")
        prepared = None
        if isinstance(action, ApplyPatchAction):
            if self.patch_preparer is None or self.patch_safety_resolver is None:
                session = self._append(session, "patch_prepare_failed", "patch preparation is unavailable")
                self.session_store.save(session)
                return self._outcome(session, "patch_prepare_failed")
            try:
                prepared = self.patch_preparer.prepare(action)
                safety = self.patch_safety_resolver.resolve(prepared)
                policy_facts = policy_facts_from_prepared(action, prepared, safety)
            except (TypeError, ValueError):
                session = self._append(session, "patch_prepare_failed", "patch preparation failed")
                self.session_store.save(session)
                return self._outcome(session, "patch_prepare_failed")
        else:
            policy_facts = PolicyFacts()
        decision = self.policy_engine.evaluate(action, policy_facts, None, None)
        if decision.outcome is PolicyOutcome.DENY:
            session = self._append(session, "policy_deny", decision.reason_code.value)
            if session.action_count >= self.max_actions:
                session = session.model_copy(update={"status": TaskStatus.STOPPED})
                return self._save(session, "budget_exhausted")
            self.session_store.save(session)
            return self._outcome(session, "policy_deny")
        if decision.outcome is PolicyOutcome.REQUIRE_APPROVAL:
            session = session.model_copy(update={"status": TaskStatus.AWAITING_APPROVAL})
            return self._save(session, "approval_required")
        execution = self.action_executor.execute_patch(action, prepared) if isinstance(action, ApplyPatchAction) else self.action_executor.execute(action)
        if execution.unknown_outcome:
            session = session.model_copy(update={"status": TaskStatus.PAUSED_FOR_HUMAN})
            return self._save(session, "unknown_outcome")
        session = self._append(session, action.type, execution.safe_summary)
        if isinstance(action, ApplyPatchAction):
            execution = self.full_test_runner.run()
            session = self._append(session, "full_test", execution.safe_summary)
        if execution.test_run is None:
            self.session_store.save(session)
            return self._outcome(session, "continue")
        run = execution.test_run
        if run.outcome is TestRunOutcome.WORKSPACE_DRIFT:
            session = session.model_copy(update={"status": TaskStatus.PAUSED_FOR_HUMAN})
            return self._save(session, "workspace_drift")
        if execution.parsed_result is None:
            session = session.model_copy(update={"status": TaskStatus.PAUSED_FOR_HUMAN})
            return self._save(session, run.outcome.value)
        current = execution.parsed_result.model_copy(update={"source_revision": execution.source_revision})
        if session.previous_result is None and current.outcome.value != "passed":
            session = session.model_copy(update={"previous_result": current, "result_history": session.result_history + (current,), "feedback_summary": current.summary, "feedback_count": session.feedback_count + 1})
            return self._feedback_gate(session, run.phase, None)
        feedback = self.feedback_engine.analyze(session.previous_result, current, history=session.result_history)
        session = session.model_copy(update={"previous_result": current, "result_history": session.result_history + (current,), "feedback_summary": feedback.sanitized_summary, "feedback_count": session.feedback_count + 1})
        return self._feedback_gate(session, run.phase, feedback.kind)

    def _feedback_gate(self, session: CoreSession, phase: TestPhase, kind: FeedbackKind | None) -> CoreOutcome:
        if kind is FeedbackKind.PASSED and phase is not TestPhase.FOCUSED:
            return self._save(session.model_copy(update={"status": TaskStatus.SUCCEEDED}), "tests_passed")
        if kind is FeedbackKind.LOOP:
            return self._save(session.model_copy(update={"status": TaskStatus.STOPPED}), "loop")
        if kind is FeedbackKind.NO_PROGRESS:
            return self._save(session.model_copy(update={"status": TaskStatus.STOPPED}), "no_progress")
        if kind in {FeedbackKind.ENVIRONMENT_ERROR, FeedbackKind.UNPARSEABLE}:
            return self._save(session.model_copy(update={"status": TaskStatus.PAUSED_FOR_HUMAN}), kind.value)
        if session.feedback_count >= self.max_feedback:
            return self._save(session.model_copy(update={"status": TaskStatus.STOPPED}), "budget_exhausted")
        self.session_store.save(session)
        return self._outcome(session, "feedback")

    @staticmethod
    def _append(session: CoreSession, action_type: str, summary: str) -> CoreSession:
        return session.model_copy(update={"history": session.history + (SafeHistoryEntry(action_type=action_type, safe_result=summary),)})

    def _save(self, session: CoreSession, reason: str) -> CoreOutcome:
        self.session_store.save(session)
        return self._outcome(session, reason)

    @staticmethod
    def _outcome(session: CoreSession, reason: str) -> CoreOutcome:
        return CoreOutcome(status=session.status, action_count=session.action_count, feedback_count=session.feedback_count, reason=reason)
