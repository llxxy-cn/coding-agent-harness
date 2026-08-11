"""Fail-closed HTTP boundary for the fixed offline demo scenarios."""

from __future__ import annotations

import ipaddress
import logging
import re
import secrets
import string
import tempfile
from collections.abc import Iterable
from html import escape
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qsl, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from coding_agent_harness.demo.scenarios import ScenarioRegistry

from .security import (
    CSRF_COOKIE_ATTRIBUTES,
    CSRF_COOKIE_NAME,
    WebSettings,
    compare_csrf_nonce,
    generate_csrf_nonce,
    validate_csrf_body,
    validate_host_header,
)
from .trace import ExecutionTraceView

_FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"
_MAX_FORM_BODY_BYTES = 4096
_CSP = "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
_HOSTNAME_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?\Z"
)
_IPV6_AUTHORITY_PATTERN = re.compile(r"\[([0-9A-Fa-f:.]+)\](?::([0-9]+))?\Z")
_CSRF_NONCE_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")
_LOGGER = logging.getLogger(__name__)
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
_RUN_SERVICE_ERROR_STATUSES = {
    "timeout": 504,
    "cleanup_failed": 500,
    "trace_incomplete": 500,
    "worker_lifecycle_invalid": 500,
    "termination_unconfirmed": 500,
    "internal": 500,
}
_RETAIN_REQUEST_ROOT_PARENT_ERRORS = frozenset(
    {"cleanup_failed", "termination_unconfirmed"}
)


class RunServiceProtocol(Protocol):
    """The later lifecycle service; C1 supplies no worker implementation."""

    def run_scenario(
        self, scenario_id: str, request_root_parent: Path
    ) -> ExecutionTraceView: ...


class RunServiceBusyError(RuntimeError):
    """A sanitized signal that the later global run lock was unavailable."""


def _security_response(status_code: int, code: str) -> PlainTextResponse:
    """Return a fixed public failure without request, exception, or trace details."""
    _LOGGER.warning("event_id=%s code=%s", secrets.token_hex(16), code)
    return PlainTextResponse(code, status_code=status_code)


def _single_raw_header(request: Request, name: str) -> str | None:
    """Return one raw header value only; duplicates are unsafe at a security boundary."""
    expected_name = name.encode("ascii")
    values = [
        value.decode("latin-1")
        for header_name, value in request.scope.get("headers", [])
        if header_name.lower() == expected_name
    ]
    return values[0] if len(values) == 1 else None


def _raw_header_values(request: Request, name: str) -> tuple[str, ...]:
    """Read raw ASGI values without combining duplicate security-sensitive headers."""
    expected_name = name.encode("ascii")
    return tuple(
        value.decode("latin-1")
        for header_name, value in request.scope.get("headers", [])
        if header_name.lower() == expected_name
    )


def _is_valid_raw_authority(authority: str) -> bool:
    """Accept only an RFC-style Host authority, never a URL or userinfo-bearing form."""
    if (
        not authority
        or not authority.isascii()
        or authority != authority.strip()
        or any(character in authority for character in "/?#@")
    ):
        return False
    if authority.startswith("["):
        match = _IPV6_AUTHORITY_PATTERN.fullmatch(authority)
        if match is None:
            return False
        try:
            ipaddress.IPv6Address(match.group(1))
        except ValueError:
            return False
        port = match.group(2)
    else:
        if authority.count(":") > 1:
            return False
        hostname, separator, port = authority.partition(":")
        if _HOSTNAME_PATTERN.fullmatch(hostname) is None:
            return False
        if not separator:
            return True
    if port is None:
        return True
    if not port.isdecimal() or len(port) > 5 or not port.strip("0"):
        return False
    return len(port) < 5 or port <= "65535"


def _is_valid_csrf_nonce(value: str) -> bool:
    """Keep compare_digest total by accepting only URL-safe ASCII nonce values."""
    return value.isascii() and _CSRF_NONCE_PATTERN.fullmatch(value) is not None


def _single_csrf_cookie(request: Request) -> str | None:
    """Find precisely one CSRF cookie across all Cookie headers and cookie pairs."""
    values: list[str] = []
    for cookie_header in _raw_header_values(request, "cookie"):
        for pair in cookie_header.split(";"):
            name, separator, value = pair.strip().partition("=")
            if separator and name == CSRF_COOKIE_NAME:
                values.append(value)
    if len(values) != 1 or not _is_valid_csrf_nonce(values[0]):
        return None
    return values[0]


async def _read_limited_body(request: Request) -> bytes | None:
    """Read no more than the fixed request-body limit, chunk by chunk."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_FORM_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _has_invalid_percent_encoding(body: bytes) -> bool:
    """Reject malformed form octets rather than silently accepting ambiguous input."""
    hex_digits = set(string.hexdigits.encode("ascii"))
    index = 0
    while index < len(body):
        if body[index] == ord("%"):
            if index + 2 >= len(body) or any(
                value not in hex_digits for value in body[index + 1 : index + 3]
            ):
                return True
            index += 3
        else:
            index += 1
    return False


def _parse_csrf_form(body: bytes) -> str | None:
    """Return the single CSRF value, rejecting duplicates and every other field."""
    if _has_invalid_percent_encoding(body):
        return None
    try:
        decoded = body.decode("ascii")
        fields = parse_qsl(
            decoded,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeDecodeError, ValueError):
        return None
    if len(fields) != 1:
        return None
    name, token = fields[0]
    if (
        name != "csrf_token"
        or not validate_csrf_body({name: token})
        or not _is_valid_csrf_nonce(token)
    ):
        return None
    return token


def _scenario_list_page(scenario_ids: Iterable[str], csrf_token: str) -> str:
    """Render the minimal C1 page without depending on the C2 template assets."""
    forms = "".join(
        "<li>"
        f"<span>{escape(scenario_id)}</span>"
        f'<form method="post" action="/scenarios/{escape(scenario_id)}/runs">'
        f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
        '<button type="submit">Run</button>'
        "</form>"
        "</li>"
        for scenario_id in scenario_ids
    )
    return f"<!doctype html><html><body><h1>Fixed demo scenarios</h1><ul>{forms}</ul></body></html>"


def create_demo_app(
    *,
    web_settings: WebSettings,
    scenario_registry: ScenarioRegistry,
    run_service: RunServiceProtocol,
) -> FastAPI:
    """Create the C1 app with all untrusted-request checks before service invocation."""
    app = FastAPI()
    canonical_authority = urlparse(web_settings.canonical_origin).netloc

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - this is the final sanitized HTTP boundary.
            response = _security_response(500, "internal_error")
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = _CSP
        return response

    @app.get("/", response_class=HTMLResponse)
    async def list_scenarios() -> HTMLResponse:
        csrf_token = generate_csrf_nonce()
        response = HTMLResponse(_scenario_list_page(scenario_registry, csrf_token))
        response.set_cookie(CSRF_COOKIE_NAME, csrf_token, **CSRF_COOKIE_ATTRIBUTES)
        return response

    @app.post("/scenarios/{scenario_id}/runs")
    async def start_scenario(scenario_id: str, request: Request) -> Response:
        if scenario_id not in scenario_registry:
            return _security_response(404, "not_found")
        origin = _single_raw_header(request, "origin")
        if origin != web_settings.canonical_origin:
            return _security_response(403, "forbidden")
        host = _single_raw_header(request, "host")
        if host is None or not _is_valid_raw_authority(host):
            return _security_response(403, "forbidden")
        if not validate_host_header(host, canonical_authority):
            return _security_response(403, "forbidden")
        content_type = _single_raw_header(request, "content-type")
        media_type = (content_type or "").split(";", 1)[0].strip().lower()
        if media_type != _FORM_MEDIA_TYPE:
            return _security_response(415, "unsupported_media_type")
        body = await _read_limited_body(request)
        if body is None:
            return _security_response(413, "request_too_large")
        form_token = _parse_csrf_form(body)
        if form_token is None:
            return _security_response(400, "bad_request")
        cookie_token = _single_csrf_cookie(request)
        if cookie_token is None or not compare_csrf_nonce(form_token, cookie_token):
            return _security_response(403, "forbidden")

        request_root_parent = Path(tempfile.mkdtemp(prefix="cah-web-run-"))
        retain_request_root_parent = False
        try:
            try:
                trace = await run_in_threadpool(
                    run_service.run_scenario, scenario_id, Path(request_root_parent)
                )
            except RunServiceBusyError:
                return _security_response(503, "busy")
            except Exception as error:  # noqa: BLE001 - this is the final HTTP boundary.
                from .run_service import RunServiceError

                if isinstance(error, RunServiceError):
                    status_code = _RUN_SERVICE_ERROR_STATUSES.get(error.code)
                    if status_code is not None:
                        retain_request_root_parent = (
                            error.code in _RETAIN_REQUEST_ROOT_PARENT_ERRORS
                        )
                        return _security_response(status_code, error.code)
                return _security_response(500, "internal_error")
            return _TEMPLATES.TemplateResponse(
                request=request,
                name="result.html",
                context={"trace": trace},
            )
        finally:
            if not retain_request_root_parent:
                try:
                    request_root_parent.rmdir()
                except OSError:
                    pass

    return app
