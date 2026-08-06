from coding_agent_harness.core.context import ContextBuilder, ContextSnapshot, SafeHistoryEntry


def test_context_is_bounded_deterministic_and_contains_only_safe_decision_data() -> None:
    snapshot = ContextSnapshot(
        user_task="fix counter",
        config_summary="mode=demo",
        action_schema=("read_file", "apply_patch", "request_human"),
        workspace_summary="tests failing",
        history=(SafeHistoryEntry(action_type="read_file", safe_result="OPENAI_API_KEY=hidden C:\\Users\\alice\\repo\\a.py"),),
        feedback_summary="tests/test_counter.py failed",
        remaining_actions=3,
        remaining_feedback=2,
    )
    first = ContextBuilder().build(snapshot)
    second = ContextBuilder().build(snapshot)
    assert first == second and first.sha256 == second.sha256
    serialized = first.model_dump_json()
    assert "hidden" not in serialized and "Users" not in serialized
    assert "raw_output" not in serialized


def test_context_keeps_only_recent_bounded_history() -> None:
    history = tuple(SafeHistoryEntry(action_type="git_status", safe_result=str(index)) for index in range(20))
    context = ContextBuilder(max_history=4).build(ContextSnapshot(user_task="fix", config_summary="demo", action_schema=("git_status",), workspace_summary="safe", history=history, feedback_summary=None, remaining_actions=2, remaining_feedback=1))
    assert len(context.history) == 4
    assert tuple(item.safe_result for item in context.history) == ("16", "17", "18", "19")
