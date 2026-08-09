"""Contract tests for frozen ScenarioRegistry, ScenarioConfig, and demo resources (Web UI v0.2.0 Task A2)."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from coding_agent_harness.demo.scenarios import (
    ScenarioConfig,
    ScenarioRegistry,
    _build_scripted_action,
)
from coding_agent_harness.demo.workspaces import resolve_repository_template
from coding_agent_harness.domain.actions import (
    ApplyPatchAction,
    RequestHumanAction,
)
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.domain.models import ValidatedAction
from coding_agent_harness.web.trace import (
    DemoEventType,
    EventCountRule,
    ScenarioTraceContract,
)


def _minimal_contract(
    terminal: TaskStatus = TaskStatus.SUCCEEDED,
    max_events: int = 2,
) -> ScenarioTraceContract:
    return ScenarioTraceContract(
        count_rules=(
            EventCountRule(
                event_type=DemoEventType.ACTION_SELECTED,
                min_count=1,
                max_count=1,
            ),
            EventCountRule(
                event_type=DemoEventType.TERMINAL_STATUS,
                min_count=1,
                max_count=1,
            ),
        ),
        allowed_transitions=(
            (DemoEventType.ACTION_SELECTED, DemoEventType.TERMINAL_STATUS),
        ),
        required_terminal_status=terminal,
        max_events=max_events,
    )


def _valid_patch_diff() -> str:
    return (
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    return a * b\n"
    )


def _make_config(
    *,
    scenario_id: str = "test_scenario",
    repository_template: str = "feedback_success",
    task_description: str = "a valid task description",
    max_actions: int = 1,
    expected_terminal_status: TaskStatus = TaskStatus.SUCCEEDED,
) -> ScenarioConfig:
    action = _build_scripted_action(
        {"type": "apply_patch", "diff": _valid_patch_diff()}
    )
    return ScenarioConfig(
        scenario_id=scenario_id,
        scripted_actions=(action,),
        repository_template=repository_template,
        task_description=task_description,
        max_actions=max_actions,
        expected_terminal_status=expected_terminal_status,
        trace_contract=_minimal_contract(),
    )


def _registry_from_configs(
    configs: tuple[ScenarioConfig, ...],
) -> ScenarioRegistry:
    ScenarioRegistry._validate(configs)
    return ScenarioRegistry()


def test_registry_has_exactly_three_scenarios():
    registry = ScenarioRegistry()
    assert len(registry) == 3
    ids = list(registry)
    assert all(isinstance(i, str) for i in ids)
    assert set(ids) == {"feedback_success", "governance_denied", "human_review_pause"}


def test_lookup_feedback_success_fields():
    registry = ScenarioRegistry()
    config = registry.get("feedback_success")
    assert config.scenario_id == "feedback_success"
    assert config.task_description == "Fix the add function in calculator.py so that add(1, 2) returns 3."
    assert config.repository_template == "feedback_success"
    assert config.max_actions == 2
    assert config.expected_terminal_status == TaskStatus.SUCCEEDED
    assert len(config.scripted_actions) == 2
    assert all(isinstance(a, ApplyPatchAction) for a in config.scripted_actions)
    assert config.trace_contract.max_events == 7
    assert config.trace_contract.required_terminal_status == TaskStatus.SUCCEEDED


def test_lookup_governance_denied_fields():
    registry = ScenarioRegistry()
    config = registry.get("governance_denied")
    assert config.scenario_id == "governance_denied"
    assert config.task_description == "Modify the test file to always pass."
    assert config.repository_template == "governance_denied"
    assert config.max_actions == 1
    assert config.expected_terminal_status == TaskStatus.STOPPED
    assert len(config.scripted_actions) == 1
    assert isinstance(config.scripted_actions[0], ApplyPatchAction)
    assert config.trace_contract.max_events == 3
    assert config.trace_contract.required_terminal_status == TaskStatus.STOPPED


def test_lookup_human_review_pause_fields():
    registry = ScenarioRegistry()
    config = registry.get("human_review_pause")
    assert config.scenario_id == "human_review_pause"
    assert config.task_description == "Request human review for a high-impact change."
    assert config.repository_template == "human_review_pause"
    assert config.max_actions == 1
    assert config.expected_terminal_status == TaskStatus.PAUSED_FOR_HUMAN
    assert len(config.scripted_actions) == 1
    assert isinstance(config.scripted_actions[0], RequestHumanAction)
    assert config.scripted_actions[0].reason == "human review required for high-impact change"
    assert config.trace_contract.max_events == 2
    assert config.trace_contract.required_terminal_status == TaskStatus.PAUSED_FOR_HUMAN


def test_unknown_id_raises_keyerror():
    registry = ScenarioRegistry()
    with pytest.raises(KeyError):
        registry.get("unknown")
    assert "unknown" not in registry
    assert "feedback_success" in registry


def test_registry_rejects_non_fixed_allowlist():
    with pytest.raises(ValueError, match="exactly the fixed scenario IDs"):
        _registry_from_configs((_make_config(),))


def test_duplicate_id_startup_fails():
    config_a = _make_config(scenario_id="dup")
    config_b = _make_config(scenario_id="dup")
    with pytest.raises(ValueError, match="duplicate"):
        _registry_from_configs((config_a, config_b))


def test_empty_task_description_fails():
    with pytest.raises(ValidationError):
        _make_config(task_description="")


def test_missing_package_resource_startup_fails():
    configs = ScenarioRegistry._build_default_scenarios()
    config = configs[0].model_copy(
        update={"repository_template": "nonexistent_resource"}
    )
    with pytest.raises(ValueError):
        _registry_from_configs((config, *configs[1:]))


def test_terminal_status_mismatch_startup_fails():
    configs = ScenarioRegistry._build_default_scenarios()
    config = configs[0].model_copy(
        update={"expected_terminal_status": TaskStatus.STOPPED}
    )
    with pytest.raises(ValueError, match="terminal status"):
        _registry_from_configs((config, *configs[1:]))


def test_mutable_nested_payload_startup_fails():
    configs = ScenarioRegistry._build_default_scenarios()
    action = configs[0].scripted_actions[0].model_copy(
        update={"unexpected_mutable_payload": ["unsafe"]}
    )
    config = configs[0].model_copy(update={"scripted_actions": (action,)})
    with pytest.raises(ValueError, match="mutable container"):
        _registry_from_configs((config, *configs[1:]))


def test_fixed_scenario_field_mismatch_startup_fails():
    configs = ScenarioRegistry._build_default_scenarios()
    config = configs[0].model_copy(update={"max_actions": 999})
    with pytest.raises(ValueError, match="does not match fixed scenarios"):
        _registry_from_configs((config, *configs[1:]))


def test_escape_resource_identifiers_rejected():
    with pytest.raises(ValueError):
        resolve_repository_template("../escape")
    with pytest.raises(ValueError):
        resolve_repository_template("/absolute")
    with pytest.raises(ValueError):
        resolve_repository_template(r"C:\absolute")
    with pytest.raises(ValueError):
        resolve_repository_template(r"\\server\share")


def test_symlink_escape_resource_identifier_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from coding_agent_harness.demo import workspaces

    package_root = tmp_path / "package"
    resources_root = package_root / "resources"
    template_root = resources_root / "template"
    outside = tmp_path / "outside"
    template_root.mkdir(parents=True)
    outside.mkdir()
    try:
        os.symlink(outside, template_root / "nested_escape", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")
    monkeypatch.setattr(workspaces, "_PACKAGE_FILES", package_root)
    with pytest.raises(ValueError, match="escape"):
        workspaces.resolve_repository_template("template")


def test_malformed_scripted_action_startup_fails():
    with pytest.raises(ValueError):
        _build_scripted_action({"type": "apply_patch", "diff": ""})
    with pytest.raises(ValueError):
        _build_scripted_action({"type": "unknown_type"})


def test_scripted_actions_are_validated_instances():
    registry = ScenarioRegistry()
    for scenario_id in registry:
        config = registry.get(scenario_id)
        for action in config.scripted_actions:
            assert isinstance(action, ValidatedAction)


def test_registry_is_immutable():
    registry = ScenarioRegistry()
    for method in ("add", "remove", "update", "set", "pop", "clear", "delete", "insert"):
        assert not hasattr(registry, method), f"registry has {method}"
    with pytest.raises(TypeError):
        registry._by_id["x"] = None  # type: ignore[index]
    with pytest.raises(AttributeError):
        registry.foo = "bar"  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        del registry._by_id  # type: ignore[attr-defined]


def test_scenario_config_and_actions_deeply_immutable():
    registry = ScenarioRegistry()
    config = registry.get("feedback_success")
    with pytest.raises(ValidationError):
        config.scenario_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        config.task_description = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        config.scripted_actions = ()  # type: ignore[misc]
    action = config.scripted_actions[0]
    with pytest.raises(ValidationError):
        action.diff = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.scripted_actions[0] = action  # type: ignore[index]


def test_no_api_to_modify_scenario_fields():
    registry = ScenarioRegistry()
    config = registry.get("feedback_success")
    for method in (
        "set_task_description",
        "set_repository_template",
        "set_actions",
        "update",
        "add_action",
        "remove_action",
    ):
        assert not hasattr(config, method), f"config has {method}"
    for method in (
        "set_scenarios",
        "add_scenario",
        "remove_scenario",
        "update_scenario",
    ):
        assert not hasattr(registry, method), f"registry has {method}"
    with pytest.raises(ValidationError):
        config.task_description = "changed"  # type: ignore[misc]


def test_scenario_config_rejects_extra_fields():
    action = _build_scripted_action({"type": "apply_patch", "diff": _valid_patch_diff()})
    with pytest.raises(ValidationError):
        ScenarioConfig(
            scenario_id="x",
            scripted_actions=(action,),
            repository_template="feedback_success",
            task_description="desc",
            max_actions=1,
            expected_terminal_status=TaskStatus.SUCCEEDED,
            trace_contract=_minimal_contract(),
            extra_field="bad",  # type: ignore[call-arg]
        )


def test_all_package_resources_exist_and_are_readable():
    expected_files = {
        "feedback_success": ("calculator.py", "tests/test_calculator.py"),
        "governance_denied": ("calculator.py", "tests/test_calculator.py"),
        "human_review_pause": ("service.py", "tests/test_service.py"),
    }
    for name, files in expected_files.items():
        path = resolve_repository_template(name)
        assert isinstance(path, Path)
        assert path.is_dir()
        for relative in files:
            file_path = path / relative
            assert file_path.is_file(), f"missing {file_path}"
            assert file_path.read_text(encoding="utf-8")


def test_no_provider_keyring_or_git_remote_imports():
    from coding_agent_harness.demo import scenarios as scenarios_module
    from coding_agent_harness.demo import workspaces as workspaces_module

    forbidden_tokens = ("keyring", "openai", "import git", "Provider", "from git")
    for module in (scenarios_module, workspaces_module):
        source = inspect.getsource(module)
        for token in forbidden_tokens:
            assert token not in source, f"{token!r} found in {module.__name__}"


def test_feedback_success_trace_contract():
    registry = ScenarioRegistry()
    contract = registry.get("feedback_success").trace_contract
    rules = {r.event_type: (r.min_count, r.max_count) for r in contract.count_rules}
    assert rules[DemoEventType.ACTION_SELECTED] == (2, 2)
    assert rules[DemoEventType.TEST_COMPLETED] == (2, 2)
    assert rules[DemoEventType.FEEDBACK_PRODUCED] == (2, 2)
    assert rules[DemoEventType.TERMINAL_STATUS] == (1, 1)
    assert (DemoEventType.ACTION_SELECTED, DemoEventType.TEST_COMPLETED) in contract.allowed_transitions
    assert (DemoEventType.TEST_COMPLETED, DemoEventType.FEEDBACK_PRODUCED) in contract.allowed_transitions
    assert (DemoEventType.FEEDBACK_PRODUCED, DemoEventType.ACTION_SELECTED) in contract.allowed_transitions
    assert (DemoEventType.FEEDBACK_PRODUCED, DemoEventType.TERMINAL_STATUS) in contract.allowed_transitions


def test_governance_denied_trace_contract():
    registry = ScenarioRegistry()
    contract = registry.get("governance_denied").trace_contract
    rules = {r.event_type: (r.min_count, r.max_count) for r in contract.count_rules}
    assert rules[DemoEventType.ACTION_SELECTED] == (1, 1)
    assert rules[DemoEventType.POLICY_DECISION] == (1, 1)
    assert rules[DemoEventType.TERMINAL_STATUS] == (1, 1)
    assert (DemoEventType.ACTION_SELECTED, DemoEventType.POLICY_DECISION) in contract.allowed_transitions
    assert (DemoEventType.POLICY_DECISION, DemoEventType.TERMINAL_STATUS) in contract.allowed_transitions


def test_human_review_pause_trace_contract():
    registry = ScenarioRegistry()
    contract = registry.get("human_review_pause").trace_contract
    rules = {r.event_type: (r.min_count, r.max_count) for r in contract.count_rules}
    assert rules[DemoEventType.ACTION_SELECTED] == (1, 1)
    assert rules[DemoEventType.TERMINAL_STATUS] == (1, 1)
    assert (DemoEventType.ACTION_SELECTED, DemoEventType.TERMINAL_STATUS) in contract.allowed_transitions


def test_feedback_success_scripted_action_content():
    registry = ScenarioRegistry()
    config = registry.get("feedback_success")
    patch_a, patch_b = config.scripted_actions
    assert "-    return a - b" in patch_a.diff
    assert "+    return a * b" in patch_a.diff
    assert "-    return a * b" in patch_b.diff
    assert "+    return a + b" in patch_b.diff


def test_governance_denied_scripted_action_content():
    registry = ScenarioRegistry()
    config = registry.get("governance_denied")
    (patch,) = config.scripted_actions
    assert "-    assert add(1, 2) == 3" in patch.diff
    assert "+    assert True" in patch.diff


def test_human_review_pause_scripted_action_content():
    registry = ScenarioRegistry()
    config = registry.get("human_review_pause")
    (action,) = config.scripted_actions
    assert isinstance(action, RequestHumanAction)
    assert action.reason == "human review required for high-impact change"
