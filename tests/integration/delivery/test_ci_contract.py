from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def content(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_license_is_standard_mit_with_confirmed_holder() -> None:
    assert content("LICENSE") == """MIT License

Copyright (c) 2026 llxxy-cn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def test_github_actions_runs_matrix_tests_and_package_build_without_live_services() -> None:
    workflow = content(".github/workflows/ci.yml")

    assert re.search(r"(?m)^name: ci$", workflow)
    assert re.search(r"(?m)^on:$", workflow)
    assert re.search(r"(?m)^  push:$", workflow)
    assert re.search(r"(?m)^  pull_request:$", workflow)
    assert '["3.11", "3.12"]' in workflow
    assert "actions/checkout@v4" in workflow
    assert "actions/setup-python@v5" in workflow
    assert 'python -m pip install -e ".[dev]"' in workflow
    assert "python -m pytest -q" in workflow
    assert "package-build:" in workflow
    assert '"setuptools>=68,<69"' in workflow
    assert '"wheel>=0.42,<1"' in workflow
    assert '"build>=1.5,<1.6"' in workflow
    assert "python -m build --no-isolation" in workflow
    assert not re.search(
        r"OPENAI_API_KEY|keyring|api[-_]?key|coding-agent-harness run|git (?:remote|fetch|pull|push)",
        workflow,
        re.IGNORECASE,
    )


def test_gitlab_ci_has_exact_unit_test_and_package_build_jobs() -> None:
    pipeline = content(".gitlab-ci.yml")

    assert re.search(r"(?m)^stages:$", pipeline)
    assert re.search(r"(?m)^  - test$", pipeline)
    assert re.search(r"(?m)^  - build$", pipeline)
    assert re.search(r"(?m)^unit-test:$", pipeline)
    assert re.search(r"(?m)^package-build:$", pipeline)
    assert "python:3.12" in pipeline
    assert 'python -m pip install -e ".[dev]"' in pipeline
    assert "python -m pytest -q" in pipeline
    assert '"setuptools>=68,<69"' in pipeline
    assert '"wheel>=0.42,<1"' in pipeline
    assert '"build>=1.5,<1.6"' in pipeline
    assert "python -m build --no-isolation" in pipeline
    assert not re.search(
        r"OPENAI_API_KEY|keyring|api[-_]?key|coding-agent-harness run|git (?:remote|fetch|pull|push)",
        pipeline,
        re.IGNORECASE,
    )
