from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coding_agent_harness.adapters.credentials.keyring_store import (
    KeyringCredentialStore,
)
from coding_agent_harness.adapters.llm import openai_factory
from coding_agent_harness.adapters.llm.openai_factory import OpenAIClientFactory
from coding_agent_harness.adapters.process.runner import (
    LaunchRequest,
    LaunchStatus,
    SubprocessLauncher,
)
from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web.app import create_demo_app
from coding_agent_harness.web.security import WebSettings
from coding_agent_harness.web.trace import ExecutionTraceView, TerminalStatusEvent


def _successful_view() -> ExecutionTraceView:
    return ExecutionTraceView.from_events(
        (TerminalStatusEvent(task_status=TaskStatus.SUCCEEDED, sequence=0),)
    )


class RecordingRunService:
    """C1 deliberately substitutes the later worker/run-service implementation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        self.calls.append((scenario_id, request_root_parent))
        return _successful_view()


@pytest.fixture
def client_and_service() -> tuple[TestClient, RecordingRunService]:
    service = RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )
    with TestClient(app, base_url="https://demo.example.com") as client:
        yield client, service


def _csrf_token(client: TestClient) -> str:
    response = client.get("/")
    match = re.search(r"__Host-cah_csrf=([^;]+)", response.headers["set-cookie"])
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize(
    "prohibited_field",
    ("prompt", "path", "patch", "command", "upload", "mode", "actions", "task_description"),
)
def test_browser_cannot_submit_prohibited_run_fields(
    client_and_service: tuple[TestClient, RecordingRunService], prohibited_field: str
) -> None:
    """Accepting any field other than CSRF would turn this fixed demo into a user-driven runner."""
    client, service = client_and_service
    token = _csrf_token(client)

    response = client.post(
        "/scenarios/feedback_success/runs",
        content=f"csrf_token={token}&{prohibited_field}=browser-value",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": f"__Host-cah_csrf={token}",
            "Host": "demo.example.com",
            "Origin": "https://demo.example.com",
        },
    )

    assert response.status_code == 400
    assert service.calls == []


def test_app_construction_and_valid_request_do_not_use_real_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing C1's fake service with real capabilities would violate the offline boundary."""

    def forbidden_capability(*args: object, **kwargs: object) -> object:
        raise AssertionError("the C1 app must not construct or call a real capability")

    popen_calls: list[object] = []

    def forbidden_popen(*args: object, **kwargs: object) -> object:
        popen_calls.append(args[0])
        raise AssertionError("the C1 app must not launch a child process")

    monkeypatch.setattr(openai_factory, "OpenAI", forbidden_capability)
    monkeypatch.setattr(OpenAIClientFactory, "__init__", forbidden_capability)
    monkeypatch.setattr(KeyringCredentialStore, "__init__", forbidden_capability)
    monkeypatch.setattr("socket.create_connection", forbidden_capability)
    monkeypatch.setattr(subprocess, "run", forbidden_capability)
    monkeypatch.setattr(subprocess, "Popen", forbidden_popen)

    service = RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )
    with TestClient(app, base_url="https://demo.example.com") as client:
        token = _csrf_token(client)
        response = client.post(
            "/scenarios/feedback_success/runs",
            content=f"csrf_token={token}",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": f"__Host-cah_csrf={token}",
                "Host": "demo.example.com",
                "Origin": "https://demo.example.com",
            },
        )

    assert response.status_code == 200
    assert [scenario_id for scenario_id, _ in service.calls] == ["feedback_success"]
    assert popen_calls == []


def test_popen_guard_intercepts_the_actual_git_launcher_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The app test's Popen guard must cover the launcher Git uses, not only subprocess.run."""
    popen_calls: list[object] = []

    def blocked_popen(*args: object, **kwargs: object) -> object:
        popen_calls.append(args[0])
        raise OSError("process launch blocked by capability test")

    monkeypatch.setattr(subprocess, "Popen", blocked_popen)

    result = SubprocessLauncher().launch(
        LaunchRequest(
            argv=("git", "remote", "-v"),
            cwd=tmp_path,
            shell=False,
            env={},
            timeout_seconds=1,
        )
    )

    assert popen_calls == [["git", "remote", "-v"]]
    assert result.status is LaunchStatus.ENVIRONMENT_ERROR
