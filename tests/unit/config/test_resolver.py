"""FrozenConfig merge, capability and deterministic hash contracts."""

from pathlib import Path

import pytest

from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.loader import load_strict_toml
from coding_agent_harness.config.models import ConfigConflict
from coding_agent_harness.config.resolver import resolve_config, sha256_canonical_config


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "config"


def document(name: str) -> dict[str, object]:
    return load_strict_toml((FIXTURES / name).read_bytes())


def test_resolver_intersects_whitelists_unions_paths_and_minimizes_limits():
    user = document("valid_user.toml")
    repo = {"diagnostics": {"allowed_commands": ["ruff_check"]}, "paths": {"protected": ["custom-protected/**"], "sensitive": ["repo-secrets/**"]}, "tests": {"timeout_seconds": 90}, "limits": {"max_actions": 12}}
    frozen = resolve_config(BUILTIN_CONFIG, user, repo, mode="real")
    assert frozen.tests.timeout_seconds == 90
    assert frozen.limits.max_actions == 12
    assert frozen.capabilities.diagnostic_ids == ("ruff_check",)
    assert "tests/**" in frozen.paths.protected and "custom-protected/**" in frozen.paths.protected
    assert "local-secrets/**" in frozen.paths.sensitive and "repo-secrets/**" in frozen.paths.sensitive
    assert frozen.provenance["tests.timeout_seconds"] == "repo"


def test_builtin_sensitive_exclusions_survive_empty_user_sensitive_paths():
    user = {"paths": {"sensitive": []}}
    frozen = resolve_config(BUILTIN_CONFIG, user, {}, mode="real")
    assert ".env" in frozen.paths.sensitive
    assert any("id_rsa" in path for path in frozen.paths.sensitive)
    assert any("harness-data" in path for path in frozen.paths.sensitive)


@pytest.mark.parametrize("name", ["broadening_repo.toml", "conflicting_repo.toml"])
def test_repository_broadening_or_empty_intersection_is_stable_conflict(name):
    user = document("valid_user.toml")
    with pytest.raises(ConfigConflict):
        resolve_config(BUILTIN_CONFIG, user, document(name), mode="demo" if "broadening" in name else "real")


def test_timeout_above_absolute_hard_limit_is_rejected():
    with pytest.raises(ConfigConflict):
        resolve_config(BUILTIN_CONFIG, {}, {"tests": {"timeout_seconds": 601}}, mode="real")


def test_real_and_demo_capabilities_are_explicit_and_demo_only_restricts():
    real = resolve_config(BUILTIN_CONFIG, document("valid_user.toml"), {}, mode="real")
    demo = resolve_config(BUILTIN_CONFIG, document("valid_user.toml"), {}, mode="demo")
    assert real.capabilities.openai_enabled is True
    assert real.capabilities.credentials_enabled is True
    assert demo.capabilities.openai_enabled is False
    assert demo.capabilities.credentials_enabled is False
    assert demo.capabilities.arbitrary_paths_enabled is False
    assert demo.capabilities.diagnostic_ids == ()


def test_frozen_config_hash_is_stable_and_source_order_independent():
    user_a = document("valid_user.toml")
    user_b = {key: user_a[key] for key in reversed(list(user_a))}
    first = resolve_config(BUILTIN_CONFIG, user_a, {}, mode="real")
    second = resolve_config(BUILTIN_CONFIG, user_b, {}, mode="real")
    assert first.sha256 == second.sha256 == sha256_canonical_config(first)
    assert len(first.sha256) == 64
