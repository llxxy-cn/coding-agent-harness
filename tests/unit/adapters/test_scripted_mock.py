import pytest

from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM
from coding_agent_harness.core.context import ContextBuilder, ContextSnapshot


def test_scripted_mock_returns_in_order_records_context_and_exhausts() -> None:
    llm = ScriptedMockLLM(['{"type":"git_status"}', "not-json"])
    context = ContextBuilder().build(ContextSnapshot(user_task="fix", config_summary="demo", action_schema=("git_status",), workspace_summary="safe", history=(), feedback_summary=None, remaining_actions=2, remaining_feedback=1))
    assert llm.generate(context) == '{"type":"git_status"}'
    assert llm.generate(context) == "not-json"
    assert llm.contexts == (context, context)
    with pytest.raises(RuntimeError, match="script exhausted"):
        llm.generate(context)
