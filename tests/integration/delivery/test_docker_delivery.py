from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _content(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_runtime_image_is_wheel_based_non_root_and_health_checked() -> None:
    """Removing a runtime hardening directive would weaken the published image."""
    dockerfile = _content("Dockerfile")

    assert "FROM python:3.12-slim AS build" in dockerfile
    assert "python -m pip wheel" in dockerfile
    assert "--no-index --find-links=/wheels" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "TMPDIR=/tmp" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "127.0.0.1:8000/healthz" in dockerfile
    assert "ENTRYPOINT [\"coding-agent-harness\", \"web\"]" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "ADD " not in dockerfile


def test_runtime_image_includes_fixed_demo_execution_dependencies() -> None:
    """The fixed demo worker must be able to initialize Git and execute pytest."""
    dockerfile = _content("Dockerfile")

    assert "apt-get install --no-install-recommends -y git" in dockerfile
    assert 'python -m pip wheel --no-cache-dir --wheel-dir /wheels ".[dev]"' in dockerfile
    assert "--find-links=/wheels coding-agent-harness pytest" in dockerfile


def test_docker_context_excludes_development_sensitive_and_cache_content() -> None:
    """An accidental broad build context could publish local credentials or source history."""
    ignored = set(_content(".dockerignore").splitlines())

    assert {".git", "tests", "docs", ".env", "*.pem", "*.key", "__pycache__"} <= ignored


def test_gitlab_docker_build_runs_local_hardening_smoke_without_publication() -> None:
    """Dropping local runtime checks or adding publication would violate the delivery scope."""
    pipeline = _content(".gitlab-ci.yml")

    assert "docker-build:" in pipeline
    assert "docker build" in pipeline
    assert "docker image inspect" in pipeline
    assert "--read-only" in pipeline
    assert "--tmpfs /tmp" in pipeline
    assert "--cap-drop ALL" in pipeline
    assert "no-new-privileges" in pipeline
    assert "/healthz" in pipeline
    assert "docker push" not in pipeline
    assert "Container-Scanning" not in pipeline
