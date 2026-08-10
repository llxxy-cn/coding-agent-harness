from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import (
    TaskStatus,
    TestPhase as _TestPhase,
    TestRunOutcome as _TestRunOutcome,
)
from coding_agent_harness.web.trace import DemoActionKind, DemoFeedbackCode

from ._scenario_helper import run_scenario


def test_feedback_success_runs_two_patch_and_test_cycles_without_baseline_test(
    tmp_path,
):
    events, _, session = run_scenario("feedback_success", tmp_path)

    assert len(events) == 7
    assert (
        events[0].action_kind,
        events[1].outcome,
        events[2].feedback_code,
        events[3].action_kind,
        events[4].outcome,
        events[5].feedback_code,
        events[6].task_status,
    ) == (
        DemoActionKind.APPLY_PATCH,
        _TestRunOutcome.FAILED,
        DemoFeedbackCode.INITIAL_FAILURE,
        DemoActionKind.APPLY_PATCH,
        _TestRunOutcome.PASSED,
        DemoFeedbackCode.PASSED,
        TaskStatus.SUCCEEDED,
    )
    assert events[2].feedback_code is not DemoFeedbackCode.CHANGED
    assert tuple(event.sequence for event in events) == tuple(range(7))

    ScenarioRegistry().get("feedback_success").trace_contract.validate(events)

    history_action_types = tuple(entry.action_type for entry in session.history)
    tool_action_types = {
        "list_files",
        "read_file",
        "search_code",
        "run_tests",
        "git_diff",
        "git_status",
        "run_diagnostic",
    }
    patch_calls = history_action_types.count("apply_patch")
    full_test_calls = history_action_types.count("full_test")
    tool_calls = sum(
        action_type in tool_action_types for action_type in history_action_types
    )

    assert history_action_types == (
        "apply_patch",
        "full_test",
        "apply_patch",
        "full_test",
    )
    assert patch_calls == 2
    assert full_test_calls == 2
    assert tool_calls == 0
    assert tuple(result.phase for result in session.result_history) == (
        _TestPhase.POST_PATCH,
        _TestPhase.POST_PATCH,
    )
