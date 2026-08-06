from coding_agent_harness.application.service import ApplicationService
from coding_agent_harness.core.harness import ActionExecution
from coding_agent_harness.domain.enums import TaskStatus, TestRunOutcome as DomainTestRunOutcome

from tests.unit.core.test_harness import Executor, FullTests, TASK_ID, core, make_test_run, parsed
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome


def test_scripted_mock_completes_deterministic_repair_loop() -> None:
    executor = Executor([ActionExecution(safe_summary="inspected counter", source_revision="a"), ActionExecution(safe_summary="patch applied", source_revision="b")])
    full = FullTests([ActionExecution(safe_summary="all tests passed", source_revision="b", test_run=make_test_run(DomainTestRunOutcome.PASSED), parsed_result=parsed(ParsedOutcome.PASSED, (), "b"))])
    harness, _ = core(['{"type":"read_file","path":"counter.py"}', '{"type":"apply_patch","diff":"--- a/counter.py\\n+++ b/counter.py\\n@@ -1 +1 @@\\n-return 0\\n+return 1\\n"}'], executor=executor, full=full)
    outcome = ApplicationService(harness).run_task(TASK_ID)
    assert outcome.status is TaskStatus.SUCCEEDED
    assert harness.llm.contexts[1].history[-1].safe_result == "inspected counter"
    assert full.calls == 1
