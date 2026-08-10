import json
import sqlite3

from coding_agent_harness import composition
from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM
from coding_agent_harness.adapters.runtime.action_executor import (
    CoreTestRunner,
    ProductionActionExecutor,
)
from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.demo.workspaces import resolve_repository_template
from coding_agent_harness.domain.actions import ApplyPatchAction
from coding_agent_harness.domain.enums import PolicyOutcome, TaskStatus
from coding_agent_harness.security.policy import PolicyEngine, PolicyReasonCode
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    PolicyDecisionEvent,
    TerminalStatusEvent,
)

from . import _scenario_helper


def test_governance_denied_emits_only_a_typed_denial_trace(tmp_path, monkeypatch):
    config = ScenarioRegistry().get("governance_denied")
    assert len(config.scripted_actions) == 1
    assert isinstance(config.scripted_actions[0], ApplyPatchAction)

    captured_runtimes = []
    policy_calls = []
    patch_execution_calls = []
    tool_execution_calls = []
    full_test_calls = []
    real_build_demo_runtime = _scenario_helper.build_demo_runtime
    real_policy_evaluate = PolicyEngine.evaluate
    real_execute_patch = ProductionActionExecutor.execute_patch
    real_execute = ProductionActionExecutor.execute
    real_full_test = CoreTestRunner.run

    def capture_runtime(**kwargs):
        runtime = real_build_demo_runtime(**kwargs)
        captured_runtimes.append(runtime)
        return runtime

    def capture_policy(self, action, facts, policy_config, approval):
        decision = real_policy_evaluate(self, action, facts, policy_config, approval)
        policy_calls.append((action, facts, decision))
        return decision

    def capture_patch_execution(self, action, prepared):
        patch_execution_calls.append((action, prepared))
        return real_execute_patch(self, action, prepared)

    def capture_tool_execution(self, action):
        tool_execution_calls.append(action)
        return real_execute(self, action)

    def capture_full_test(self):
        full_test_calls.append(self)
        return real_full_test(self)

    def fail_if_real_provider_is_constructed(*args, **kwargs):
        del args, kwargs
        raise AssertionError("real provider construction is forbidden in this scenario")

    monkeypatch.setattr(_scenario_helper, "build_demo_runtime", capture_runtime)
    monkeypatch.setattr(PolicyEngine, "evaluate", capture_policy)
    monkeypatch.setattr(ProductionActionExecutor, "execute_patch", capture_patch_execution)
    monkeypatch.setattr(ProductionActionExecutor, "execute", capture_tool_execution)
    monkeypatch.setattr(CoreTestRunner, "run", capture_full_test)
    monkeypatch.setattr(composition, "build_real_llm", fail_if_real_provider_is_constructed)

    events, view, session = _scenario_helper.run_scenario("governance_denied", tmp_path)

    assert len(captured_runtimes) == 1
    runtime = captured_runtimes[0]
    assert runtime.frozen_config.llm.model == "offline-scripted"
    assert runtime.runtime.provider_factory is runtime.provider_factory
    assert runtime.provider_factory.actions == tuple(
        action.model_dump(mode="json") for action in config.scripted_actions
    )
    assert len(runtime.provider_factory.clients) == 1
    assert isinstance(runtime.provider_factory.clients[0], ScriptedMockLLM)
    assert len(runtime.provider_factory.clients[0].contexts) == 1

    assert len(policy_calls) == 1
    policy_action, policy_facts, policy_decision = policy_calls[0]
    assert isinstance(policy_action, ApplyPatchAction)
    assert policy_action == config.scripted_actions[0]
    assert policy_facts.touches_test_assets is True
    assert policy_decision.outcome is PolicyOutcome.DENY
    assert policy_decision.reason_code is PolicyReasonCode.TEST_ASSET_PROTECTION

    assert len(events) == 3
    selected, decision, terminal = events
    assert isinstance(selected, ActionSelectedEvent)
    assert selected.action_kind is DemoActionKind.APPLY_PATCH
    assert isinstance(decision, PolicyDecisionEvent)
    assert decision.decision is PolicyOutcome.DENY
    assert decision.reason_code is PolicyReasonCode.TEST_ASSET_PROTECTION
    assert isinstance(terminal, TerminalStatusEvent)
    assert terminal.task_status is TaskStatus.STOPPED
    assert [event.sequence for event in events] == [0, 1, 2]
    config.trace_contract.validate(events)

    assert view.status is TaskStatus.STOPPED
    assert session.status is TaskStatus.STOPPED
    assert session.action_count == config.max_actions == 1
    assert tuple((entry.action_type, entry.safe_result) for entry in session.history) == (
        ("policy_deny", PolicyReasonCode.TEST_ASSET_PROTECTION.value),
    )
    assert runtime.patch_apply_calls == 0
    assert runtime.external_action_calls == 0
    assert patch_execution_calls == []
    assert tool_execution_calls == []
    assert full_test_calls == []

    with sqlite3.connect(tmp_path / "request_root" / "data" / "state.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone() == (0,)

    template_test = resolve_repository_template(config.repository_template) / "tests" / "test_calculator.py"
    expected_test_bytes = template_test.read_bytes()
    repository_test = tmp_path / "request_root" / "repository" / "tests" / "test_calculator.py"
    (worktree,) = tuple((tmp_path / "request_root" / "data" / "worktrees").iterdir())
    assert repository_test.read_bytes() == expected_test_bytes
    assert (worktree / "tests" / "test_calculator.py").read_bytes() == expected_test_bytes

    trace_payload = json.dumps(
        [event.model_dump(mode="json") for event in events],
        sort_keys=True,
    )
    assert json.loads(trace_payload) == [
        {
            "action_kind": "apply_patch",
            "event_type": "action_selected",
            "sequence": 0,
        },
        {
            "decision": "deny",
            "event_type": "policy_decision",
            "reason_code": "test_asset_protection",
            "sequence": 1,
        },
        {
            "event_type": "terminal_status",
            "sequence": 2,
            "task_status": "stopped",
        },
    ]
    assert "Modify the test file to always pass." not in trace_payload
    assert "tests/test_calculator.py" not in trace_payload
    assert "assert True" not in trace_payload
    assert "--- a/" not in trace_payload
    assert '"diff"' not in trace_payload
