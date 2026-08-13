"""End-to-end HTTP contracts for fixed offline demo runs."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import venv
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

import pytest
from fastapi.testclient import TestClient

from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web.app import RunServiceBusyError, create_demo_app
from coding_agent_harness.web.run_service import DemoRunService, RunServiceError
from coding_agent_harness.web.security import WebSettings
from coding_agent_harness.web.trace import ExecutionTraceView, TerminalStatusEvent

_ORIGIN = "https://demo.example.com"
_ACTION_HISTORY_TYPES = frozenset({"apply_patch", "policy_deny", "request_human"})


def _view(status: TaskStatus = TaskStatus.SUCCEEDED) -> ExecutionTraceView:
    return ExecutionTraceView.from_events(
        (TerminalStatusEvent(task_status=status, sequence=0),)
    )


def _csrf_token(client: TestClient) -> str:
    response = client.get("/")
    match = re.search(r"__Host-cah_csrf=([^;]+)", response.headers["set-cookie"])
    assert match is not None
    return match.group(1)


def _headers(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": f"__Host-cah_csrf={token}",
        "Host": "demo.example.com",
        "Origin": _ORIGIN,
    }


def _post(client: TestClient, scenario_id: str, token: str):
    return client.post(
        f"/scenarios/{scenario_id}/runs",
        content=f"csrf_token={token}",
        headers=_headers(token),
    )


@pytest.fixture(scope="module")
def worker_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Make the isolated child resolve this worktree rather than another checkout."""
    environment = tmp_path_factory.mktemp("isolated-worker") / "environment"
    builder = venv.EnvBuilder(system_site_packages=True, with_pip=False)
    context = builder.ensure_directories(environment)
    builder.create(environment)
    source_root = Path(__file__).parents[3] / "src"
    python = Path(context.env_exe)
    site_packages = Path(
        subprocess.run(
            (
                str(python),
                "-I",
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    )
    (site_packages / "cah_d3_source.pth").write_text(
        f"{source_root}\n", encoding="utf-8"
    )
    scripted_mock_count_path = environment / "scripted-mock-calls.txt"
    (site_packages / "sitecustomize.py").write_text(
        dedent(
            f"""
            import atexit
            import socket
            import subprocess
            from pathlib import Path

            import keyring
            import coding_agent_harness.composition as composition
            from coding_agent_harness.adapters.credentials.keyring_store import KeyringCredentialStore
            from coding_agent_harness.adapters.llm import openai_factory
            from coding_agent_harness.adapters.llm.openai_factory import OpenAIClientFactory
            from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM

            _count_path = Path({str(scripted_mock_count_path)!r})
            _calls = 0
            _original_generate = ScriptedMockLLM.generate
            _original_popen = subprocess.Popen

            def _forbidden(capability):
                def _raise(*args, **kwargs):
                    del args, kwargs
                    raise AssertionError(f"offline audit guard: {{capability}}")
                return _raise

            def _counted_generate(self, context):
                global _calls
                _calls += 1
                return _original_generate(self, context)

            def _guarded_popen(args, *positional, **keywords):
                command = tuple(str(part).casefold() for part in args)
                executable = Path(command[0]).name if command else ""
                forbidden_git_actions = {{"remote", "clone", "fetch", "pull", "push", "ls-remote", "submodule"}}
                if executable in {{"git", "git.exe"}} and any(
                    part in forbidden_git_actions for part in command[1:]
                ):
                    raise AssertionError("offline audit guard: remote or network Git action")
                return _original_popen(args, *positional, **keywords)

            ScriptedMockLLM.generate = _counted_generate
            composition.build_real_llm = _forbidden("real provider construction")
            openai_factory.OpenAI = _forbidden("OpenAI construction")
            OpenAIClientFactory.__init__ = _forbidden("OpenAI client factory construction")
            OpenAIClientFactory.create = _forbidden("OpenAI client factory call")
            KeyringCredentialStore.__init__ = _forbidden("keyring construction")
            keyring.get_password = _forbidden("keyring read")
            keyring.set_password = _forbidden("keyring write")
            keyring.delete_password = _forbidden("keyring delete")
            socket.create_connection = _forbidden("network connection")
            subprocess.Popen = _guarded_popen

            @atexit.register
            def _write_count():
                _count_path.write_text(str(_calls), encoding="ascii")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    imported = subprocess.run(
        (
            str(python),
            "-I",
            "-c",
            "import coding_agent_harness.web.worker as w; print(w.__file__)",
        ),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert (
        source_root.as_posix().casefold()
        in imported.stdout.replace("\\", "/").casefold()
    )
    assert scripted_mock_count_path.read_text(encoding="ascii") == "0"
    return python


@pytest.fixture(scope="module")
def scripted_mock_count_path(worker_python: Path) -> Path:
    return worker_python.parent.parent / "scripted-mock-calls.txt"


@dataclass
class _CapturedRun:
    scenario_id: str
    request_root_parent: Path
    view: ExecutionTraceView
    snapshot: Path
    action_history: tuple[str, ...]


class _InspectingDemoRunService(DemoRunService):
    """Run the production service while recording only fixed post-run evidence."""

    def __init__(self, *, snapshot_root: Path, trusted_python: Path) -> None:
        self.captured: list[_CapturedRun] = []
        self._snapshot_root = snapshot_root
        super().__init__(
            scenario_registry=ScenarioRegistry(),
            trusted_python=trusted_python,
            startup_environment={
                **os.environ,
                "OPENAI_API_KEY": "must-not-reach-the-offline-worker",
                "OPENAI_BASE_URL": "https://provider.invalid",
                "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
                "GIT_CONFIG_GLOBAL": "C:/must-not-reach-worker.gitconfig",
            },
            cleanup=self._capture_then_cleanup,
        )

    def _capture_then_cleanup(self, request_root: Path) -> None:
        snapshot = self._snapshot_root / request_root.name
        shutil.copytree(request_root, snapshot)
        self._cleanup_request_root(request_root)

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        view = super().run_scenario(scenario_id, request_root_parent)
        snapshot = next(self._snapshot_root.iterdir())
        with sqlite3.connect(snapshot / "data" / "state.sqlite3") as connection:
            (state_json,) = connection.execute(
                "SELECT data_json FROM feedback_states"
            ).fetchone()
        state = json.loads(state_json)
        action_history = tuple(
            entry["action_type"] for entry in state["session"]["history"]
        )
        self.captured.append(
            _CapturedRun(
                scenario_id, request_root_parent, view, snapshot, action_history
            )
        )
        return view


@pytest.mark.parametrize(
    ("scenario_id", "expected_display", "terminal_status", "llm_calls"),
    (
        (
            "feedback_success",
            (
                "action selected: apply_patch",
                "test completed: failed",
                "feedback produced: initial_failure",
                "action selected: apply_patch",
                "test completed: passed",
                "feedback produced: passed",
                "terminal status: succeeded",
            ),
            TaskStatus.SUCCEEDED,
            2,
        ),
        (
            "governance_denied",
            (
                "action selected: apply_patch",
                "policy decision: deny (test_asset_protection)",
                "terminal status: stopped",
            ),
            TaskStatus.STOPPED,
            1,
        ),
        (
            "human_review_pause",
            (
                "action selected: request_human",
                "terminal status: paused_for_human",
            ),
            TaskStatus.PAUSED_FOR_HUMAN,
            1,
        ),
    ),
)
def test_post_runs_real_worker_and_renders_the_validated_fixed_trace(
    tmp_path: Path,
    worker_python: Path,
    scripted_mock_count_path: Path,
    scenario_id: str,
    expected_display: tuple[str, ...],
    terminal_status: TaskStatus,
    llm_calls: int,
) -> None:
    """One CSRF-protected POST must synchronously return its fixed worker trace."""
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    scripted_mock_count_path.unlink(missing_ok=True)
    service = _InspectingDemoRunService(
        snapshot_root=snapshot_root, trusted_python=worker_python
    )
    assert {
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "PYTHON_KEYRING_BACKEND",
        "GIT_CONFIG_GLOBAL",
    }.isdisjoint(service._environment)
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin=_ORIGIN),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )

    with TestClient(app, base_url=_ORIGIN) as client:
        response = _post(client, scenario_id, _csrf_token(client))

    assert response.status_code == 200
    assert "run_started" not in response.text
    assert f"Terminal status: {terminal_status.value}" in response.text
    for display_text in expected_display:
        assert display_text in response.text

    (captured,) = service.captured
    assert captured.scenario_id == scenario_id
    assert captured.view.terminal_status is terminal_status
    assert tuple(
        captured.view.display_text(event) for event in captured.view.events
    ) == (expected_display)
    ScenarioRegistry().get(scenario_id).trace_contract.validate(captured.view.events)
    assert tuple(event.sequence for event in captured.view.events) == tuple(
        range(len(expected_display))
    )

    # Every fixed model response becomes exactly one persisted selected/denied action.
    assert (
        sum(
            action_type in _ACTION_HISTORY_TYPES
            for action_type in captured.action_history
        )
        == llm_calls
    )
    assert scripted_mock_count_path.read_text(encoding="ascii") == str(llm_calls)
    assert "must-not-reach-the-offline-worker" not in response.text
    assert "https://provider.invalid" not in response.text
    assert "human review required for high-impact change" not in response.text
    assert "Modify the test file to always pass." not in response.text
    assert "return a + b" not in response.text

    git_environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT")
        if key in os.environ
    }
    git_environment.update(
        {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    remote = subprocess.run(
        ("git", "remote", "-v"),
        cwd=captured.snapshot / "repository",
        env=git_environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert remote.stdout == ""
    assert not captured.request_root_parent.exists()


def test_real_worker_cleanup_removes_read_only_artifact(
    tmp_path: Path,
    worker_python: Path,
) -> None:
    """A real worker result remains successful when cleanup sees a read-only file."""

    def cleanup(request_root: Path) -> None:
        readonly = request_root / "data" / "worker-readonly.txt"
        readonly.write_bytes(b"worker artifact")
        readonly.chmod(0o400)
        (request_root / "data").chmod(0o500)
        (request_root / "cwd").chmod(0o500)
        DemoRunService._cleanup_request_root(request_root)

    service = DemoRunService(
        scenario_registry=ScenarioRegistry(),
        trusted_python=worker_python,
        cleanup=cleanup,
    )

    view = service.run_scenario("human_review_pause", tmp_path)

    assert view.events
    assert not tuple(tmp_path.iterdir())


@dataclass
class _RecordingRunService:
    calls: list[Path] = field(default_factory=list)

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        del scenario_id
        self.calls.append(request_root_parent)
        return _view()


def test_each_post_uses_a_fresh_parent_and_removes_it_after_the_service_returns() -> (
    None
):
    """A shared system temporary directory would retain request lifecycle state."""
    service = _RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin=_ORIGIN),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )

    with TestClient(app, base_url=_ORIGIN) as client:
        first = _post(client, "feedback_success", _csrf_token(client))
        second = _post(client, "human_review_pause", _csrf_token(client))

    assert [response.status_code for response in (first, second)] == [200, 200]
    assert len(set(service.calls)) == 2
    assert all(
        not request_root_parent.exists() for request_root_parent in service.calls
    )


@dataclass
class _FailingRunService:
    failure: Exception
    calls: int = 0

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        del scenario_id, request_root_parent
        self.calls += 1
        raise self.failure


@dataclass
class _RetainingFailureRunService:
    failure_code: str
    request_root_parent: Path | None = None
    retained_child: Path | None = None

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        del scenario_id
        self.request_root_parent = request_root_parent
        self.retained_child = request_root_parent / "cah-run-retained-quarantine"
        self.retained_child.mkdir()
        (self.retained_child / "worker-state").write_text("private", encoding="ascii")
        raise RunServiceError(self.failure_code)  # type: ignore[arg-type]


@pytest.mark.parametrize("failure_code", ("cleanup_failed", "termination_unconfirmed"))
def test_unsafe_run_failures_retain_the_quarantined_child_without_leaking_its_path(
    failure_code: str,
) -> None:
    """The HTTP parent must not override D1's retained-root safety decision."""
    service = _RetainingFailureRunService(failure_code)
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin=_ORIGIN),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )

    try:
        with TestClient(app, base_url=_ORIGIN) as client:
            response = _post(client, "human_review_pause", _csrf_token(client))

        assert response.status_code == 500
        assert response.text == failure_code
        assert service.request_root_parent is not None
        assert service.retained_child is not None
        assert service.retained_child.is_dir()
        assert (service.retained_child / "worker-state").read_text(
            encoding="ascii"
        ) == "private"
        assert str(service.request_root_parent) not in response.text
        assert str(service.retained_child) not in response.text
    finally:
        if (
            service.request_root_parent is not None
            and service.request_root_parent.exists()
        ):
            shutil.rmtree(service.request_root_parent)


@pytest.mark.parametrize(
    ("failure", "status_code", "response_code"),
    (
        (RunServiceBusyError(), 503, "busy"),
        (RunServiceError("timeout"), 504, "timeout"),
        (RunServiceError("cleanup_failed"), 500, "cleanup_failed"),
        (RunServiceError("trace_incomplete"), 500, "trace_incomplete"),
        (RunServiceError("worker_lifecycle_invalid"), 500, "worker_lifecycle_invalid"),
        (RunServiceError("termination_unconfirmed"), 500, "termination_unconfirmed"),
        (RunServiceError("internal"), 500, "internal"),
        (RuntimeError("private error detail"), 500, "internal_error"),
    ),
)
def test_run_service_outcomes_have_only_fixed_http_responses(
    failure: Exception, status_code: int, response_code: str
) -> None:
    """The HTTP boundary preserves D1's fixed codes without leaking exception text."""
    service = _FailingRunService(failure)
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin=_ORIGIN),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )

    with TestClient(app, base_url=_ORIGIN) as client:
        response = _post(client, "feedback_success", _csrf_token(client))

    assert response.status_code == status_code
    assert response.text == response_code
    assert "private error detail" not in response.text
    assert service.calls == 1


def test_browser_and_ipc_cannot_submit_actions_or_reach_human_control_endpoints() -> (
    None
):
    """The only POST input is CSRF; demo runs never expose approve/reject/resume."""
    service = _RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin=_ORIGIN),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )

    with TestClient(app, base_url=_ORIGIN) as client:
        token = _csrf_token(client)
        action_response = client.post(
            "/scenarios/feedback_success/runs",
            content=f"csrf_token={token}&actions=apply_patch",
            headers=_headers(token),
        )
        endpoint_responses = [
            client.post(path)
            for path in (
                "/scenarios/human_review_pause/approve",
                "/scenarios/human_review_pause/reject",
                "/scenarios/human_review_pause/resume",
            )
        ]

    assert action_response.status_code == 400
    assert [response.status_code for response in endpoint_responses] == [404, 404, 404]
    assert service.calls == []
