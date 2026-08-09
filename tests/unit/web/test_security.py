import pytest
from pydantic import ValidationError

from coding_agent_harness.web.security import (
    CSRF_COOKIE_ATTRIBUTES,
    CSRF_COOKIE_NAME,
    WebSettings,
    compare_csrf_nonce,
    generate_csrf_nonce,
    normalize_authority,
    validate_csrf_body,
    validate_host_header,
)


def test_websettings_accepts_valid_https_origin() -> None:
    settings = WebSettings(canonical_origin="https://demo.example.com")
    assert settings.canonical_origin == "https://demo.example.com"


def test_websettings_rejects_http_scheme() -> None:
    with pytest.raises(ValidationError):
        WebSettings(canonical_origin="http://demo.example.com")


def test_websettings_rejects_userinfo() -> None:
    with pytest.raises(ValidationError):
        WebSettings(canonical_origin="https://user:pass@demo.example.com")


def test_websettings_rejects_path() -> None:
    with pytest.raises(ValidationError):
        WebSettings(canonical_origin="https://demo.example.com/foo")


def test_websettings_rejects_query() -> None:
    with pytest.raises(ValidationError):
        WebSettings(canonical_origin="https://demo.example.com?key=value")


def test_websettings_rejects_fragment() -> None:
    with pytest.raises(ValidationError):
        WebSettings(canonical_origin="https://demo.example.com#section")


def test_websettings_lowercases_hostname() -> None:
    settings = WebSettings(canonical_origin="https://DEMO.EXAMPLE.COM")
    assert settings.canonical_origin == "https://demo.example.com"


def test_websettings_normalizes_port_443_omitted() -> None:
    settings = WebSettings(canonical_origin="https://demo.example.com:443")
    assert settings.canonical_origin == "https://demo.example.com"


def test_websettings_retains_non_default_port() -> None:
    settings = WebSettings(canonical_origin="https://demo.example.com:8443")
    assert settings.canonical_origin == "https://demo.example.com:8443"


def test_websettings_is_frozen() -> None:
    settings = WebSettings(canonical_origin="https://demo.example.com")
    with pytest.raises(Exception):
        settings.canonical_origin = "https://evil.example.com"  # type: ignore[misc]


def test_csrf_cookie_name_constant() -> None:
    assert CSRF_COOKIE_NAME == "__Host-cah_csrf"


def test_normalize_authority_lowercases_hostname() -> None:
    assert normalize_authority("DEMO.EXAMPLE.COM") == "demo.example.com"


def test_normalize_authority_omits_port_443() -> None:
    assert normalize_authority("demo.example.com:443") == "demo.example.com"


def test_normalize_authority_retains_non_default_port() -> None:
    assert normalize_authority("demo.example.com:8443") == "demo.example.com:8443"


def test_normalize_authority_rejects_userinfo() -> None:
    with pytest.raises(ValueError):
        normalize_authority("evil.com@demo.example.com")


def test_validate_host_header_exact_match() -> None:
    assert validate_host_header("demo.example.com", "demo.example.com") is True


def test_validate_host_header_case_insensitive() -> None:
    assert validate_host_header("DEMO.EXAMPLE.COM", "demo.example.com") is True


def test_validate_host_header_port_443_normalized() -> None:
    assert validate_host_header("demo.example.com:443", "demo.example.com") is True


def test_validate_host_header_mismatch_rejected() -> None:
    assert validate_host_header("evil.example.com", "demo.example.com") is False


def test_validate_host_header_port_mismatch_rejected() -> None:
    assert validate_host_header("demo.example.com:8443", "demo.example.com") is False


def test_validate_host_header_userinfo_rejected() -> None:
    assert validate_host_header("evil.com@demo.example.com", "demo.example.com") is False


def test_generate_csrf_nonce_returns_nonempty_string() -> None:
    nonce = generate_csrf_nonce()
    assert isinstance(nonce, str)
    assert len(nonce) > 0


def test_generate_csrf_nonce_returns_different_values_each_call() -> None:
    a = generate_csrf_nonce()
    b = generate_csrf_nonce()
    assert a != b


def test_compare_csrf_nonce_equal_values() -> None:
    assert compare_csrf_nonce("abc", "abc") is True


def test_compare_csrf_nonce_unequal_values() -> None:
    assert compare_csrf_nonce("abc", "def") is False


def test_validate_csrf_body_valid() -> None:
    assert validate_csrf_body({"csrf_token": "some-nonce"}) is True


def test_validate_csrf_body_rejects_extra_fields() -> None:
    assert validate_csrf_body({"csrf_token": "some-nonce", "extra": "field"}) is False


def test_validate_csrf_body_rejects_missing_csrf_token() -> None:
    assert validate_csrf_body({}) is False


def test_validate_csrf_body_rejects_empty_token() -> None:
    assert validate_csrf_body({"csrf_token": ""}) is False


def test_validate_csrf_body_rejects_non_string_token() -> None:
    assert validate_csrf_body({"csrf_token": 123}) is False


def test_csrf_cookie_attributes() -> None:
    assert CSRF_COOKIE_ATTRIBUTES["secure"] is True
    assert CSRF_COOKIE_ATTRIBUTES["httponly"] is True
    assert CSRF_COOKIE_ATTRIBUTES["samesite"] == "strict"
    assert CSRF_COOKIE_ATTRIBUTES["path"] == "/"
    assert "domain" not in CSRF_COOKIE_ATTRIBUTES
