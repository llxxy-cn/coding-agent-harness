import pytest

from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.domain.actions import GitStatusAction
from coding_agent_harness.patching.models import PatchFacts
from coding_agent_harness.domain.enums import PolicyOutcome
from coding_agent_harness.security.policy import PolicyEngine, PolicyFacts, PolicyReasonCode


def facts(**overrides):
    values = dict(file_count=1, added_lines=0, deleted_lines=0, touches_test_assets=False, touches_sensitive_paths=False)
    values.update(overrides)
    return PatchFacts(**values)


def test_policy_priority_deny_approval_allow_and_boundaries() -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    engine = PolicyEngine()
    assert engine.evaluate(GitStatusAction(type="git_status"), facts(), config, None).outcome.value == "allow"
    assert engine.evaluate(GitStatusAction(type="git_status"), facts(file_count=6), config, None).outcome.value == "require_approval"
    assert engine.evaluate(GitStatusAction(type="git_status"), facts(touches_test_assets=True, file_count=6), config, None).outcome.value == "deny"
    assert engine.evaluate(GitStatusAction(type="git_status"), facts(file_count=21), config, object()).outcome.value == "deny"
    assert engine.evaluate(GitStatusAction(type="git_status"), facts(added_lines=301), config, None).outcome.value == "require_approval"


@pytest.mark.parametrize(("overrides", "outcome", "reason"), [
    ({}, PolicyOutcome.ALLOW, PolicyReasonCode.ALLOWED),
    ({"touches_test_assets": True}, PolicyOutcome.DENY, PolicyReasonCode.TEST_ASSET_PROTECTION),
    ({"protected_config": True}, PolicyOutcome.DENY, PolicyReasonCode.PROTECTED_CONFIG),
    ({"path_escape": True}, PolicyOutcome.DENY, PolicyReasonCode.PATH_SAFETY),
    ({"symlink": True}, PolicyOutcome.DENY, PolicyReasonCode.PATH_SAFETY),
    ({"binary": True}, PolicyOutcome.DENY, PolicyReasonCode.BINARY_UNSUPPORTED),
    ({"shell": True}, PolicyOutcome.DENY, PolicyReasonCode.SHELL_FORBIDDEN),
    ({"capability_missing": True}, PolicyOutcome.DENY, PolicyReasonCode.CAPABILITY_MISSING),
    ({"demo_escape": True}, PolicyOutcome.DENY, PolicyReasonCode.DEMO_ESCAPE),
    ({"file_count": 5}, PolicyOutcome.ALLOW, PolicyReasonCode.ALLOWED),
    ({"file_count": 6}, PolicyOutcome.REQUIRE_APPROVAL, PolicyReasonCode.PATCH_REQUIRES_APPROVAL),
    ({"file_count": 20}, PolicyOutcome.REQUIRE_APPROVAL, PolicyReasonCode.PATCH_REQUIRES_APPROVAL),
    ({"file_count": 21}, PolicyOutcome.DENY, PolicyReasonCode.PATCH_HARD_LIMIT),
    ({"changed_lines": 300}, PolicyOutcome.ALLOW, PolicyReasonCode.ALLOWED),
    ({"changed_lines": 301}, PolicyOutcome.REQUIRE_APPROVAL, PolicyReasonCode.PATCH_REQUIRES_APPROVAL),
    ({"changed_lines": 2000}, PolicyOutcome.REQUIRE_APPROVAL, PolicyReasonCode.PATCH_REQUIRES_APPROVAL),
    ({"changed_lines": 2001}, PolicyOutcome.DENY, PolicyReasonCode.PATCH_HARD_LIMIT),
    ({"payload_bytes": 1_048_576}, PolicyOutcome.ALLOW, PolicyReasonCode.ALLOWED),
    ({"payload_bytes": 1_048_577}, PolicyOutcome.DENY, PolicyReasonCode.PATCH_HARD_LIMIT),
    ({"source_delete": True}, PolicyOutcome.REQUIRE_APPROVAL, PolicyReasonCode.SOURCE_DELETE),
    ({"sensitive_path": True}, PolicyOutcome.REQUIRE_APPROVAL, PolicyReasonCode.SENSITIVE_PATH),
    ({"dependency_config": True}, PolicyOutcome.REQUIRE_APPROVAL, PolicyReasonCode.DEPENDENCY_CONFIG),
])
def test_policy_complete_parameterized_matrix(overrides, outcome, reason) -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    decision = PolicyEngine().evaluate(GitStatusAction(type="git_status"), PolicyFacts(**overrides), config, None)
    assert decision.outcome is outcome
    assert decision.reason_code is reason


def test_policy_deny_precedes_approval_and_is_pure() -> None:
    config = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    policy_facts = PolicyFacts(file_count=6, touches_test_assets=True)
    action = GitStatusAction(type="git_status")
    decision = PolicyEngine().evaluate(action, policy_facts, config, object())
    assert decision.outcome is PolicyOutcome.DENY
    assert policy_facts.file_count == 6 and action.type == "git_status"
