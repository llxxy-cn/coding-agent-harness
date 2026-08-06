import pytest
from uuid import uuid4

from coding_agent_harness.domain.enums import ApprovalStatus
from coding_agent_harness.domain.models import TaskId
from coding_agent_harness.security.approvals import ApprovalBinding, can_execute_approval, verify_approval_binding


def _binding() -> ApprovalBinding:
    return ApprovalBinding(task_id=TaskId(value=uuid4()), action_sha256="a" * 64, diff_sha256="b" * 64, target_paths=("src/a.py",), pre_image_hashes=("c" * 64,), config_sha256="d" * 64, capability_sha256="e" * 64, risk_sha256="f" * 64, base_commit="a" * 40, status=ApprovalStatus.APPROVED)


def test_approval_binding_mutations_invalidate_and_resume_is_explicit() -> None:
    binding = _binding()
    assert verify_approval_binding(binding, binding)
    changed = binding.__class__(**{**binding.__dict__, "diff_sha256": "0" * 64})
    assert not verify_approval_binding(binding, changed)
    assert binding.status is ApprovalStatus.APPROVED
    assert binding.status is not ApprovalStatus.CONSUMED


@pytest.mark.parametrize("field", ["task_id", "action_sha256", "diff_sha256", "target_paths", "pre_image_hashes", "config_sha256", "capability_sha256", "risk_sha256", "base_commit", "status"])
def test_each_approval_binding_mutation_invalidates(field) -> None:
    binding = _binding()
    changes = {
        "task_id": TaskId(value=uuid4()), "action_sha256": "0" * 64, "diff_sha256": "0" * 64,
        "target_paths": ("src/b.py",), "pre_image_hashes": ("0" * 64,), "config_sha256": "0" * 64,
        "capability_sha256": "0" * 64, "risk_sha256": "0" * 64, "base_commit": "0" * 40,
        "status": ApprovalStatus.CONSUMED,
    }
    changed = binding.__class__(**{**binding.__dict__, field: changes[field]})
    assert not verify_approval_binding(binding, changed)


def test_approval_binding_strict_frozen_and_resume_qualification() -> None:
    binding = _binding()
    with pytest.raises(Exception):
        binding.status = ApprovalStatus.CONSUMED
    with pytest.raises(Exception):
        binding.__class__(**{**binding.__dict__, "extra": 1})
    assert can_execute_approval(binding, resume_requested=False) is False
