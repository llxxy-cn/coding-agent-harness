import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM
from coding_agent_harness.core.context import ContextBuilder
from coding_agent_harness.core.harness import ActionExecution, CoreSession, HarnessCore, InMemorySessionStore
from coding_agent_harness.domain.enums import PolicyOutcome, TaskStatus, TestPhase as DomainTestPhase, TestRunOutcome as DomainTestRunOutcome
from coding_agent_harness.domain.models import ArtifactRef, FrozenCommand, TaskId, TestRun as DomainTestRun
from coding_agent_harness.feedback.engine import FeedbackEngine
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome, ParsedTestResult
from coding_agent_harness.patching.models import PatchSnapshot
from coding_agent_harness.patching.parser import prepare
from coding_agent_harness.security.policy import PolicyDecision, PolicyEngine, PolicyFacts, PolicyReasonCode


TASK_ID = TaskId(value=UUID("123e4567-e89b-42d3-a456-426614174000"))
HASH_A = "a" * 64
HASH_B = "b" * 64


def parsed(outcome=ParsedOutcome.FAILED, nodes=("tests/test_counter.py::test_counter",), source="a"):
    return ParsedTestResult(run_id=uuid4(), phase=DomainTestPhase.POST_PATCH, outcome=outcome, node_ids=nodes, exception_type="AssertionError" if nodes else None, summary=outcome.value, in_project_frames=(), truncated=False, source_revision=source)


def make_test_run(outcome, phase=DomainTestPhase.POST_PATCH, drift=False):
    output = ArtifactRef(artifact_id=uuid4(), task_id=TASK_ID, schema_id="sanitized_test_output", schema_version=1, media_type="application/json", byte_length=2, sha256=HASH_A)
    parsed_ref = None if outcome not in {DomainTestRunOutcome.PASSED, DomainTestRunOutcome.FAILED} or drift else ArtifactRef(artifact_id=uuid4(), task_id=TASK_ID, schema_id="parsed_result", schema_version=1, media_type="application/json", byte_length=2, sha256=HASH_A)
    return DomainTestRun(run_id=uuid4(), task_id=TASK_ID, phase=phase, outcome=DomainTestRunOutcome.WORKSPACE_DRIFT if drift else outcome, command=FrozenCommand(argv=["pytest", "-q"]), base_commit="a" * 40, config_sha256=HASH_A, environment_sha256=HASH_A, workspace_before_sha256=HASH_A, workspace_after_sha256=HASH_B if drift else HASH_A, started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), finished_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc), duration_ms=1000, exit_code=0 if outcome is DomainTestRunOutcome.PASSED else 1 if outcome is DomainTestRunOutcome.FAILED else None, sanitized_output_ref=output, parsed_result_ref=parsed_ref)


class AllowPolicy:
    def evaluate(self, action, facts, config, approval):
        return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason_code=PolicyReasonCode.ALLOWED)


class DenyPolicy:
    def evaluate(self, action, facts, config, approval):
        return PolicyDecision(outcome=PolicyOutcome.DENY, reason_code=PolicyReasonCode.TEST_ASSET_PROTECTION)


class Executor:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.actions = []
    def execute(self, action):
        self.actions.append(action)
        return self.results.pop(0) if self.results else ActionExecution(safe_summary="read ok", source_revision="a")
    def execute_patch(self, action, prepared):
        self.actions.append(action)
        return self.results.pop(0) if self.results else ActionExecution(safe_summary="patch applied", source_revision="b")


class FullTests:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
    def run(self):
        self.calls += 1
        return self.results.pop(0)


class DefaultPatchPreparer:
    def prepare(self, action):
        return prepare(action.diff, PatchSnapshot({"counter.py": b"return 0\n", "a.py": b"a\n"}))


@dataclass(frozen=True)
class DefaultPatchSafetyFacts:
    symlink: bool
    capability_missing: bool
    demo_escape: bool


class DefaultPatchSafetyResolver:
    def resolve(self, prepared):
        return DefaultPatchSafetyFacts(symlink=False, capability_missing=False, demo_escape=False)


def core(actions, executor=None, full=None, policy=None, max_actions=6, session=None):
    store = InMemorySessionStore()
    store.save(session or CoreSession(task_id=TASK_ID, user_task="fix counter", config_summary="demo", workspace_summary="one test fails"))
    instance = HarnessCore(llm=ScriptedMockLLM(actions), session_store=store, context_builder=ContextBuilder(), policy_engine=policy or AllowPolicy(), action_executor=executor or Executor(), full_test_runner=full or FullTests([]), feedback_engine=FeedbackEngine(), patch_preparer=DefaultPatchPreparer(), patch_safety_resolver=DefaultPatchSafetyResolver(), max_actions=max_actions, max_feedback=4)
    return instance, store


def test_invalid_json_consumes_budget_and_read_result_reaches_next_context() -> None:
    executor = Executor()
    instance, store = core(["bad-json", '{"type":"git_status"}', '{"type":"request_human","reason":"review needed"}'], executor=executor)
    outcome = instance.run(TASK_ID)
    assert outcome.status is TaskStatus.PAUSED_FOR_HUMAN and outcome.action_count == 3
    assert "protocol_error" in instance.llm.contexts[1].history[-1].action_type
    assert instance.llm.contexts[2].history[-1].safe_result == "read ok"


def test_apply_patch_forces_full_test_and_pass_succeeds() -> None:
    executor = Executor([ActionExecution(safe_summary="patch applied", source_revision="b")])
    full = FullTests([ActionExecution(safe_summary="tests passed", source_revision="b", test_run=make_test_run(DomainTestRunOutcome.PASSED), parsed_result=parsed(ParsedOutcome.PASSED, (), "b"))])
    instance, _ = core(['{"type":"apply_patch","diff":"--- a/counter.py\\n+++ b/counter.py\\n@@ -1 +1 @@\\n-return 0\\n+return 1\\n"}'], executor=executor, full=full)
    outcome = instance.run(TASK_ID)
    assert outcome.status is TaskStatus.SUCCEEDED and full.calls == 1


def test_failed_full_test_feedback_changes_next_turn_and_no_progress_stops() -> None:
    executor = Executor([ActionExecution(safe_summary="patch applied", source_revision="b"), ActionExecution(safe_summary="patch applied", source_revision="b")])
    full = FullTests([
        ActionExecution(safe_summary="tests failed", source_revision="b", test_run=make_test_run(DomainTestRunOutcome.FAILED), parsed_result=parsed(source="b")),
        ActionExecution(safe_summary="tests failed", source_revision="b", test_run=make_test_run(DomainTestRunOutcome.FAILED), parsed_result=parsed(source="b")),
    ])
    actions = ['{"type":"apply_patch","diff":"--- a/a.py\\n+++ b/a.py\\n@@ -1 +1 @@\\n-a\\n+b\\n"}'] * 2
    instance, _ = core(actions, executor=executor, full=full)
    outcome = instance.run(TASK_ID)
    assert instance.llm.contexts[1].feedback_summary is not None
    assert outcome.status is TaskStatus.STOPPED and outcome.reason == "no_progress"


def test_focused_pass_cannot_succeed_workspace_drift_and_unknown_pause() -> None:
    focused = Executor([ActionExecution(safe_summary="focused", source_revision="a", test_run=make_test_run(DomainTestRunOutcome.PASSED, DomainTestPhase.FOCUSED), parsed_result=parsed(ParsedOutcome.PASSED, ()))])
    instance, _ = core(['{"type":"run_tests","scope":"focused","targets":["tests/test_counter.py"]}', '{"type":"request_human","reason":"done checking"}'], executor=focused)
    assert instance.run(TASK_ID).status is TaskStatus.PAUSED_FOR_HUMAN
    drift_executor = Executor([ActionExecution(safe_summary="drift", source_revision="b", test_run=make_test_run(DomainTestRunOutcome.PASSED, drift=True))])
    drift_core, _ = core(['{"type":"run_tests","scope":"full","targets":[]}'], executor=drift_executor)
    assert drift_core.run(TASK_ID).reason == "workspace_drift"
    unknown_core, _ = core(['{"type":"git_status"}'], executor=Executor([ActionExecution(safe_summary="unknown", source_revision="a", unknown_outcome=True)]))
    assert unknown_core.run(TASK_ID).reason == "unknown_outcome" and len(unknown_core.action_executor.actions) == 1


def test_policy_deny_does_not_call_handler_and_budget_stops_before_extra_llm_call() -> None:
    executor = Executor()
    instance, _ = core(['{"type":"git_status"}', '{"type":"git_status"}'], executor=executor, policy=DenyPolicy(), max_actions=1)
    outcome = instance.run(TASK_ID)
    assert outcome.status is TaskStatus.STOPPED and executor.actions == []
    assert len(instance.llm.contexts) == 1


def test_prepared_small_source_patch_allows_one_apply_and_forces_full_test() -> None:
    class PrepareSpy:
        calls = 0
        def prepare(self, action):
            self.calls += 1
            return prepare(action.diff, PatchSnapshot({"counter.py": b"return 0\n"}))

    class PolicySpy:
        def __init__(self):
            self.facts = []
            self.decisions = []
        def evaluate(self, action, facts, config, approval):
            assert isinstance(facts, PolicyFacts)
            self.facts.append(facts)
            decision = PolicyEngine().evaluate(action, facts, config, approval)
            self.decisions.append(decision)
            return decision

    class PatchExecutor(Executor):
        def __init__(self):
            super().__init__()
            self.patch_calls = []
        def execute_patch(self, action, prepared):
            self.patch_calls.append(prepared)
            return ActionExecution(safe_summary="patch applied", source_revision="b")

    @dataclass(frozen=True)
    class SafetyFacts:
        symlink: bool
        capability_missing: bool
        demo_escape: bool

    class SafetyResolver:
        def resolve(self, prepared):
            return SafetyFacts(symlink=False, capability_missing=False, demo_escape=False)

    store = InMemorySessionStore()
    store.save(CoreSession(task_id=TASK_ID, user_task="fix counter", config_summary="demo", workspace_summary="one test fails"))
    policy = PolicySpy()
    executor = PatchExecutor()
    full = FullTests([ActionExecution(safe_summary="tests passed", source_revision="b", test_run=make_test_run(DomainTestRunOutcome.PASSED), parsed_result=parsed(ParsedOutcome.PASSED, (), "b"))])
    harness = HarnessCore(llm=ScriptedMockLLM(['{"type":"apply_patch","diff":"--- a/counter.py\\n+++ b/counter.py\\n@@ -1 +1 @@\\n-return 0\\n+return 1\\n"}']), session_store=store, context_builder=ContextBuilder(), policy_engine=policy, action_executor=executor, full_test_runner=full, feedback_engine=FeedbackEngine(), patch_preparer=PrepareSpy(), patch_safety_resolver=SafetyResolver())
    outcome = harness.run(TASK_ID)
    assert outcome.status is TaskStatus.SUCCEEDED
    assert policy.decisions[0].outcome is PolicyOutcome.ALLOW
    assert policy.facts[0].file_count == 1 and policy.facts[0].changed_lines == 2 and policy.facts[0].payload_bytes > 0
    assert len(executor.patch_calls) == 1 and full.calls == 1


def test_prepared_test_asset_patch_is_denied_without_apply_or_full_test() -> None:
    class PrepareSpy:
        def prepare(self, action):
            return prepare(action.diff, PatchSnapshot({"tests/test_a.py": b"a\n"}))

    class PolicySpy:
        def __init__(self):
            self.facts = []
            self.decisions = []
        def evaluate(self, action, facts, config, approval):
            assert isinstance(facts, PolicyFacts)
            self.facts.append(facts)
            decision = PolicyEngine().evaluate(action, facts, config, approval)
            self.decisions.append(decision)
            return decision

    class PatchExecutor(Executor):
        def __init__(self):
            super().__init__()
            self.patch_calls = []
        def execute_patch(self, action, prepared):
            self.patch_calls.append(prepared)
            return ActionExecution(safe_summary="unexpected", source_revision="b")

    @dataclass(frozen=True)
    class SafetyFacts:
        symlink: bool
        capability_missing: bool
        demo_escape: bool

    class SafetyResolver:
        def resolve(self, prepared):
            return SafetyFacts(symlink=False, capability_missing=False, demo_escape=False)

    store = InMemorySessionStore()
    store.save(CoreSession(task_id=TASK_ID, user_task="fix", config_summary="demo", workspace_summary="safe"))
    policy = PolicySpy()
    executor = PatchExecutor()
    full = FullTests([])
    diff = "--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1 +1 @@\n-a\n+b\n"
    harness = HarnessCore(llm=ScriptedMockLLM([json.dumps({"type": "apply_patch", "diff": diff})]), session_store=store, context_builder=ContextBuilder(), policy_engine=policy, action_executor=executor, full_test_runner=full, feedback_engine=FeedbackEngine(), patch_preparer=PrepareSpy(), patch_safety_resolver=SafetyResolver(), max_actions=1)
    outcome = harness.run(TASK_ID)
    assert outcome.status is TaskStatus.STOPPED
    assert policy.facts[0].touches_test_assets is True
    assert policy.decisions[0].outcome is PolicyOutcome.DENY
    assert policy.decisions[0].reason_code is PolicyReasonCode.TEST_ASSET_PROTECTION
    assert executor.patch_calls == [] and full.calls == 0


def test_prepared_six_file_patch_waits_for_approval_without_apply() -> None:
    paths = tuple(f"src/file_{index}.py" for index in range(6))
    diff = "".join(f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n" for path in paths)

    class PrepareSpy:
        def prepare(self, action):
            return prepare(action.diff, PatchSnapshot({path: b"a\n" for path in paths}))

    class PolicySpy:
        def __init__(self):
            self.facts = []
            self.decisions = []
        def evaluate(self, action, facts, config, approval):
            assert isinstance(facts, PolicyFacts)
            self.facts.append(facts)
            decision = PolicyEngine().evaluate(action, facts, config, approval)
            self.decisions.append(decision)
            return decision

    class PatchExecutor(Executor):
        def __init__(self):
            super().__init__()
            self.patch_calls = []
        def execute_patch(self, action, prepared):
            self.patch_calls.append(prepared)
            return ActionExecution(safe_summary="unexpected", source_revision="b")

    @dataclass(frozen=True)
    class SafetyFacts:
        symlink: bool
        capability_missing: bool
        demo_escape: bool

    class SafetyResolver:
        def resolve(self, prepared):
            return SafetyFacts(symlink=False, capability_missing=False, demo_escape=False)

    store = InMemorySessionStore()
    store.save(CoreSession(task_id=TASK_ID, user_task="fix", config_summary="demo", workspace_summary="safe"))
    policy = PolicySpy()
    executor = PatchExecutor()
    full = FullTests([])
    harness = HarnessCore(llm=ScriptedMockLLM([json.dumps({"type": "apply_patch", "diff": diff})]), session_store=store, context_builder=ContextBuilder(), policy_engine=policy, action_executor=executor, full_test_runner=full, feedback_engine=FeedbackEngine(), patch_preparer=PrepareSpy(), patch_safety_resolver=SafetyResolver())
    outcome = harness.run(TASK_ID)
    assert outcome.status is TaskStatus.AWAITING_APPROVAL
    assert policy.facts[0].file_count == 6
    assert policy.decisions[0].outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert policy.decisions[0].reason_code is PolicyReasonCode.PATCH_REQUIRES_APPROVAL
    assert executor.patch_calls == [] and full.calls == 0
