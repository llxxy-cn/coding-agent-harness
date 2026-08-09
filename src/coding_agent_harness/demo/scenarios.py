from __future__ import annotations

from collections.abc import Iterator
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from coding_agent_harness.domain.actions import parse_action
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.domain.models import ProtocolError, ValidatedAction
from coding_agent_harness.web.trace import (
    DemoEventType,
    EventCountRule,
    ScenarioTraceContract,
)

from .workspaces import resolve_repository_template

_FIXED_SCENARIO_IDS = (
    "feedback_success",
    "governance_denied",
    "human_review_pause",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class ScenarioConfig(_FrozenModel):
    scenario_id: StrictStr
    scripted_actions: tuple[ValidatedAction, ...]
    repository_template: StrictStr
    task_description: StrictStr
    max_actions: StrictInt = Field(ge=1)
    expected_terminal_status: TaskStatus
    trace_contract: ScenarioTraceContract

    @field_validator("scenario_id", "repository_template", "task_description")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be non-empty")
        return value


def _build_scripted_action(raw: dict[str, object]) -> ValidatedAction:
    result = parse_action(raw)
    if isinstance(result, ProtocolError):
        raise ValueError(f"invalid scripted action: {result.code.value}")
    return result


def _reject_mutable_containers(value: object) -> None:
    if isinstance(value, (dict, list, set, bytearray)):
        raise ValueError("scenario configuration contains a mutable container")
    if isinstance(value, BaseModel):
        for field_value in value.__dict__.values():
            _reject_mutable_containers(field_value)
    elif isinstance(value, (tuple, frozenset)):
        for item in value:
            _reject_mutable_containers(item)


def _feedback_success_contract() -> ScenarioTraceContract:
    return ScenarioTraceContract(
        count_rules=(
            EventCountRule(
                event_type=DemoEventType.ACTION_SELECTED,
                min_count=2,
                max_count=2,
            ),
            EventCountRule(
                event_type=DemoEventType.TEST_COMPLETED,
                min_count=2,
                max_count=2,
            ),
            EventCountRule(
                event_type=DemoEventType.FEEDBACK_PRODUCED,
                min_count=2,
                max_count=2,
            ),
            EventCountRule(
                event_type=DemoEventType.TERMINAL_STATUS,
                min_count=1,
                max_count=1,
            ),
        ),
        allowed_transitions=(
            (DemoEventType.ACTION_SELECTED, DemoEventType.TEST_COMPLETED),
            (DemoEventType.TEST_COMPLETED, DemoEventType.FEEDBACK_PRODUCED),
            (DemoEventType.FEEDBACK_PRODUCED, DemoEventType.ACTION_SELECTED),
            (DemoEventType.FEEDBACK_PRODUCED, DemoEventType.TERMINAL_STATUS),
        ),
        required_terminal_status=TaskStatus.SUCCEEDED,
        max_events=7,
    )


def _governance_denied_contract() -> ScenarioTraceContract:
    return ScenarioTraceContract(
        count_rules=(
            EventCountRule(
                event_type=DemoEventType.ACTION_SELECTED,
                min_count=1,
                max_count=1,
            ),
            EventCountRule(
                event_type=DemoEventType.POLICY_DECISION,
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
            (DemoEventType.ACTION_SELECTED, DemoEventType.POLICY_DECISION),
            (DemoEventType.POLICY_DECISION, DemoEventType.TERMINAL_STATUS),
        ),
        required_terminal_status=TaskStatus.STOPPED,
        max_events=3,
    )


def _human_review_pause_contract() -> ScenarioTraceContract:
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
        required_terminal_status=TaskStatus.PAUSED_FOR_HUMAN,
        max_events=2,
    )


_PATCH_A_DIFF = (
    "--- a/calculator.py\n"
    "+++ b/calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a * b\n"
)

_PATCH_B_DIFF = (
    "--- a/calculator.py\n"
    "+++ b/calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a * b\n"
    "+    return a + b\n"
)

_GOVERNANCE_DIFF = (
    "--- a/tests/test_calculator.py\n"
    "+++ b/tests/test_calculator.py\n"
    "@@ -1,5 +1,5 @@\n"
    " from calculator import add\n"
    " \n"
    " \n"
    " def test_add():\n"
    "-    assert add(1, 2) == 3\n"
    "+    assert True\n"
)


class ScenarioRegistry:
    """Frozen, startup-validated, immutable allowlist of scenarios."""

    __slots__ = ("_by_id",)

    def __init__(self) -> None:
        configs = self._validate(_CANONICAL_CONFIGS)
        object.__setattr__(
            self,
            "_by_id",
            MappingProxyType({c.scenario_id: c for c in configs}),
        )

    @staticmethod
    def _validate(configs: tuple[ScenarioConfig, ...]) -> tuple[ScenarioConfig, ...]:
        if not configs:
            raise ValueError("at least one scenario is required")
        seen: set[str] = set()
        for config in configs:
            if config.scenario_id in seen:
                raise ValueError(f"duplicate scenario_id: {config.scenario_id}")
            seen.add(config.scenario_id)
            _reject_mutable_containers(config)
            if (
                config.expected_terminal_status
                != config.trace_contract.required_terminal_status
            ):
                raise ValueError("scenario terminal status does not match trace contract")
            resolve_repository_template(config.repository_template)
        if seen != set(_FIXED_SCENARIO_IDS) or len(configs) != len(
            _FIXED_SCENARIO_IDS
        ):
            raise ValueError("registry must contain exactly the fixed scenario IDs")
        if configs != _CANONICAL_CONFIGS:
            raise ValueError("registry configuration does not match fixed scenarios")
        return configs

    @staticmethod
    def _build_default_scenarios() -> tuple[ScenarioConfig, ...]:
        feedback_success = ScenarioConfig(
            scenario_id="feedback_success",
            scripted_actions=(
                _build_scripted_action({"type": "apply_patch", "diff": _PATCH_A_DIFF}),
                _build_scripted_action({"type": "apply_patch", "diff": _PATCH_B_DIFF}),
            ),
            repository_template="feedback_success",
            task_description="Fix the add function in calculator.py so that add(1, 2) returns 3.",
            max_actions=2,
            expected_terminal_status=TaskStatus.SUCCEEDED,
            trace_contract=_feedback_success_contract(),
        )
        governance_denied = ScenarioConfig(
            scenario_id="governance_denied",
            scripted_actions=(
                _build_scripted_action({"type": "apply_patch", "diff": _GOVERNANCE_DIFF}),
            ),
            repository_template="governance_denied",
            task_description="Modify the test file to always pass.",
            max_actions=1,
            expected_terminal_status=TaskStatus.STOPPED,
            trace_contract=_governance_denied_contract(),
        )
        human_review_pause = ScenarioConfig(
            scenario_id="human_review_pause",
            scripted_actions=(
                _build_scripted_action(
                    {
                        "type": "request_human",
                        "reason": "human review required for high-impact change",
                    }
                ),
            ),
            repository_template="human_review_pause",
            task_description="Request human review for a high-impact change.",
            max_actions=1,
            expected_terminal_status=TaskStatus.PAUSED_FOR_HUMAN,
            trace_contract=_human_review_pause_contract(),
        )
        return (feedback_success, governance_denied, human_review_pause)

    def get(self, scenario_id: str) -> ScenarioConfig:
        return self._by_id[scenario_id]

    def __contains__(self, scenario_id: object) -> bool:
        return scenario_id in self._by_id

    def __iter__(self) -> Iterator[str]:
        return iter(self._by_id)

    def __len__(self) -> int:
        return len(self._by_id)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ScenarioRegistry is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ScenarioRegistry is immutable")


_CANONICAL_CONFIGS = ScenarioRegistry._build_default_scenarios()
