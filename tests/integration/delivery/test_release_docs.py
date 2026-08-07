from __future__ import annotations

import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import coding_agent_harness


ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_URL = "https://github.com/llxxy-cn/coding-agent-harness"
RELEASE_URL = "https://github.com/llxxy-cn/coding-agent-harness/releases/tag/v0.1.0"
WHEEL_SCHEMA = "coding_agent_harness/adapters/sqlite/schema.sql"
SDIST_SCHEMA = "coding-agent-harness-0.1.0/src/coding_agent_harness/adapters/sqlite/schema.sql"


def text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_built_archives_include_sqlite_schema(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    subprocess.run(
        (sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output)),
        cwd=ROOT,
        shell=False,
        check=True,
    )

    with zipfile.ZipFile(output / "coding_agent_harness-0.1.0-py3-none-any.whl") as wheel:
        assert WHEEL_SCHEMA in wheel.namelist()
    with tarfile.open(output / "coding-agent-harness-0.1.0.tar.gz", "r:gz") as sdist:
        assert SDIST_SCHEMA in sdist.getnames()


def test_readme_documents_real_cli_and_safety_boundaries() -> None:
    readme = text("README.md")

    for heading in (
        "## Overview",
        "## Features",
        "## Installation",
        "## Configuration",
        "## Credentials",
        "## CLI",
        "## Offline Demo",
        "## Architecture",
        "## Security Boundaries",
        "## Project Layout",
        "## Distribution",
        "## Known Limitations",
    ):
        assert heading in readme
    for command in (
        "coding-agent-harness run",
        "coding-agent-harness status",
        "coding-agent-harness resume",
        "coding-agent-harness key set",
        "coding-agent-harness key status",
        "coding-agent-harness key update",
        "coding-agent-harness key clear",
    ):
        assert command in readme
    assert "--demo --trust-repo" in readme
    assert "shell=False" in readme
    assert "raw pytest output is never persisted" in readme


def test_release_documents_cover_architecture_demo_and_current_limits() -> None:
    readme = text("README.md")
    architecture = text("docs/ARCHITECTURE.md")
    demo = text("docs/DEMO.md")
    notes = text("RELEASE_NOTES.md")

    assert "HarnessCore" in architecture
    assert "```mermaid" in architecture
    assert "Credential boundary" in architecture
    assert "Raw-output boundary" in architecture
    assert "baseline" in demo.lower()
    assert "Policy deny" in demo
    assert "invalid Action" in demo
    assert "0.1.0" in notes
    assert "371 passed" in notes
    assert "2 skipped" in notes
    assert REPOSITORY_URL in readme
    assert RELEASE_URL in readme
    assert REPOSITORY_URL in notes
    assert RELEASE_URL in notes
    assert "planned release" in readme.lower()
    assert "planned release" in notes.lower()
    assert "MIT License" in readme
    assert "Copyright (c) 2026 llxxy-cn" in readme
    assert "upstream license" in readme


def test_package_metadata_and_documented_version_are_consistent() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["version"] == coding_agent_harness.__version__ == "0.1.0"
    assert project["readme"] == "README.md"
    assert project["scripts"] == {
        "coding-agent-harness": "coding_agent_harness.cli.app:main"
    }
    assert "v0.1.0" in text("RELEASE_NOTES.md")


def test_ai_log_records_reviewable_assistance_without_sensitive_values() -> None:
    log = text("AGENT_LOG.md")

    for phrase in (
        "Codex",
        "Superpowers",
        "Red → Green → verification",
        "human",
        "review",
    ):
        assert phrase in log
    assert "API key" not in log


def test_spec_process_records_real_commits_and_pending_external_evidence() -> None:
    process = text("SPEC_PROCESS.md")

    for commit in (
        "daffeb6857e10101d92091c8dcb6e60e8772aea6",
        "f976cc2",
        "634712f",
        "fc12c5989b71975b280bdaa3d5ac6f6e7f70215c",
        "10455b31ce60f18d1450aa42fb88393a79c785fc",
        "55b6186a3dfa6c95287b8b92d6f0c49d0d14e98d",
        "ab5c23fc1cb58ddde32920e463b83413741b9270",
        "5de2d27dfb70ac606201b07a4c867aa8d4006549",
        "cd431e2a7482db28955f79a768c7b79d0aefc473",
        "630ba9c02315b534addc0aa3a4a011815c9b7271",
        "7eff8038bdc7f15df8a3bcdfb215d93cb71ee6d8",
        "8aae4f6f962d877a9860de7412589fc55ff92e19",
    ):
        assert commit in process
    assert "371 passed, 2 skipped, 0 warnings" in process
    assert "Python 3.12 isolated installation" in process
    assert "remote CI: pending verification" in process
    assert "hosted release: planned, not created" in process
    assert "student-authored" in process
