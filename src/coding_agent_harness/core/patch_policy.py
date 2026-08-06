from __future__ import annotations

from coding_agent_harness.domain.actions import ApplyPatchAction
from coding_agent_harness.patching.models import OperationType, PreparedPatch
from coding_agent_harness.security.policy import PolicyFacts


_PROTECTED_CONFIG = frozenset({"pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini", ".coding-harness.toml"})
_DEPENDENCY_CONFIG = frozenset({"pyproject.toml", "setup.cfg", "requirements.txt", "requirements-dev.txt", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock"})


def policy_facts_from_prepared(action: ApplyPatchAction, prepared: PreparedPatch, safety) -> PolicyFacts:
    paths = tuple(plan.path for plan in prepared.files)
    return PolicyFacts(
        file_count=prepared.facts.file_count,
        changed_lines=prepared.facts.added_lines + prepared.facts.deleted_lines,
        payload_bytes=len(action.diff.encode("utf-8", errors="strict")),
        touches_test_assets=prepared.facts.touches_test_assets,
        protected_config=any(path in _PROTECTED_CONFIG for path in paths),
        path_escape=getattr(safety, "path_escape", False),
        symlink=safety.symlink,
        binary=getattr(safety, "binary", False),
        shell=getattr(safety, "shell", False),
        capability_missing=safety.capability_missing,
        demo_escape=safety.demo_escape,
        source_delete=any(plan.operation is OperationType.DELETE and plan.path.endswith(".py") and not plan.path.startswith("tests/") for plan in prepared.files),
        sensitive_path=prepared.facts.touches_sensitive_paths,
        dependency_config=any(path in _DEPENDENCY_CONFIG or path.startswith("requirements/") for path in paths),
    )
