from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.core.tool_dispatcher import TypedToolDispatcher
from coding_agent_harness.domain.tool_payloads import ToolPayloadUnion, DiagnosticPayload, GitDiffPayload, GitStatusPayload, ListFilesPayload, ReadFilePayload, SearchCodePayload
from coding_agent_harness.domain.actions import ApplyPatchAction, GitDiffAction, GitStatusAction, ListFilesAction, ReadFileAction, RequestHumanAction, RunDiagnosticAction, RunTestsAction, SearchCodeAction
from coding_agent_harness.domain.models import ToolPayload


def test_dispatcher_rejects_missing_capability_before_handler_call() -> None:
    capabilities = resolve_config(BUILTIN_CONFIG, {}, {}, "demo").capabilities
    dispatcher = TypedToolDispatcher()
    result = dispatcher.dispatch(GitStatusAction(type="git_status"), capabilities)
    assert not result.ok
    assert dispatcher.handler_calls == []


def test_unregistered_mutating_actions_are_not_dispatchable() -> None:
    capabilities = resolve_config(BUILTIN_CONFIG, {}, {}, "real").capabilities
    dispatcher = TypedToolDispatcher()
    actions = (
        ApplyPatchAction(type="apply_patch", diff="diff\n"),
        RunTestsAction(type="run_tests", scope="full", targets=[]),
        RequestHumanAction(type="request_human", reason="help"),
    )
    for action in actions:
        result = dispatcher.dispatch(action, capabilities)
        assert not result.ok
    assert dispatcher.handler_calls == []


def test_concrete_payloads_are_frozen_extra_forbid_and_union_is_closed() -> None:
    payloads = (
        ListFilesPayload(files=()), ReadFilePayload(text="", truncated=False),
        SearchCodePayload(matches=(), truncated=False), GitStatusPayload(entries=()),
        GitDiffPayload(diff="", truncated=False), DiagnosticPayload(diagnostic_id="x", exit_code=0, output=""),
    )
    assert all(isinstance(payload, ToolPayload) for payload in payloads)
    assert all(getattr(payload, "model_config", {}).get("frozen") for payload in payloads)
    for payload in payloads:
        try:
            payload.extra = 1
        except Exception:
            pass
        else:
            raise AssertionError("payload must be frozen")
    assert ToolPayloadUnion != ToolPayload
