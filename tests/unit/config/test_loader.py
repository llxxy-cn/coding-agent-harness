"""Strict TOML loader contracts for Task 4."""

from pathlib import Path

import pytest

from coding_agent_harness.config.loader import load_strict_toml


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "config"


def test_valid_toml_loads_without_interpolation_or_mutation():
    raw = (FIXTURES / "valid_user.toml").read_bytes()
    document = load_strict_toml(raw)
    assert document["llm"]["provider"] == "openai"
    assert document["tests"]["default_command"] == ["python", "-m", "pytest", "-q"]


@pytest.mark.parametrize(
    "raw",
    [
        b"unknown = true\n",
        b"[llm]\nprovider = '${HOME}'\nmodel = 'x'\n",
        b"schema_version = '1'\n",
        b"[tests]\ntimeout_seconds = 120\nextra = true\n",
    ],
)
def test_loader_rejects_unknown_fields_interpolation_and_type_coercion(raw):
    with pytest.raises(ValueError):
        load_strict_toml(raw)


def test_loader_rejects_invalid_toml_and_non_mapping_top_level():
    with pytest.raises(ValueError):
        load_strict_toml(b"[broken\n")
