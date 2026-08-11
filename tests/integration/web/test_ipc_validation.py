"""Integration contracts for parent-side Web UI worker-result validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coding_agent_harness.demo.scenarios import ScenarioConfig, ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web.process_boundary import FakeProcessBoundary
from coding_agent_harness.web.run_service import DemoRunService, RunServiceError
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    DemoEventType,
    DemoWorkerResult,
    EventCountRule,
    ScenarioTraceContract,
    TerminalStatusEvent,
)


def _valid_result_bytes() -> bytes:
    """Use typed DTOs to form the one valid registered IPC document."""
    return (
        DemoWorkerResult(
            schema_version=1,
            scenario_id="human_review_pause",
            events=(
                ActionSelectedEvent(
                    action_kind=DemoActionKind.REQUEST_HUMAN,
                    sequence=0,
                ),
                TerminalStatusEvent(
                    task_status=TaskStatus.PAUSED_FOR_HUMAN,
                    sequence=1,
                ),
            ),
            terminal_code=TaskStatus.PAUSED_FOR_HUMAN,
        )
        .model_dump_json()
        .encode("utf-8")
    )


class _SingleScenarioRegistry:
    """Test-only registry accepting one otherwise-valid custom trace contract."""

    def __init__(self, scenario: ScenarioConfig) -> None:
        self._scenario = scenario

    def __contains__(self, scenario_id: object) -> bool:
        return scenario_id == self._scenario.scenario_id

    def get(self, scenario_id: str) -> ScenarioConfig:
        if scenario_id != self._scenario.scenario_id:
            raise KeyError(scenario_id)
        return self._scenario


def _sixty_five_event_scenario() -> ScenarioConfig:
    """Keep every contract rule valid except the independent global 64-event cap."""
    base = ScenarioRegistry().get("human_review_pause")
    contract = ScenarioTraceContract(
        count_rules=(
            EventCountRule(
                event_type=DemoEventType.ACTION_SELECTED,
                min_count=64,
                max_count=64,
            ),
            EventCountRule(
                event_type=DemoEventType.TERMINAL_STATUS,
                min_count=1,
                max_count=1,
            ),
        ),
        allowed_transitions=(
            (DemoEventType.ACTION_SELECTED, DemoEventType.ACTION_SELECTED),
            (DemoEventType.ACTION_SELECTED, DemoEventType.TERMINAL_STATUS),
        ),
        required_terminal_status=TaskStatus.PAUSED_FOR_HUMAN,
        max_events=65,
    )
    return base.model_copy(update={"trace_contract": contract})


class _PausedTerminalPermittingContract:
    """Test-only contract double that reaches the parent's final consistency check."""

    required_terminal_status = TaskStatus.STOPPED

    def __init__(self) -> None:
        self._event_contract = (
            ScenarioRegistry().get("human_review_pause").trace_contract
        )

    def validate(self, events: tuple[object, ...]) -> None:
        self._event_contract.validate(events)  # type: ignore[arg-type]


def _terminal_mismatch_scenario() -> ScenarioConfig:
    """Match code to scenario/contract while allowing only its paused event to differ."""
    base = ScenarioRegistry().get("human_review_pause")
    return base.model_copy(
        update={
            "expected_terminal_status": TaskStatus.STOPPED,
            "trace_contract": _PausedTerminalPermittingContract(),
        }
    )


def _service_for_payload(
    payload: bytes,
    *,
    scenario_registry: ScenarioRegistry | _SingleScenarioRegistry | None = None,
) -> DemoRunService:
    """Provide the payload as the only worker side effect used by these tests."""

    def factory(command: list[str], **_kwargs: object) -> FakeProcessBoundary:
        result_path = Path(command[command.index("--result") + 1])
        result_path.write_bytes(payload)
        return FakeProcessBoundary()

    return DemoRunService(
        scenario_registry=ScenarioRegistry()
        if scenario_registry is None
        else scenario_registry,  # type: ignore[arg-type]
        trusted_python="trusted-python",
        process_factory=factory,
        monotonic_clock=lambda: 100.0,
    )


def _assert_rejected(
    payload: bytes,
    tmp_path: Path,
    *,
    scenario_registry: ScenarioRegistry | _SingleScenarioRegistry | None = None,
) -> None:
    with pytest.raises(RunServiceError, match="^trace_incomplete$") as error:
        _service_for_payload(payload, scenario_registry=scenario_registry).run_scenario(
            "human_review_pause", tmp_path
        )
    assert error.value.code == "trace_incomplete"
    assert not tuple(tmp_path.iterdir())


def test_demo_worker_result_schema_accepts_a_valid_typed_json_document(
    tmp_path: Path,
) -> None:
    """The parent must deserialize a worker result only after strict validation."""
    view = _service_for_payload(_valid_result_bytes()).run_scenario(
        "human_review_pause", tmp_path
    )

    assert view.terminal_status is TaskStatus.PAUSED_FOR_HUMAN
    assert isinstance(view.events[0], ActionSelectedEvent)
    assert isinstance(view.events[-1], TerminalStatusEvent)
    assert not tuple(tmp_path.iterdir())


def test_unknown_ipc_field_is_rejected(tmp_path: Path) -> None:
    """Ignoring an unknown top-level field would widen the IPC contract."""
    payload = json.loads(_valid_result_bytes())
    payload["untrusted_extra"] = "unexpected"

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


def test_unknown_nested_ipc_event_field_is_rejected(tmp_path: Path) -> None:
    """Ignoring an event field would widen a discriminated IPC DTO."""
    payload = json.loads(_valid_result_bytes())
    payload["events"][0]["untrusted_extra"] = "unexpected"

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


def test_result_scenario_id_must_match_the_started_scenario(tmp_path: Path) -> None:
    """A result from another allowed scenario must never satisfy this run."""
    payload = json.loads(_valid_result_bytes())
    payload["scenario_id"] = "feedback_success"

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


def test_result_scenario_id_must_be_a_string(tmp_path: Path) -> None:
    """Coercing a numeric scenario ID could bypass the typed parent contract."""
    payload = json.loads(_valid_result_bytes())
    payload["scenario_id"] = 123

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


@pytest.mark.parametrize("invalid_version", (True, 1.0, "1"))
def test_schema_version_accepts_only_the_integer_literal_one(
    tmp_path: Path,
    invalid_version: object,
) -> None:
    """Boolean, float, and string lookalikes must not bypass version strictness."""
    payload = json.loads(_valid_result_bytes())
    payload["schema_version"] = invalid_version

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


def test_invalid_event_discriminator_is_rejected(tmp_path: Path) -> None:
    """An unknown event type must not be accepted as an untyped trace dictionary."""
    payload = json.loads(_valid_result_bytes())
    payload["events"][0]["event_type"] = "unrecognized_event"

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


def test_invalid_event_typed_field_is_rejected(tmp_path: Path) -> None:
    """Boolean sequence values must not be coerced through StrictInt validation."""
    payload = json.loads(_valid_result_bytes())
    payload["events"][0]["sequence"] = True

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


def test_invalid_terminal_enum_is_rejected(tmp_path: Path) -> None:
    """An arbitrary terminal code must not be treated as a status enum value."""
    payload = json.loads(_valid_result_bytes())
    payload["terminal_code"] = "unrecognized_status"

    _assert_rejected(json.dumps(payload).encode("utf-8"), tmp_path)


def test_terminal_code_must_match_the_terminal_event(tmp_path: Path) -> None:
    """A worker cannot claim a terminal result that its event stream contradicts."""
    payload = json.loads(_valid_result_bytes())
    payload["terminal_code"] = "stopped"

    result = DemoWorkerResult.model_validate(payload)
    scenario = _terminal_mismatch_scenario()
    assert result.terminal_code is scenario.expected_terminal_status
    assert result.terminal_code is scenario.trace_contract.required_terminal_status
    scenario.trace_contract.validate(result.events)
    assert isinstance(result.events[-1], TerminalStatusEvent)
    assert result.events[-1].task_status is not result.terminal_code

    _assert_rejected(
        json.dumps(payload).encode("utf-8"),
        tmp_path,
        scenario_registry=_SingleScenarioRegistry(scenario),
    )


def test_ipc_result_with_more_than_sixty_four_events_is_rejected(
    tmp_path: Path,
) -> None:
    """Removing the parent event cap would allow an oversized worker trace."""
    events = [
        {
            "event_type": "action_selected",
            "action_kind": "request_human",
            "sequence": sequence,
        }
        for sequence in range(64)
    ]
    events.append(
        {
            "event_type": "terminal_status",
            "task_status": "paused_for_human",
            "sequence": 64,
        }
    )
    payload = json.dumps(
        {
            "schema_version": 1,
            "scenario_id": "human_review_pause",
            "events": events,
            "terminal_code": "paused_for_human",
        }
    ).encode("utf-8")

    result = DemoWorkerResult.model_validate_json(payload)
    scenario = _sixty_five_event_scenario()
    scenario.trace_contract.validate(result.events)

    _assert_rejected(
        payload,
        tmp_path,
        scenario_registry=_SingleScenarioRegistry(scenario),
    )


def test_ipc_result_larger_than_sixty_four_kib_is_rejected(tmp_path: Path) -> None:
    """Removing the byte limit would let an untrusted worker exhaust parent memory."""
    valid = _valid_result_bytes()
    oversized_whitespace = b" " * (64 * 1024 - len(valid) + 1)
    payload = valid + oversized_whitespace

    assert len(payload) > 64 * 1024
    assert (
        DemoRunService._decode_worker_result(payload).scenario_id
        == "human_review_pause"
    )
    _assert_rejected(payload, tmp_path)


def test_ipc_result_with_trailing_json_data_is_rejected(tmp_path: Path) -> None:
    """Permitting concatenated JSON would make the result boundary ambiguous."""
    _assert_rejected(_valid_result_bytes() + b"\n{}", tmp_path)


def test_ipc_result_with_duplicate_json_keys_is_rejected(tmp_path: Path) -> None:
    """The duplicate-key hook must prevent parser last-key-wins behavior."""
    valid = _valid_result_bytes()
    duplicated = valid.replace(
        b'{"schema_version":1,',
        b'{"schema_version":1,"schema_version":1,',
        1,
    )
    assert duplicated != valid

    _assert_rejected(duplicated, tmp_path)


def test_ipc_result_with_duplicate_nested_json_keys_is_rejected(tmp_path: Path) -> None:
    """The duplicate-key hook must reject nested object ambiguity as well."""
    valid = _valid_result_bytes()
    duplicated = valid.replace(
        b'"action_kind":"request_human",',
        b'"action_kind":"request_human","action_kind":"request_human",',
        1,
    )
    assert duplicated != valid

    _assert_rejected(duplicated, tmp_path)
