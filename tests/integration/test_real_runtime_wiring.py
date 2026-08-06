from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM
from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.core.context import ContextBuilder
from coding_agent_harness.core.harness import CoreSession, HarnessCore, InMemorySessionStore
from coding_agent_harness.domain.actions import ReadFileAction, SearchCodeAction
from coding_agent_harness.domain.enums import TaskStatus
from coding_agent_harness.feedback.engine import FeedbackEngine
from coding_agent_harness.security.policy import PolicyEngine

from tests.unit.core.test_harness import TASK_ID


def _config():
    return resolve_config(BUILTIN_CONFIG, {"llm": {"model": "gpt-test-model"}}, {}, "real")


def test_default_real_runtime_is_constructible_with_injected_safe_boundaries(tmp_path: Path) -> None:
    from coding_agent_harness.composition import build_default_real_runtime

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    verified = SimpleNamespace(
        root=worktree,
        base_commit="a" * 40,
        summary="verified isolated workspace",
        isolated=True,
    )
    runtime = build_default_real_runtime(
        data_root=tmp_path / "data",
        frozen_config=_config(),
        provider_factory=SimpleNamespace(create=lambda **_: ScriptedMockLLM([{"type": "request_human", "reason": "review"}])),
        workspace=SimpleNamespace(verified=True, prepare=lambda **_: verified),
        command_launcher=SimpleNamespace(launch=lambda request: None),
        trusted_python=Path(__file__).resolve(),
    )

    result = runtime.run(repository=tmp_path, task_description="repair", mode="real", trust_repo=True)

    assert runtime.data_root == (tmp_path / "data").resolve()
    assert result.status is TaskStatus.PAUSED_FOR_HUMAN


def test_default_status_does_not_construct_launcher_or_provider(tmp_path: Path) -> None:
    import pytest

    from coding_agent_harness.composition import build_default_real_runtime

    launcher_calls: list[str] = []
    provider_calls: list[str] = []
    runtime = build_default_real_runtime(
        data_root=tmp_path / "data",
        frozen_config=_config(),
        command_launcher_factory=lambda: launcher_calls.append("launcher"),
        provider_factory=SimpleNamespace(create=lambda **_: provider_calls.append("provider")),
    )

    with pytest.raises(KeyError, match="task not found"):
        runtime.status(UUID("123e4567-e89b-42d3-a456-426614174000"))

    assert launcher_calls == []
    assert provider_calls == []


def test_three_layer_config_uses_user_model_and_repo_only_restricts(tmp_path: Path) -> None:
    import pytest

    from coding_agent_harness.adapters.config.source_loader import ConfigSourceError, LayeredConfigSource
    from coding_agent_harness.adapters.llm.openai_factory import OpenAIClientFactory

    user_config = tmp_path / "user.toml"
    user_config.write_bytes(b'[llm]\nmodel = "gpt-course-model"\n[limits]\nmax_actions = 20\n')
    repo_blob = b'[limits]\nmax_actions = 10\n'
    source = LayeredConfigSource(user_config=user_config, repository_reader=lambda repository, base_commit: repo_blob)

    frozen = source.load(repository=tmp_path, base_commit="a" * 40)
    client = OpenAIClientFactory(sdk_constructor=lambda **_: SimpleNamespace(responses=SimpleNamespace())).create(
        credential_store=SimpleNamespace(_read_for_provider=lambda: "sk-test"),
        frozen_config=frozen,
        timeout_seconds=60,
        max_output_tokens=4096,
    )

    assert frozen.llm.model == "gpt-course-model"
    assert frozen.limits.max_actions == 10
    assert frozen.provenance["llm.model"] == "user"
    assert frozen.provenance["limits.max_actions"] == "repo"
    assert "gpt-course-model" in repr(client)

    broadening = LayeredConfigSource(
        user_config=user_config,
        repository_reader=lambda repository, base_commit: b'[llm]\nmodel = "repo-selected-model"\n',
    )
    with pytest.raises(ConfigSourceError, match="configuration is invalid"):
        broadening.load(repository=tmp_path, base_commit="a" * 40)


def test_production_executor_routes_read_and_search_to_local_filesystem(tmp_path: Path) -> None:
    from coding_agent_harness.adapters.runtime.action_executor import ProductionActionExecutor

    (tmp_path / "counter.py").write_text("def counter():\n    return 1\n", encoding="utf-8")
    executor = ProductionActionExecutor.for_workspace(
        root=tmp_path,
        base_commit="a" * 40,
        capabilities=_config().capabilities,
        git_launcher=lambda *_: None,
        diagnostic_launcher=lambda *_: None,
        patch_applier=lambda *_args, **_kwargs: None,
        test_runner=None,
    )

    read = executor.execute(ReadFileAction(type="read_file", path="counter.py"))
    search = executor.execute(SearchCodeAction(type="search_code", path=".", query="return 1", case_sensitive=True))

    assert "return 1" in read.safe_summary
    assert "counter.py" in search.safe_summary and "return 1" in search.safe_summary


@dataclass(frozen=True)
class _SafetyFacts:
    path_escape: bool = False
    symlink: bool = False
    binary: bool = False
    shell: bool = False
    capability_missing: bool = False
    demo_escape: bool = False


def test_composed_patch_is_policy_checked_applied_then_forces_full_tests(tmp_path: Path) -> None:
    from coding_agent_harness.adapters.runtime.action_executor import ProductionActionExecutor, WorkspacePatchPreparer

    (tmp_path / "counter.py").write_bytes(b"return 0\n")
    calls: list[str] = []

    def apply_spy(prepared, authorization, root):
        calls.append("apply")
        assert authorization is True and Path(root) == tmp_path.resolve()
        return SimpleNamespace(ok=True)

    class FullTests:
        def run(self):
            calls.append("full_test")
            return SimpleNamespace(
                safe_summary="full tests completed",
                source_revision="b",
                test_run=None,
                parsed_result=None,
                unknown_outcome=False,
            )

    executor = ProductionActionExecutor.for_workspace(
        root=tmp_path,
        base_commit="a" * 40,
        capabilities=_config().capabilities,
        git_launcher=lambda *_: None,
        diagnostic_launcher=lambda *_: None,
        patch_applier=apply_spy,
        test_runner=None,
    )
    store = InMemorySessionStore()
    store.save(CoreSession(task_id=TASK_ID, user_task="fix", config_summary="safe", workspace_summary="isolated"))
    diff = "--- a/counter.py\n+++ b/counter.py\n@@ -1 +1 @@\n-return 0\n+return 1\n"
    core = HarnessCore(
        llm=ScriptedMockLLM([{"type": "apply_patch", "diff": diff}]),
        session_store=store,
        context_builder=ContextBuilder(),
        policy_engine=PolicyEngine(),
        action_executor=executor,
        full_test_runner=FullTests(),
        feedback_engine=FeedbackEngine(),
        patch_preparer=WorkspacePatchPreparer(tmp_path),
        patch_safety_resolver=SimpleNamespace(resolve=lambda prepared: _SafetyFacts()),
        max_actions=1,
    )

    outcome = core.run(TASK_ID)

    assert outcome.status is TaskStatus.STOPPED
    assert calls == ["apply", "full_test"]
