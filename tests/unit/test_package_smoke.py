"""Package smoke tests for the formal Task 1 skeleton."""

import sys
import tomllib
from pathlib import Path

import coding_agent_harness


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_package_exposes_version_string():
    assert isinstance(coding_agent_harness.__version__, str)
    assert coding_agent_harness.__version__


def test_running_interpreter_is_supported():
    assert (3, 11) <= sys.version_info[:2] < (3, 13)


def test_requires_python_metadata_is_311_to_before_313():
    pyproject = PROJECT_ROOT / "pyproject.toml"
    assert pyproject.is_file(), "pyproject.toml must exist at the project root"
    with pyproject.open("rb") as stream:
        document = tomllib.load(stream)
    assert document["project"]["requires-python"] == ">=3.11,<3.13"
