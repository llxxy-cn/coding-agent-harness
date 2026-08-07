from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest

from coding_agent_harness.core.harness import ActionExecution
from coding_agent_harness.domain.enums import FeedbackKind, TaskStatus, TestRunOutcome as DomainTestRunOutcome
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome

from tests.e2e.test_cli_repair_demo import PATCH, prepared_repository
from tests.unit.core.test_harness import Executor, FullTests, TASK_ID, core, make_test_run, parsed


PYTHON = str(Path(sys.executable).resolve())


def test_invalid_actions_stop_without_tool_or_patch_side_effects(tmp_path: Path) -> None:
    from coding_agent_harness.composition import build_demo_runtime

    repository = prepared_repository(tmp_path)
    runtime = build_demo_runtime(data_root=tmp_path / "data", scripted_actions=("{", '{"type":"unknown"}'), max_actions=2, trusted_python=PYTHON)

    result = runtime.run(repository=repository, task_description="invalid protocol", mode="demo", trust_repo=True)

    assert result.status is TaskStatus.STOPPED
    assert "return a - b" in (repository / "calculator.py").read_text(encoding="utf-8")
    assert runtime.external_action_calls == 0


def test_policy_deny_never_applies_test_asset_patch(tmp_path: Path) -> None:
    from coding_agent_harness.composition import build_demo_runtime

    repository = prepared_repository(tmp_path)
    protected_patch = "--- a/tests/test_calculator.py\n+++ b/tests/test_calculator.py\n@@ -3,2 +3,2 @@\n def test_adds_two_numbers() -> None:\n-    assert add(2, 3) == 5\n+    assert add(2, 3) == -1\n"
    runtime = build_demo_runtime(data_root=tmp_path / "data", scripted_actions=({"type": "apply_patch", "diff": protected_patch},), max_actions=1, trusted_python=PYTHON)

    result = runtime.run(repository=repository, task_description="modify tests", mode="demo", trust_repo=True)

    assert result.status is TaskStatus.STOPPED
    assert runtime.patch_apply_calls == 0
    worktree_test = next((tmp_path / "data" / "worktrees").glob("*/tests/test_calculator.py"))
    assert "== 5" in worktree_test.read_text(encoding="utf-8")


def test_request_human_pauses_without_action_tool_execution(tmp_path: Path) -> None:
    from coding_agent_harness.composition import build_demo_runtime

    repository = prepared_repository(tmp_path)
    runtime = build_demo_runtime(data_root=tmp_path / "data", scripted_actions=({"type": "request_human", "reason": "review required"},), trusted_python=PYTHON)

    result = runtime.run(repository=repository, task_description="request review", mode="demo", trust_repo=True)

    assert result.status is TaskStatus.PAUSED_FOR_HUMAN
    assert runtime.external_action_calls == 0 and runtime.patch_apply_calls == 0


def test_repeated_reliable_failure_stops_as_no_progress() -> None:
    first_run = make_test_run(DomainTestRunOutcome.FAILED)
    second_run = make_test_run(DomainTestRunOutcome.FAILED)
    first = parsed(ParsedOutcome.FAILED, ("tests/test_calculator.py::test_adds_two_numbers",), "same").model_copy(update={"run_id": first_run.run_id})
    second = parsed(ParsedOutcome.FAILED, ("tests/test_calculator.py::test_adds_two_numbers",), "same").model_copy(update={"run_id": second_run.run_id})
    full = FullTests([
        ActionExecution(safe_summary="failed", source_revision="same", test_run=first_run, parsed_result=first),
        ActionExecution(safe_summary="failed", source_revision="same", test_run=second_run, parsed_result=second),
    ])
    counter_patch = "--- a/counter.py\n+++ b/counter.py\n@@ -1 +1 @@\n-return 0\n+return 1\n"
    harness, _ = core([
        {"type": "apply_patch", "diff": counter_patch},
        {"type": "apply_patch", "diff": counter_patch},
    ], executor=Executor([ActionExecution(safe_summary="patch", source_revision="same"), ActionExecution(safe_summary="patch", source_revision="same")]), full=full)

    outcome = harness.run(TASK_ID)

    assert outcome.status is TaskStatus.STOPPED
    assert outcome.reason == FeedbackKind.NO_PROGRESS.value
    assert len(harness.llm.contexts) == 2


def test_unparseable_result_pauses_and_raw_output_never_enters_context() -> None:
    run = make_test_run(DomainTestRunOutcome.FAILED).model_copy(update={"outcome": DomainTestRunOutcome.UNPARSEABLE, "parsed_result_ref": None})
    execution = ActionExecution(safe_summary="test result unavailable", source_revision="same", test_run=run, parsed_result=None)
    harness, _ = core([{"type": "run_tests", "scope": "full", "targets": []}], executor=Executor([execution]))

    outcome = harness.run(TASK_ID)

    assert outcome.status is TaskStatus.PAUSED_FOR_HUMAN
    assert "raw" not in str(harness.llm.contexts).lower()


def test_resume_accepts_paused_task_and_rejects_succeeded_task(tmp_path: Path) -> None:
    from coding_agent_harness.composition import build_demo_runtime

    paused_repo = prepared_repository(tmp_path / "paused")
    paused = build_demo_runtime(data_root=tmp_path / "paused-data", scripted_actions=({"type": "request_human", "reason": "review"},), trusted_python=PYTHON)
    paused_view = paused.run(repository=paused_repo, task_description="pause", mode="demo", trust_repo=True)
    resumed = build_demo_runtime(data_root=tmp_path / "paused-data", scripted_actions=({"type": "request_human", "reason": "review again"},), trusted_python=PYTHON)
    assert resumed.resume(UUID(paused_view.task_id)).status is TaskStatus.PAUSED_FOR_HUMAN

    success_repo = prepared_repository(tmp_path / "success")
    success = build_demo_runtime(data_root=tmp_path / "success-data", scripted_actions=(
        {"type": "apply_patch", "diff": PATCH},
    ), trusted_python=PYTHON)
    success_view = success.run(repository=success_repo, task_description="repair", mode="demo", trust_repo=True)
    assert success_view.status is TaskStatus.SUCCEEDED
    with pytest.raises(ValueError, match="task is not resumable"):
        success.resume(UUID(success_view.task_id))
