from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from coding_agent_harness.demo.scenarios import ScenarioRegistry
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.web.app import RunServiceBusyError, create_demo_app
from coding_agent_harness.web.security import WebSettings
from coding_agent_harness.web.trace import ExecutionTraceView, TerminalStatusEvent


def _successful_view() -> ExecutionTraceView:
    return ExecutionTraceView.from_events(
        (TerminalStatusEvent(task_status=TaskStatus.SUCCEEDED, sequence=0),)
    )


class RecordingRunService:
    """A C1 boundary fake: records only calls that passed all validation."""

    def __init__(self, failure: Exception | None = None) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.failure = failure

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        self.calls.append((scenario_id, request_root_parent))
        if self.failure is not None:
            raise self.failure
        return _successful_view()


@pytest.fixture
def run_service() -> RecordingRunService:
    return RecordingRunService()


@pytest.fixture
def client(run_service: RecordingRunService) -> TestClient:
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=run_service,
    )
    with TestClient(app, base_url="https://demo.example.com") as test_client:
        yield test_client


def _csrf_token(response) -> str:
    match = re.search(r"__Host-cah_csrf=([^;]+)", response.headers["set-cookie"])
    assert match is not None
    return match.group(1)


def _headers(token: str, **overrides: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": f"__Host-cah_csrf={token}",
        "Host": "demo.example.com",
        "Origin": "https://demo.example.com",
    }
    headers.update(overrides)
    return headers


def _post(client: TestClient, token: str, **overrides: str):
    return client.post(
        "/scenarios/feedback_success/runs",
        content=f"csrf_token={token}",
        headers=_headers(token, **overrides),
    )


def test_factory_requires_keyword_dependencies() -> None:
    """Removing the keyword-only boundary would let callers omit app dependencies."""
    with pytest.raises(TypeError):
        create_demo_app(  # type: ignore[call-arg]
            WebSettings(canonical_origin="https://demo.example.com"),
            ScenarioRegistry(),
            RecordingRunService(),
        )


def test_get_lists_fixed_scenarios_and_sets_secure_csrf_cookie(
    client: TestClient,
) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'class="scenario-grid"' in response.text
    assert (
        len(re.findall(r'<article class="[^\"]*\bscenario-card\b', response.text)) == 3
    )
    assert "<h1>Fixed demo scenarios</h1><ul>" not in response.text
    for scenario_id in ("feedback_success", "governance_denied", "human_review_pause"):
        assert scenario_id in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "__host-cah_csrf=" in cookie
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert "domain=" not in cookie
    hidden = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert hidden is not None
    assert hidden.group(1) == _csrf_token(response)


def test_healthz_is_cookie_free_and_does_not_touch_demo_dependencies() -> None:
    class ExplodingRegistry:
        def __iter__(self):
            raise AssertionError("health check must not list scenarios")

    service = RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ExplodingRegistry(),  # type: ignore[arg-type]
        run_service=service,
    )
    with TestClient(app, base_url="https://demo.example.com") as health_client:
        response = health_client.get("/healthz")

    assert response.status_code == 200
    assert response.text == "ok"
    assert "set-cookie" not in response.headers
    assert service.calls == []


def test_static_assets_are_local_read_only_and_do_not_touch_demo_dependencies() -> None:
    """Static UI assets must be package-owned, cookie-free, and outside the demo flow."""

    class ExplodingRegistry:
        def __iter__(self):
            raise AssertionError("static requests must not list scenarios")

    service = RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ExplodingRegistry(),  # type: ignore[arg-type]
        run_service=service,
    )
    with TestClient(app, base_url="https://demo.example.com") as static_client:
        css = static_client.get("/static/app.css")
        script = static_client.get("/static/app.js")
        missing = static_client.get("/static/missing.css")
        traversal = static_client.get("/static/%2e%2e/app.py")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith(
        ("text/javascript", "application/javascript")
    )
    assert missing.status_code == 404
    assert traversal.status_code == 404
    assert "set-cookie" not in css.headers
    assert "set-cookie" not in script.headers
    assert service.calls == []


def test_valid_post_calls_service_after_security_checks(
    client: TestClient, run_service: RecordingRunService
) -> None:
    token = _csrf_token(client.get("/"))

    response = _post(
        client,
        token,
        **{"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )

    assert response.status_code == 200
    assert [scenario_id for scenario_id, _ in run_service.calls] == ["feedback_success"]


@pytest.mark.parametrize("host", ("DEMO.EXAMPLE.COM", "demo.example.com:443"))
def test_host_normalization_accepts_case_and_default_https_port(
    client: TestClient, run_service: RecordingRunService, host: str
) -> None:
    token = _csrf_token(client.get("/"))

    response = _post(client, token, Host=host)

    assert response.status_code == 200
    assert len(run_service.calls) == 1


@pytest.mark.parametrize(
    "origin",
    (
        "null",
        "https://DEMO.EXAMPLE.COM",
        "https://demo.example.com:443",
        "https://demo.example.com/",
    ),
)
def test_origin_requires_the_exact_canonical_string(
    client: TestClient, run_service: RecordingRunService, origin: str
) -> None:
    token = _csrf_token(client.get("/"))

    response = _post(client, token, Origin=origin)

    assert response.status_code == 403
    assert run_service.calls == []


@pytest.mark.parametrize(
    ("host", "expected_status"),
    [
        ("demo.example.com/path", 403),
        ("demo.example.com?query=value", 403),
        ("demo.example.com#fragment", 403),
        ("user@demo.example.com", 403),
        ("demo.example.com:", 403),
        ("demo.example.com:" + "9" * 10_000, 403),
        (":443", 403),
        ("demo..example.com", 403),
    ],
)
def test_raw_host_authority_rejects_non_authority_forms(
    client: TestClient,
    run_service: RecordingRunService,
    host: str,
    expected_status: int,
) -> None:
    """Permissive URL parsing could otherwise discard a hostile Host suffix before comparison."""
    token = _csrf_token(client.get("/"))

    response = _post(client, token, Host=host)

    assert response.status_code == expected_status
    assert run_service.calls == []


@pytest.mark.parametrize(
    "cookie_headers",
    (
        lambda token: [f"__Host-cah_csrf={token}; __Host-cah_csrf=other"],
        lambda token: ["__Host-cah_csrf=other", f"__Host-cah_csrf={token}"],
        lambda token: [f"__Host-cah_csrf={token}", "__Host-cah_csrf=other"],
    ),
)
def test_duplicate_csrf_cookies_fail_closed_before_service(
    client: TestClient, run_service: RecordingRunService, cookie_headers
) -> None:
    """Ambiguous duplicate cookies must not depend on header order or parser choice."""
    token = _csrf_token(client.get("/"))
    headers = [
        ("Content-Type", "application/x-www-form-urlencoded"),
        ("Host", "demo.example.com"),
        ("Origin", "https://demo.example.com"),
    ]
    headers.extend(("Cookie", value) for value in cookie_headers(token))

    response = client.post(
        "/scenarios/feedback_success/runs",
        content=f"csrf_token={token}",
        headers=headers,
    )

    assert response.status_code == 403
    assert run_service.calls == []


@pytest.mark.parametrize(
    ("duplicate_name", "expected_status"),
    [("Origin", 403), ("Host", 403), ("Content-Type", 415)],
)
def test_duplicate_security_headers_fail_closed_before_service(
    client: TestClient,
    run_service: RecordingRunService,
    duplicate_name: str,
    expected_status: int,
) -> None:
    """Selecting one duplicated security header would make proxy and app interpretations diverge."""
    token = _csrf_token(client.get("/"))
    headers = [
        ("Content-Type", "application/x-www-form-urlencoded"),
        ("Cookie", f"__Host-cah_csrf={token}"),
        ("Host", "demo.example.com"),
        ("Origin", "https://demo.example.com"),
    ]
    duplicated_value = next(value for name, value in headers if name == duplicate_name)
    headers.append((duplicate_name, duplicated_value))

    response = client.post(
        "/scenarios/feedback_success/runs",
        content=f"csrf_token={token}",
        headers=headers,
    )

    assert response.status_code == expected_status
    assert run_service.calls == []


@pytest.mark.parametrize(
    ("path", "content", "header_overrides", "expected_status"),
    [
        ("/scenarios/not-fixed/runs", "csrf_token=token", {}, 404),
        (
            "/scenarios/feedback_success/runs",
            "csrf_token=token",
            {"Origin": "https://evil.example.com"},
            403,
        ),
        (
            "/scenarios/feedback_success/runs",
            "csrf_token=token",
            {"Host": "evil.example.com"},
            403,
        ),
        (
            "/scenarios/feedback_success/runs",
            "{}",
            {"Content-Type": "application/json"},
            415,
        ),
        ("/scenarios/feedback_success/runs", "csrf_token=token", {"Cookie": ""}, 403),
        ("/scenarios/feedback_success/runs", "csrf_token=other", {}, 403),
        (
            "/scenarios/feedback_success/runs",
            "csrf_token=token&csrf_token=again",
            {},
            400,
        ),
        (
            "/scenarios/feedback_success/runs",
            "csrf_token=token&prompt=free-text",
            {},
            400,
        ),
        ("/scenarios/feedback_success/runs", "csrf_token=%ZZ", {}, 400),
        ("/scenarios/feedback_success/runs", "csrf_token=%C3%A9", {}, 400),
        ("/scenarios/feedback_success/runs", "csrf_token=token&", {}, 400),
        ("/scenarios/feedback_success/runs", "csrf_token=" + "x" * 4097, {}, 413),
    ],
)
def test_each_rejected_request_stops_before_service_invocation(
    client: TestClient,
    run_service: RecordingRunService,
    path: str,
    content: str,
    header_overrides: dict[str, str],
    expected_status: int,
) -> None:
    """Deleting a validation branch would start the fake service for invalid browser input."""
    token = _csrf_token(client.get("/"))
    content = content.replace("csrf_token=token", f"csrf_token={token}")

    response = client.post(
        path, content=content, headers=_headers(token, **header_overrides)
    )

    assert response.status_code == expected_status
    assert run_service.calls == []


def test_request_too_large_uses_the_fixed_sanitized_code(
    client: TestClient, run_service: RecordingRunService
) -> None:
    """Changing the public 413 code would expose an undocumented app-boundary contract."""
    token = _csrf_token(client.get("/"))

    response = client.post(
        "/scenarios/feedback_success/runs",
        content="csrf_token=" + "x" * 4097,
        headers=_headers(token),
    )

    assert response.status_code == 413
    assert response.text == "request_too_large"
    assert run_service.calls == []


def test_exact_body_limit_is_accepted_when_the_csrf_tokens_match(
    client: TestClient, run_service: RecordingRunService
) -> None:
    token = "x" * (4096 - len("csrf_token="))

    response = client.post(
        "/scenarios/feedback_success/runs",
        content=f"csrf_token={token}",
        headers=_headers(token),
    )

    assert response.status_code == 200
    assert len(run_service.calls) == 1


def test_streaming_body_limit_stops_after_the_over_limit_chunk() -> None:
    """Reading the full request before rejecting would allow a client to keep consuming memory."""
    service = RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )
    received = 0
    sent: list[dict[str, object]] = []
    messages = [
        {
            "type": "http.request",
            "body": b"csrf_token=" + b"x" * 4097,
            "more_body": True,
        },
        {"type": "http.request", "body": b"should-not-be-read", "more_body": False},
    ]

    async def receive() -> dict[str, object]:
        nonlocal received
        received += 1
        return messages.pop(0)

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/scenarios/feedback_success/runs",
        "raw_path": b"/scenarios/feedback_success/runs",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"cookie", b"__Host-cah_csrf=x"),
            (b"host", b"demo.example.com"),
            (b"origin", b"https://demo.example.com"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("demo.example.com", 443),
    }

    asyncio.run(app(scope, receive, send))

    assert received == 1
    assert any(message.get("status") == 413 for message in sent)
    assert service.calls == []


def test_forwarded_headers_do_not_override_host_validation(
    client: TestClient, run_service: RecordingRunService
) -> None:
    token = _csrf_token(client.get("/"))

    response = _post(
        client,
        token,
        Host="evil.example.com",
        **{
            "X-Forwarded-Host": "demo.example.com",
            "Forwarded": "host=demo.example.com",
        },
    )

    assert response.status_code == 403
    assert run_service.calls == []


def test_forwarded_headers_are_ignored_when_actual_host_is_valid(
    client: TestClient, run_service: RecordingRunService
) -> None:
    token = _csrf_token(client.get("/"))

    response = _post(client, token, **{"X-Forwarded-Host": "evil.example.com"})

    assert response.status_code == 200
    assert len(run_service.calls) == 1


def test_security_headers_apply_to_fail_closed_response(client: TestClient) -> None:
    response = client.post("/scenarios/not-fixed/runs")

    assert response.status_code == 404
    assert response.headers["referrer-policy"] == "origin"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers.get("access-control-allow-origin") != "*"


@pytest.mark.parametrize(
    ("failure", "content", "overrides", "expected_status", "expected_code", "secret"),
    [
        (None, "csrf_token=token&prompt=leak-400", {}, 400, "bad_request", "leak-400"),
        (
            None,
            "csrf_token=token",
            {"Origin": "https://evil.example.com/leak-403"},
            403,
            "forbidden",
            "leak-403",
        ),
        (
            RunServiceBusyError("leak-503"),
            "csrf_token=token",
            {},
            503,
            "busy",
            "leak-503",
        ),
        (
            RuntimeError("leak-500"),
            "csrf_token=token",
            {},
            500,
            "internal_error",
            "leak-500",
        ),
    ],
)
def test_fixed_error_responses_log_only_random_event_id_and_code(
    caplog: pytest.LogCaptureFixture,
    failure: Exception | None,
    content: str,
    overrides: dict[str, str],
    expected_status: int,
    expected_code: str,
    secret: str,
) -> None:
    """Adding request data or exception text to an error log would breach the public boundary."""
    service = RecordingRunService(failure)
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )
    with TestClient(app, base_url="https://demo.example.com") as client:
        response = client.post(
            "/scenarios/feedback_success/runs",
            content=content,
            headers=_headers("token", **overrides),
        )

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "coding_agent_harness.web.app"
    ]
    assert response.status_code == expected_status
    assert messages and len(messages) == 1
    assert re.fullmatch(rf"event_id=[0-9a-f]{{32}} code={expected_code}", messages[0])
    assert secret not in messages[0]


def test_error_event_ids_are_unique_per_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )
    with TestClient(app, base_url="https://demo.example.com") as client:
        first = client.post(
            "/scenarios/feedback_success/runs",
            content="csrf_token=token&prompt=first",
            headers=_headers("token"),
        )
        second = client.post(
            "/scenarios/feedback_success/runs",
            content="csrf_token=token&prompt=second",
            headers=_headers("token"),
        )

    event_ids = [
        re.fullmatch(r"event_id=([0-9a-f]{32}) code=bad_request", record.getMessage())
        for record in caplog.records
        if record.name == "coding_agent_harness.web.app"
    ]
    assert first.status_code == second.status_code == 400
    assert all(match is not None for match in event_ids)
    assert len({match.group(1) for match in event_ids if match is not None}) == 2


def test_unexpected_route_error_is_sanitized_and_has_security_headers() -> None:
    class ExplodingRegistry:
        def __contains__(self, scenario_id: object) -> bool:
            raise RuntimeError("untrusted exception text")

        def __iter__(self):
            return iter(())

    service = RecordingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ExplodingRegistry(),  # type: ignore[arg-type]
        run_service=service,
    )
    with TestClient(
        app, base_url="https://demo.example.com", raise_server_exceptions=False
    ) as client:
        response = client.post(
            "/scenarios/feedback_success/runs",
            content="csrf_token=token",
            headers=_headers("token"),
        )

    assert response.status_code == 500
    assert response.text == "internal_error"
    assert response.headers["referrer-policy"] == "origin"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert service.calls == []


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_body"),
    [
        (RunServiceBusyError(), 503, "busy"),
        (RuntimeError("private implementation detail"), 500, "internal_error"),
    ],
)
def test_run_service_failures_are_sanitized(
    failure: Exception, expected_status: int, expected_body: str
) -> None:
    """Leaking a service exception or mapping a busy lock to success would be a public-boundary bug."""
    service = RecordingRunService(failure)
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )
    with TestClient(app, base_url="https://demo.example.com") as client:
        token = _csrf_token(client.get("/"))
        response = _post(client, token)

    assert response.status_code == expected_status
    assert response.text == expected_body
    assert len(service.calls) == 1


class NonBlockingRunService:
    """A lock-1 fake whose first run blocks only its worker thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView:
        del scenario_id, request_root_parent
        self.calls += 1
        if not self._lock.acquire(blocking=False):
            raise RunServiceBusyError()
        self.entered.set()
        try:
            self.release.wait(timeout=0.2)
            return _successful_view()
        finally:
            self._lock.release()


def test_overlapping_posts_do_not_block_the_event_loop() -> None:
    service = NonBlockingRunService()
    app = create_demo_app(
        web_settings=WebSettings(canonical_origin="https://demo.example.com"),
        scenario_registry=ScenarioRegistry(),
        run_service=service,
    )

    async def post_valid_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://demo.example.com"
        ) as client:
            token = _csrf_token(await client.get("/"))
            return await client.post(
                "/scenarios/feedback_success/runs",
                content=f"csrf_token={token}",
                headers=_headers(token),
            )

    async def run_concurrently() -> tuple[httpx.Response, httpx.Response]:
        first = asyncio.create_task(post_valid_request())
        await asyncio.to_thread(service.entered.wait, 1)
        second = await post_valid_request()
        service.release.set()
        return await first, second

    first, second = asyncio.run(run_concurrently())

    assert sorted((first.status_code, second.status_code)) == [200, 503]
    assert service.calls == 2
