import pytest

from coding_agent_harness.security.trust import TrustBinding, verify_trust_binding


def test_trust_binding_mutation_requires_reconfirmation() -> None:
    trust = TrustBinding(repository_identity="repo", base_commit="a" * 40, command_hash="b" * 64, config_hash="c" * 64, capability_hash="d" * 64, provider="openai", threat_notice_version="1", data_categories=("source",), mode="real")
    assert verify_trust_binding(trust, trust)
    changed = trust.__class__(**{**trust.__dict__, "base_commit": "e" * 40})
    assert not verify_trust_binding(trust, changed)
    assert "token" not in repr(trust).lower()


@pytest.mark.parametrize("field", ["repository_identity", "base_commit", "command_hash", "config_hash", "capability_hash", "provider", "threat_notice_version", "data_categories", "mode"])
def test_each_trust_binding_mutation_requires_reconfirmation(field) -> None:
    trust = TrustBinding(repository_identity="repo", base_commit="a" * 40, command_hash="b" * 64, config_hash="c" * 64, capability_hash="d" * 64, provider="openai", threat_notice_version="1", data_categories=("source",), mode="real")
    changes = {"repository_identity": "other", "base_commit": "e" * 40, "command_hash": "e" * 64, "config_hash": "e" * 64, "capability_hash": "e" * 64, "provider": "other", "threat_notice_version": "2", "data_categories": ("tests",), "mode": "demo"}
    assert not verify_trust_binding(trust, trust.__class__(**{**trust.__dict__, field: changes[field]}))


def test_trust_binding_is_frozen_and_forbids_extra_or_sensitive_fields() -> None:
    trust = TrustBinding(repository_identity="repo", base_commit="a" * 40, command_hash="b" * 64, config_hash="c" * 64, capability_hash="d" * 64, provider="openai", threat_notice_version="1", data_categories=("source",), mode="real")
    with pytest.raises(Exception):
        trust.mode = "demo"
    with pytest.raises(Exception):
        trust.__class__(**{**trust.__dict__, "token": "secret"})
    assert all(name not in trust.__dict__ for name in ("credential", "token", "secret", "environment"))
