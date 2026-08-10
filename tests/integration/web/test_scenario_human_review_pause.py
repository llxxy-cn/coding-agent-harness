"""Evidence tests for the fixed human-review pause demo scenario."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.demo.workspaces import resolve_repository_template
from coding_agent_harness.domain.actions import RequestHumanAction
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web.trace import (
    ActionSelectedEvent,
    DemoActionKind,
    DemoEventType,
    FeedbackProducedEvent,
    PolicyDecisionEvent,
    TerminalStatusEvent,
    TestCompletedEvent,
)

from ._scenario_helper import _GIT_ENV_ALLOWLIST, _GIT_TIMEOUT_SECONDS, run_scenario


def test_human_review_pause_records_only_a_redacted_human_request(tmp_path: Path) -> None:
    """A direct human-review request pauses without policy, execution, or approval."""
    config = ScenarioRegistry().get("human_review_pause")
    (request_human,) = config.scripted_actions
    assert isinstance(request_human, RequestHumanAction)

    events, view, session = run_scenario("human_review_pause", tmp_path)

    assert len(events) == 2
    assert isinstance(events[0], ActionSelectedEvent)
    assert events[0].action_kind is DemoActionKind.REQUEST_HUMAN
    assert isinstance(events[1], TerminalStatusEvent)
    assert events[1].task_status is TaskStatus.PAUSED_FOR_HUMAN
    assert [event.sequence for event in events] == [0, 1]
    config.trace_contract.validate(events)

    assert {event.event_type for event in events} == {
        DemoEventType.ACTION_SELECTED,
        DemoEventType.TERMINAL_STATUS,
    }
    assert not any(
        isinstance(event, (PolicyDecisionEvent, TestCompletedEvent, FeedbackProducedEvent))
        for event in events
    )

    action_types = tuple(entry.action_type for entry in session.history)
    tool_action_types = {
        "list_files",
        "read_file",
        "search_code",
        "run_tests",
        "git_diff",
        "git_status",
        "run_diagnostic",
    }
    tool_calls = sum(action_type in tool_action_types for action_type in action_types)
    patch_calls = sum(action_type == "apply_patch" for action_type in action_types)
    full_test_calls = sum(action_type == "full_test" for action_type in action_types)
    assert action_types == ("request_human",)
    assert tuple(entry.safe_result for entry in session.history) == (
        "human review requested",
    )
    assert (tool_calls, patch_calls, full_test_calls) == (0, 0, 0)
    assert view.status is TaskStatus.PAUSED_FOR_HUMAN
    assert session.status is TaskStatus.PAUSED_FOR_HUMAN
    assert session.status is not TaskStatus.AWAITING_APPROVAL

    trace_payload = tuple(event.model_dump(mode="json") for event in events)
    trace_json = json.dumps(trace_payload, sort_keys=True)
    assert request_human.reason not in trace_json
    assert all("reason" not in event for event in trace_payload)
    assert TaskStatus.AWAITING_APPROVAL.value not in trace_json

    request_root = tmp_path / "request_root"
    template = resolve_repository_template(config.repository_template)
    expected_files = {
        path.relative_to(template): path.read_bytes()
        for path in template.rglob("*")
        if path.is_file()
    }
    expected_files.update(
        {
            Path(".gitattributes"): b"* text=auto eol=lf\n",
            Path("conftest.py"): b"import sys\n\nsys.dont_write_bytecode = True\n",
            Path("pytest.ini"): b"[pytest]\naddopts = --assert=plain\n",
        }
    )
    repository = request_root / "repository"
    (worktree,) = tuple((request_root / "data" / "worktrees").iterdir())
    git_environment = {
        name: os.environ[name] for name in _GIT_ENV_ALLOWLIST if name in os.environ
    }
    git_environment.update(
        {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    for root in (repository, worktree):
        actual_files = {
            path.relative_to(root): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        assert actual_files == expected_files
        status = subprocess.run(
            (
                "git",
                "-c",
                "status.showUntrackedFiles=all",
                "-c",
                "core.fsmonitor=false",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignored=matching",
            ),
            cwd=root,
            env=git_environment,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        assert status.stdout == ""

    with sqlite3.connect(request_root / "data" / "state.sqlite3") as connection:
        approvals = connection.execute("SELECT status FROM approvals").fetchall()
        actions = connection.execute("SELECT status FROM actions").fetchall()
        persisted_session = connection.execute(
            "SELECT data_json FROM feedback_states WHERE task_id=?",
            (str(session.task_id.value),),
        ).fetchone()
    assert approvals == []
    assert actions == []
    assert persisted_session is not None
    persisted_json = persisted_session[0]
    assert request_human.reason not in persisted_json
    assert json.loads(persisted_json)["session"]["history"] == [
        {"action_type": "request_human", "safe_result": "human review requested"}
    ]
