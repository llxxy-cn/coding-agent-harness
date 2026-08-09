"""Web security primitives: Host/Origin authority validation and CSRF foundation.

Forwarded and X-Forwarded-* headers are intentionally NOT trusted here. Any
reverse-proxy trust boundary is an application-level concern handled by the
ASGI server configuration, not by this module.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

CSRF_COOKIE_NAME = "__Host-cah_csrf"

CSRF_COOKIE_ATTRIBUTES = {
    "secure": True,
    "httponly": True,
    "samesite": "strict",
    "path": "/",
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


def normalize_authority(host: str) -> str:
    """Normalize a Host header authority: lowercase hostname, omit port 443, retain non-default port."""
    parsed = urlparse("//" + host)
    if parsed.username or parsed.password:
        raise ValueError("authority must not contain userinfo")
    hostname = parsed.hostname
    if not hostname:
        return host.lower()
    port = parsed.port
    if port is None or port == 443:
        return hostname
    return f"{hostname}:{port}"


def validate_host_header(host: str, canonical: str) -> bool:
    """Exact match after normalization. Case-insensitive. Port 443 normalized."""
    try:
        return normalize_authority(host) == normalize_authority(canonical)
    except ValueError:
        return False


class WebSettings(_FrozenModel):
    canonical_origin: StrictStr

    @field_validator("canonical_origin")
    @classmethod
    def validate_canonical_origin(cls, v: str) -> str:
        """Validate canonical HTTPS origin."""
        parsed = urlparse(v)
        if parsed.scheme != "https":
            raise ValueError("canonical_origin must use https scheme")
        if parsed.username or parsed.password:
            raise ValueError("canonical_origin must not contain userinfo")
        if not parsed.hostname:
            raise ValueError("canonical_origin must have a hostname")
        if parsed.path not in ("", "/"):
            raise ValueError("canonical_origin must not contain a path")
        if parsed.query:
            raise ValueError("canonical_origin must not contain a query")
        if parsed.fragment:
            raise ValueError("canonical_origin must not contain a fragment")
        hostname = parsed.hostname.lower()
        port = parsed.port
        if port is None or port == 443:
            return f"https://{hostname}"
        return f"https://{hostname}:{port}"


def generate_csrf_nonce() -> str:
    """Generate a CSRF nonce using secrets.token_urlsafe(32)."""
    return secrets.token_urlsafe(32)


def compare_csrf_nonce(a: str, b: str) -> bool:
    """Constant-time comparison of two CSRF nonces."""
    return secrets.compare_digest(a, b)


def validate_csrf_body(parsed_body: dict[str, object]) -> bool:
    """Validate that the parsed body has exactly one csrf_token field and no extra fields."""
    if set(parsed_body.keys()) != {"csrf_token"}:
        return False
    token = parsed_body["csrf_token"]
    return isinstance(token, str) and token != ""
