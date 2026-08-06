from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM
from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.core.harness import ActionExecution
from coding_agent_harness.domain.enums import TaskStatus, TestRunOutcome as DomainTestRunOutcome
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome

from tests.unit.core.test_harness import (
    DefaultPatchPreparer,
    DefaultPatchSafetyResolver,
    Executor,
    FullTests,
    TASK_ID,
    make_test_run,
    parsed,
)


def _config():
    return resolve_config(BUILTIN_CONFIG, {"llm": {"model": "gpt-test-model"}}, {}, "real")


class FakeProviderFactory:
    def __init__(self, llm) -> None:
        self.llm = llm
        self.calls = []

    def create(self, *, frozen_config):
        self.calls.append(frozen_config)
        return self.llm


class BombProviderFactory:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, *, frozen_config):
        self.calls += 1
        raise AssertionError("provider must not be created")


class VerifiedWorkspaceBoundary:
    verified = True

    def __init__(self, worktree) -> None:
        self.worktree = worktree
        self.calls = []

    def prepare(self, *, repository, task_id, frozen_config, trust_repo):
        self.calls.append((repository, task_id, frozen_config, trust_repo))
        return SimpleNamespace(root=self.worktree.resolve(), summary="verified isolated test workspace", isolated=True)


class BombDependency:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected dependency call: {name}")


def _runtime(tmp_path, provider_factory, *, executor=None, full_tests=None, task_id_factory=None):
    from coding_agent_harness.composition import build_real_runtime

    worktree = tmp_path / "verified-worktree"
    worktree.mkdir(exist_ok=True)
    return build_real_runtime(
        data_root=tmp_path / "harness-data",
        frozen_config=_config(),
        provider_factory=provider_factory,
        workspace=VerifiedWorkspaceBoundary(worktree),
        action_executor=executor or BombDependency(),
        full_test_runner=full_tests or BombDependency(),
        patch_preparer=DefaultPatchPreparer(),
        patch_safety_resolver=DefaultPatchSafetyResolver(),
        task_id_factory=task_id_factory,
    )


def test_real_runtime_runs_through_application_core_and_persists_task(tmp_path) -> None:
    llm = ScriptedMockLLM([{"type": "request_human", "reason": "review required"}])
    provider = FakeProviderFactory(llm)
    runtime = _runtime(tmp_path, provider)

    result = runtime.run(repository=tmp_path, task_description="fix counter", mode="real", trust_repo=True)

    assert result.status is TaskStatus.PAUSED_FOR_HUMAN
    assert len(provider.calls) == 1 and len(llm.contexts) == 1
    assert runtime.application.core.__class__.__name__ == "HarnessCore"


def test_status_reads_task_from_new_runtime_using_same_data_root(tmp_path) -> None:
    first = _runtime(tmp_path, FakeProviderFactory(ScriptedMockLLM([{"type": "request_human", "reason": "review required"}])))
    created = first.run(repository=tmp_path, task_description="fix counter", mode="real", trust_repo=True)
    second_provider = BombProviderFactory()
    second = _runtime(tmp_path, second_provider)

    loaded = second.status(created.task_id)

    assert loaded.task_id == created.task_id
    assert loaded.status is TaskStatus.PAUSED_FOR_HUMAN
    assert second_provider.calls == 0


def test_new_runtime_resumes_persisted_recoverable_session_via_application_service(tmp_path) -> None:
    first = _runtime(tmp_path, FakeProviderFactory(ScriptedMockLLM([{"type": "request_human", "reason": "review required"}])))
    created = first.run(repository=tmp_path, task_description="fix counter", mode="real", trust_repo=True)
    resumed_llm = ScriptedMockLLM([{"type": "request_human", "reason": "review again"}])
    resumed_provider = FakeProviderFactory(resumed_llm)
    second = _runtime(tmp_path, resumed_provider)

    result = second.resume(created.task_id)

    assert result.status is TaskStatus.PAUSED_FOR_HUMAN
    assert len(resumed_provider.calls) == 1 and len(resumed_llm.contexts) == 1


def test_nonrecoverable_session_rejects_resume_without_state_change(tmp_path) -> None:
    diff = "--- a/counter.py\n+++ b/counter.py\n@@ -1 +1 @@\n-return 0\n+return 1\n"
    executor = Executor([ActionExecution(safe_summary="patch applied", source_revision="b")])
    full_tests = FullTests([ActionExecution(safe_summary="tests passed", source_revision="b", test_run=make_test_run(DomainTestRunOutcome.PASSED), parsed_result=parsed(ParsedOutcome.PASSED, (), "b"))])
    first = _runtime(tmp_path, FakeProviderFactory(ScriptedMockLLM([{"type": "apply_patch", "diff": diff}])), executor=executor, full_tests=full_tests, task_id_factory=lambda: TASK_ID)
    created = first.run(repository=tmp_path, task_description="fix counter", mode="real", trust_repo=True)
    second_provider = BombProviderFactory()
    second = _runtime(tmp_path, second_provider, task_id_factory=lambda: TASK_ID)

    with pytest.raises(ValueError, match="task is not resumable"):
        second.resume(created.task_id)

    assert second.status(created.task_id).status is TaskStatus.SUCCEEDED
    assert second_provider.calls == 0


class _Preflight:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = 0

    def inspect(self, repository):
        self.calls += 1
        return SimpleNamespace(root=self.root, base_commit="a" * 40, identity_sha256="b" * 64)


class _ConfigSource:
    def __init__(self, value=None, error=None) -> None:
        self.value = value
        self.error = error
        self.calls = []

    def load(self, *, repository, base_commit):
        self.calls.append((repository, base_commit))
        if self.error is not None:
            raise self.error
        return self.value


class _WorkspaceBomb:
    def __init__(self) -> None:
        self.calls = 0

    def prepare(self, **kwargs):
        self.calls += 1
        raise AssertionError("worktree must not be created")


class _CredentialMissingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, *, frozen_config):
        from coding_agent_harness.security.provider_errors import ProviderError, ProviderErrorCode

        self.calls += 1
        raise ProviderError(ProviderErrorCode.CREDENTIAL_MISSING)


def test_missing_credential_stops_after_readonly_preflight_with_zero_write_side_effects(tmp_path) -> None:
    from coding_agent_harness.composition import build_default_real_runtime

    data_root = tmp_path / "absent-data"
    launcher_calls: list[str] = []
    workspace = _WorkspaceBomb()
    provider = _CredentialMissingProvider()
    preflight = _Preflight(tmp_path)
    runtime = build_default_real_runtime(
        data_root=data_root,
        provider_factory=provider,
        workspace=workspace,
        repository_preflight=preflight,
        config_source_loader=_ConfigSource(_config()),
        command_launcher_factory=lambda: launcher_calls.append("launcher"),
    )

    with pytest.raises(Exception, match="credential is not configured"):
        runtime.run(repository=tmp_path, task_description="repair", mode="real", trust_repo=True)

    assert provider.calls == 1
    assert preflight.calls == 1
    assert workspace.calls == 0
    assert launcher_calls == []
    assert not data_root.exists()


def test_placeholder_model_stops_before_provider_or_writes(tmp_path) -> None:
    from coding_agent_harness.composition import build_default_real_runtime

    data_root = tmp_path / "absent-data"
    workspace = _WorkspaceBomb()
    provider = BombProviderFactory()
    placeholder = resolve_config(BUILTIN_CONFIG, {}, {}, "real")
    runtime = build_default_real_runtime(
        data_root=data_root,
        provider_factory=provider,
        workspace=workspace,
        repository_preflight=_Preflight(tmp_path),
        config_source_loader=_ConfigSource(placeholder),
    )
    with pytest.raises(Exception, match="provider model is not configured"):
        runtime.run(repository=tmp_path, task_description="repair", mode="real", trust_repo=True)

    assert provider.calls == 0 and workspace.calls == 0 and not data_root.exists()


def test_config_error_is_sanitized_and_stops_before_provider_or_writes(tmp_path) -> None:
    from coding_agent_harness.composition import build_default_real_runtime

    data_root = tmp_path / "absent-data"
    workspace = _WorkspaceBomb()
    provider = BombProviderFactory()
    invalid = build_default_real_runtime(
        data_root=data_root,
        provider_factory=provider,
        workspace=workspace,
        repository_preflight=_Preflight(tmp_path),
        config_source_loader=_ConfigSource(error=ValueError(f"bad config at {tmp_path}")),
    )
    with pytest.raises(Exception, match="configuration is invalid") as captured:
        invalid.run(repository=tmp_path, task_description="repair", mode="real", trust_repo=True)

    assert str(tmp_path) not in str(captured.value)
    assert provider.calls == 0 and workspace.calls == 0 and not data_root.exists()
