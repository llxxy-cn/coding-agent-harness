from __future__ import annotations

from click import unstyle
from typer.testing import CliRunner

from coding_agent_harness.cli.app import build_cli


def _capture_uvicorn(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(app, **kwargs) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    return captured


def test_web_help_describes_required_origin_and_network_options(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    result = CliRunner().invoke(
        build_cli(), ["web", "--help"], color=True, terminal_width=100
    )

    assert result.exit_code == 0
    output = unstyle(result.output)
    assert "\x1b[" in result.output
    for option in ("--origin", "--host", "--port", "--tls-cert", "--tls-key"):
        assert option in output


def test_web_requires_origin(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    result = CliRunner().invoke(build_cli(), ["web"], color=True, terminal_width=100)

    assert result.exit_code != 0
    output = unstyle(result.output)
    assert "\x1b[" in result.output
    assert "Missing option" in output
    assert "--origin" in output


def test_web_rejects_non_https_origin() -> None:
    result = CliRunner().invoke(
        build_cli(), ["web", "--origin", "http://demo.example.com"]
    )

    assert result.exit_code != 0
    assert "https" in result.stdout.lower()


def test_web_rejects_partial_tls_configuration() -> None:
    result = CliRunner().invoke(
        build_cli(),
        ["web", "--origin", "https://demo.example.com", "--tls-cert", "cert.pem"],
    )

    assert result.exit_code != 0
    assert "together" in result.stdout.lower()


def test_web_rejects_public_host_without_tls() -> None:
    result = CliRunner().invoke(
        build_cli(),
        ["web", "--origin", "https://demo.example.com", "--host", "0.0.0.0"],
    )

    assert result.exit_code != 0
    assert "public" in result.stdout.lower()


def test_web_rejects_invalid_host_and_port() -> None:
    runner = CliRunner()

    invalid_host = runner.invoke(
        build_cli(),
        ["web", "--origin", "https://demo.example.com", "--host", "bad host"],
    )
    invalid_port = runner.invoke(
        build_cli(),
        ["web", "--origin", "https://demo.example.com", "--port", "70000"],
    )

    assert invalid_host.exit_code != 0
    assert invalid_port.exit_code != 0


def test_web_loopback_without_tls_starts_one_unproxied_worker(monkeypatch) -> None:
    captured = _capture_uvicorn(monkeypatch)

    result = CliRunner().invoke(
        build_cli(),
        [
            "web",
            "--origin",
            "https://demo.example.com",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
    )

    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8001
    assert captured["workers"] == 1
    assert "ssl_certfile" not in captured and "ssl_keyfile" not in captured
    assert captured["proxy_headers"] is False
    assert captured["app"] is not None


def test_web_passes_complete_tls_configuration_to_uvicorn(monkeypatch) -> None:
    captured = _capture_uvicorn(monkeypatch)

    result = CliRunner().invoke(
        build_cli(),
        [
            "web",
            "--origin",
            "https://demo.example.com",
            "--host",
            "0.0.0.0",
            "--port",
            "8443",
            "--tls-cert",
            "cert.pem",
            "--tls-key",
            "key.pem",
        ],
    )

    assert result.exit_code == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8443
    assert captured["workers"] == 1
    assert captured["ssl_certfile"] == "cert.pem"
    assert captured["ssl_keyfile"] == "key.pem"
    assert captured["proxy_headers"] is False
