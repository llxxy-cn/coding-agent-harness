from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM
from coding_agent_harness.application.service import ApplicationService
from coding_agent_harness.core.context import ContextBuilder
from coding_agent_harness.core.harness import ActionExecution, CoreSession, HarnessCore, InMemorySessionStore
from coding_agent_harness.domain.actions import ApplyPatchAction, parse_action
from coding_agent_harness.domain.enums import TaskStatus, TestRunOutcome as DomainTestRunOutcome
from coding_agent_harness.feedback.engine import FeedbackEngine
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome
from coding_agent_harness.patching.models import PatchSnapshot
from coding_agent_harness.patching.parser import prepare

from tests.unit.core.test_harness import (
    AllowPolicy,
    DefaultPatchSafetyResolver,
    Executor,
    FullTests,
    TASK_ID,
    make_test_run,
    parsed,
)

_RAW_A = '{"type":"apply_patch","diff":"--- a/counter.py\\n+++ b/counter.py\\n@@ -1 +1 @@\\n-return 0\\n+return 1\\n"}'
_RAW_B = '{"type":"apply_patch","diff":"--- a/counter.py\\n+++ b/counter.py\\n@@ -1 +1 @@\\n-return 1\\n+return 2\\n"}'

_EXPECTED_A = parse_action(_RAW_A)
_EXPECTED_B = parse_action(_RAW_B)


class _SequentialPatchPreparer:
    def __init__(self):
        self._snapshots = (
            PatchSnapshot({"counter.py": b"return 0\n"}),
            PatchSnapshot({"counter.py": b"return 1\n"}),
        )
        self._index = 0

    def prepare(self, action):
        snapshot = self._snapshots[self._index]
        self._index += 1
        return prepare(action.diff, snapshot)


def test_feedback_driven_action_change_succeeds() -> None:
    assert isinstance(_EXPECTED_A, ApplyPatchAction)
    assert isinstance(_EXPECTED_B, ApplyPatchAction)

    executor = Executor([
        ActionExecution(safe_summary="patch A applied", source_revision="b"),
        ActionExecution(safe_summary="patch B applied", source_revision="c"),
    ])
    full = FullTests([
        ActionExecution(
            safe_summary="tests failed",
            source_revision="b",
            test_run=make_test_run(DomainTestRunOutcome.FAILED),
            parsed_result=parsed(ParsedOutcome.FAILED, ("tests/test_counter.py::test_counter",), "b"),
        ),
        ActionExecution(
            safe_summary="tests passed",
            source_revision="c",
            test_run=make_test_run(DomainTestRunOutcome.PASSED),
            parsed_result=parsed(ParsedOutcome.PASSED, (), "c"),
        ),
    ])
    store = InMemorySessionStore()
    store.save(CoreSession(
        task_id=TASK_ID,
        user_task="fix counter",
        config_summary="demo",
        workspace_summary="one test fails",
    ))
    harness = HarnessCore(
        llm=ScriptedMockLLM([_RAW_A, _RAW_B]),
        session_store=store,
        context_builder=ContextBuilder(),
        policy_engine=AllowPolicy(),
        action_executor=executor,
        full_test_runner=full,
        feedback_engine=FeedbackEngine(),
        patch_preparer=_SequentialPatchPreparer(),
        patch_safety_resolver=DefaultPatchSafetyResolver(),
        max_actions=6,
        max_feedback=4,
    )
    outcome = ApplicationService(harness).run_task(TASK_ID)

    assert outcome.status is TaskStatus.SUCCEEDED
    assert tuple(action.diff for action in executor.actions) == (_EXPECTED_A.diff, _EXPECTED_B.diff)
    assert len(harness.llm.contexts) == 2
    assert harness.llm.contexts[0].feedback_summary is None
    assert harness.llm.contexts[1].feedback_summary == "failed"
    assert full.calls == 2
