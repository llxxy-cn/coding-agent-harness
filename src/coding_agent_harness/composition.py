from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from coding_agent_harness.adapters.llm.scripted_mock import ScriptedMockLLM
from coding_agent_harness.application.service import ApplicationService
from coding_agent_harness.application.session_store import PersistentCoreSessionStore
from coding_agent_harness.adapters.artifacts.local_store import LocalArtifactStore
from coding_agent_harness.adapters.sqlite.state_store import SQLiteStateStore
from coding_agent_harness.config.models import FrozenConfig
from coding_agent_harness.core.context import ContextBuilder
from coding_agent_harness.core.harness import ActionExecution, CoreSession, HarnessCore, InMemorySessionStore
from coding_agent_harness.domain.enums import TaskStatus, TestPhase, TestRunOutcome
from coding_agent_harness.domain.models import ArtifactRef, FrozenCommand, TaskId, TestRun
from coding_agent_harness.feedback.engine import FeedbackEngine
from coding_agent_harness.feedback.pytest_parser import ParsedOutcome, ParsedTestResult
from coding_agent_harness.patching.models import PatchSnapshot
from coding_agent_harness.patching.parser import prepare
from coding_agent_harness.security.policy import PolicyEngine


PROVIDER_TIMEOUT_SECONDS = 60
PROVIDER_MAX_OUTPUT_TOKENS = 4096
_DEMO_TASK_ID = TaskId(value=UUID("123e4567-e89b-42d3-a456-426614174000"))
_HASH = "a" * 64


def build_real_llm(*, frozen_config: FrozenConfig, backend=None, sdk_constructor=None):
    if backend is None:
        import keyring

        backend = keyring
    from coding_agent_harness.adapters.credentials.keyring_store import KeyringCredentialStore
    from coding_agent_harness.adapters.llm.openai_factory import OpenAIClientFactory

    store = KeyringCredentialStore(backend=backend)
    return OpenAIClientFactory(sdk_constructor=sdk_constructor).create(
        credential_store=store,
        frozen_config=frozen_config,
        timeout_seconds=PROVIDER_TIMEOUT_SECONDS,
        max_output_tokens=PROVIDER_MAX_OUTPUT_TOKENS,
    )


class _SystemProviderFactory:
    def __init__(self, *, backend=None, sdk_constructor=None) -> None:
        self.backend = backend
        self.sdk_constructor = sdk_constructor

    def create(self, *, frozen_config):
        return build_real_llm(frozen_config=frozen_config, backend=self.backend, sdk_constructor=self.sdk_constructor)


class _UnavailableDependency:
    def __getattr__(self, name):
        raise RuntimeError("runtime dependency is unavailable")


class _RealRuntime:
    def __init__(self, *, data_root, frozen_config, provider_factory, workspace, action_executor, full_test_runner, patch_preparer, patch_safety_resolver, task_id_factory=None, component_factory=None, repository_preflight=None, config_source_loader=None) -> None:
        self.data_root = Path(data_root).resolve()
        self.frozen_config = frozen_config
        self.provider_factory = provider_factory
        self.workspace = workspace
        self.action_executor = action_executor
        self.full_test_runner = full_test_runner
        self.patch_preparer = patch_preparer
        self.patch_safety_resolver = patch_safety_resolver
        self.task_id_factory = task_id_factory or (lambda: TaskId(value=uuid4()))
        self.component_factory = component_factory
        self.repository_preflight = repository_preflight
        self.config_source_loader = config_source_loader
        self.application = None
        self.artifact_store = None

    def _stores(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        state_store = SQLiteStateStore(self.data_root / "state.sqlite3")
        self.artifact_store = LocalArtifactStore(self.data_root / "artifacts")
        return PersistentCoreSessionStore(state_store)

    def _task_id(self):
        value = self.task_id_factory()
        if isinstance(value, TaskId):
            return value
        return TaskId(value=value)

    def _core(self, session_store, llm):
        return HarnessCore(
            llm=llm,
            session_store=session_store,
            context_builder=ContextBuilder(max_history=self.frozen_config.limits.history_window or 8),
            policy_engine=PolicyEngine(),
            action_executor=self.action_executor,
            full_test_runner=self.full_test_runner,
            feedback_engine=FeedbackEngine(),
            patch_preparer=self.patch_preparer,
            patch_safety_resolver=self.patch_safety_resolver,
            max_actions=self.frozen_config.limits.max_actions or 40,
            max_feedback=self.frozen_config.limits.max_feedback_rounds or 8,
        )

    def _activate_components(self, workspace, task_id):
        if self.component_factory is None:
            return
        components = self.component_factory(workspace, task_id, self.artifact_store, self.frozen_config)
        self.action_executor = components.action_executor
        self.full_test_runner = components.full_test_runner
        self.patch_preparer = components.patch_preparer
        self.patch_safety_resolver = components.patch_safety_resolver

    @staticmethod
    def _view(session_or_outcome, task_id):
        status = session_or_outcome.status
        reason = getattr(session_or_outcome, "reason", "task state loaded")
        return SimpleNamespace(task_id=str(task_id.value), status=status, safe_summary=reason)

    def run(self, *, repository: Path, task_description: str, mode: str, trust_repo: bool):
        repository = Path(repository).resolve(strict=True)
        facts = self.repository_preflight.inspect(repository) if self.repository_preflight is not None else None
        if self.config_source_loader is not None:
            try:
                self.frozen_config = self.config_source_loader.load(repository=repository, base_commit=facts.base_commit)
            except Exception:
                raise RuntimeError("configuration is invalid") from None
        if mode != "real" or trust_repo is not True:
            raise ValueError("real runtime trust is required")
        model = getattr(getattr(self.frozen_config, "llm", None), "model", None)
        if not isinstance(model, str) or not model.strip() or model == "configured-by-user":
            raise RuntimeError("provider model is not configured")
        llm = self.provider_factory.create(frozen_config=self.frozen_config)
        task_id = self._task_id()
        workspace = self.workspace.prepare(repository=repository, task_id=task_id, frozen_config=self.frozen_config, trust_repo=trust_repo)
        if getattr(workspace, "isolated", False) is not True or Path(workspace.root).resolve() == repository:
            raise ValueError("verified isolated workspace is required")
        session_store = self._stores()
        self._activate_components(workspace, task_id)
        core = self._core(session_store, llm)
        self.application = ApplicationService(core, session_store=session_store)
        session = CoreSession(task_id=task_id, user_task=task_description, config_summary=f"real:{self.frozen_config.sha256}", workspace_summary=getattr(workspace, "summary", "verified isolated workspace"))
        session_store.save(session)
        session_store.bind_workspace(task_id, workspace)
        outcome = self.application.run_task(task_id)
        return self._view(outcome, task_id)

    def status(self, task_id):
        domain_id = task_id if isinstance(task_id, TaskId) else TaskId(value=task_id)
        session_store = self._stores()
        self.application = ApplicationService(session_store=session_store)
        session = self.application.status_task(domain_id)
        return self._view(session, domain_id)

    def resume(self, task_id):
        domain_id = task_id if isinstance(task_id, TaskId) else TaskId(value=task_id)
        session_store = self._stores()
        readonly_application = ApplicationService(session_store=session_store)
        session = readonly_application.status_task(domain_id)
        if session.status is not TaskStatus.PAUSED_FOR_HUMAN:
            raise ValueError("task is not resumable")
        workspace_payload = session_store.load_workspace(domain_id)
        if self.config_source_loader is not None and workspace_payload is not None:
            try:
                self.frozen_config = self.config_source_loader.load(
                    repository=Path(workspace_payload["repository_root"]),
                    base_commit=workspace_payload["base_commit"],
                )
            except Exception:
                raise RuntimeError("configuration is invalid") from None
        if hasattr(self.workspace, "validate_resume") and workspace_payload is not None:
            from coding_agent_harness.adapters.git.worktree import VerifiedWorkspace

            workspace = self.workspace.validate_resume(workspace=VerifiedWorkspace.model_validate(workspace_payload), frozen_config=self.frozen_config)
        else:
            workspace = SimpleNamespace(root=Path(workspace_payload["root"])) if workspace_payload else None
        if workspace is not None:
            self._activate_components(workspace, domain_id)
        llm = self.provider_factory.create(frozen_config=self.frozen_config)
        core = self._core(session_store, llm)
        self.application = ApplicationService(core, session_store=session_store)
        outcome = self.application.resume_task(domain_id)
        return self._view(outcome, domain_id)


def build_real_runtime(*, data_root, frozen_config, provider_factory, workspace, action_executor, full_test_runner, patch_preparer, patch_safety_resolver, task_id_factory=None, component_factory=None, repository_preflight=None, config_source_loader=None):
    return _RealRuntime(
        data_root=data_root,
        frozen_config=frozen_config,
        provider_factory=provider_factory,
        workspace=workspace,
        action_executor=action_executor,
        full_test_runner=full_test_runner,
        patch_preparer=patch_preparer,
        patch_safety_resolver=patch_safety_resolver,
        task_id_factory=task_id_factory,
        component_factory=component_factory,
        repository_preflight=repository_preflight,
        config_source_loader=config_source_loader,
    )


def build_default_real_runtime(
    *,
    data_root=None,
    frozen_config=None,
    provider_factory=None,
    workspace=None,
    command_launcher=None,
    command_launcher_factory=None,
    git_launcher=None,
    git_launcher_factory=None,
    repository_preflight=None,
    config_source_loader=None,
    trusted_python=None,
    workspace_hasher=None,
):
    from platformdirs import user_config_path, user_data_path
    import os
    import sys

    from coding_agent_harness.adapters.config.source_loader import LayeredConfigSource
    from coding_agent_harness.adapters.git.worktree import GitWorktreeAdapter
    from coding_agent_harness.adapters.process.pytest_runner import PytestTestRunner
    from coding_agent_harness.adapters.process.runner import SubprocessLauncher
    from coding_agent_harness.adapters.runtime.action_executor import (
        CoreTestRunner,
        ProductionActionExecutor,
        WorkspacePatchPreparer,
        WorkspacePatchSafetyResolver,
        parsed_marker,
        workspace_sha256,
    )
    from coding_agent_harness.application.preflight import RepositoryPreflight
    from coding_agent_harness.patching.applier import apply as apply_patch

    resolved_root = Path(data_root or user_data_path("coding-agent-harness", appauthor=False)).resolve()
    if command_launcher is not None and command_launcher_factory is not None:
        raise ValueError("command launcher injection is ambiguous")
    if git_launcher is not None and git_launcher_factory is not None:
        raise ValueError("Git launcher injection is ambiguous")

    class LazyCommandLauncher:
        def __init__(self, factory) -> None:
            self.factory = factory
            self.instance = None

        def launch(self, request):
            if self.instance is None:
                self.instance = self.factory()
            return self.instance.launch(request)

    action_launcher_factory = command_launcher_factory or (lambda: command_launcher or SubprocessLauncher())
    action_launcher = LazyCommandLauncher(action_launcher_factory)
    git_process_factory = git_launcher_factory or (lambda: git_launcher or SubprocessLauncher())
    git_process_launcher = LazyCommandLauncher(git_process_factory)
    config_holder = {"value": frozen_config}

    class CommandBridge:
        def __init__(self, launcher, *, git_only=False) -> None:
            self.launcher = launcher
            self.git_only = git_only

        def __call__(self, argv, cwd, shell, env):
            from coding_agent_harness.adapters.process.runner import LaunchRequest, LaunchStatus

            config = config_holder["value"]
            timeout = 120 if self.git_only or config is None else config.tests.timeout_seconds
            output_limit = 65_536 if self.git_only or config is None else config.limits.max_process_output_bytes
            result = self.launcher.launch(LaunchRequest(
                argv=tuple(argv), cwd=Path(cwd), shell=shell, env=env,
                timeout_seconds=timeout,
                stdout_limit=output_limit,
                stderr_limit=output_limit,
            ))
            return SimpleNamespace(
                returncode=result.exit_code if result.status is LaunchStatus.COMPLETED else 1,
                stdout=result.stdout.decode("utf-8", errors="replace"),
                stderr=result.stderr.decode("utf-8", errors="replace"),
            )

    action_bridge = CommandBridge(action_launcher)
    git_bridge = CommandBridge(git_process_launcher, git_only=True)
    workspace_boundary = workspace or GitWorktreeAdapter(data_root=resolved_root, launcher=git_bridge)

    effective_preflight = repository_preflight
    effective_config_source = config_source_loader
    if frozen_config is None:
        effective_preflight = effective_preflight or RepositoryPreflight(launcher=git_bridge)

        def repository_reader(repository, base_commit):
            env = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "LANG", "LC_ALL"}}
            listed = git_bridge(("git", "ls-tree", "--name-only", base_commit, "--", ".coding-harness.toml"), repository, False, env)
            if listed.returncode != 0:
                raise RuntimeError("configuration is invalid")
            if listed.stdout.strip() == "":
                return None
            if listed.stdout.strip() != ".coding-harness.toml":
                raise RuntimeError("configuration is invalid")
            result = git_bridge(("git", "show", f"{base_commit}:.coding-harness.toml"), repository, False, env)
            if result.returncode != 0:
                raise RuntimeError("configuration is invalid")
            return result.stdout.encode("utf-8")

        effective_config_source = effective_config_source or LayeredConfigSource(
            user_config=user_config_path("coding-agent-harness", appauthor=False) / "config.toml",
            repository_reader=repository_reader,
        )

    def components(verified_workspace, task_id, artifact_store, effective_config):
        config_holder["value"] = effective_config
        root = Path(verified_workspace.root).resolve(strict=True)
        pytest_runner = PytestTestRunner(
            launcher=action_launcher,
            artifact_store=artifact_store,
            workspace_hasher=workspace_hasher or workspace_sha256,
            parser=parsed_marker,
            trusted_python=str(Path(trusted_python or sys.executable).resolve()),
        )
        tests = CoreTestRunner(
            runner=pytest_runner,
            task_id=task_id,
            root=root,
            base_commit=verified_workspace.base_commit,
            config=effective_config,
        )
        executor = ProductionActionExecutor.for_workspace(
            root=root,
            base_commit=verified_workspace.base_commit,
            capabilities=effective_config.capabilities,
            git_launcher=action_bridge,
            diagnostic_launcher=action_bridge,
            patch_applier=apply_patch,
            test_runner=tests,
        )
        return SimpleNamespace(
            action_executor=executor,
            full_test_runner=tests,
            patch_preparer=WorkspacePatchPreparer(root),
            patch_safety_resolver=WorkspacePatchSafetyResolver(root, effective_config.capabilities),
        )

    runtime = build_real_runtime(
        data_root=resolved_root,
        frozen_config=frozen_config,
        provider_factory=provider_factory or _SystemProviderFactory(),
        workspace=workspace_boundary,
        action_executor=_UnavailableDependency(),
        full_test_runner=_UnavailableDependency(),
        patch_preparer=_UnavailableDependency(),
        patch_safety_resolver=_UnavailableDependency(),
        component_factory=components,
        repository_preflight=effective_preflight,
        config_source_loader=effective_config_source,
    )
    runtime.command_launcher = action_launcher
    runtime.command_bridge = action_bridge
    runtime.trusted_python = str(Path(trusted_python or sys.executable).resolve())
    return runtime


@dataclass(frozen=True)
class _DemoSafety:
    symlink: bool = False
    capability_missing: bool = False
    demo_escape: bool = False


class _DemoPreparer:
    def prepare(self, action):
        return prepare(action.diff, PatchSnapshot({"counter.py": b"return 0\n"}))


class _DemoSafetyResolver:
    def resolve(self, prepared):
        return _DemoSafety()


class _DemoExecutor:
    def execute(self, action):
        return ActionExecution(safe_summary="inspection completed", source_revision="demo-a")

    def execute_patch(self, action, prepared):
        return ActionExecution(safe_summary="patch applied", source_revision="demo-b")


class _DemoFullTests:
    def run(self):
        output_ref = ArtifactRef(artifact_id=uuid4(), task_id=_DEMO_TASK_ID, schema_id="sanitized_test_output", schema_version=1, media_type="application/json", byte_length=2, sha256=_HASH)
        parsed_ref = ArtifactRef(artifact_id=uuid4(), task_id=_DEMO_TASK_ID, schema_id="parsed_result", schema_version=1, media_type="application/json", byte_length=2, sha256=_HASH)
        run_id = uuid4()
        test_run = TestRun(
            run_id=run_id,
            task_id=_DEMO_TASK_ID,
            phase=TestPhase.POST_PATCH,
            outcome=TestRunOutcome.PASSED,
            command=FrozenCommand(argv=["pytest", "-q"]),
            base_commit="a" * 40,
            config_sha256=_HASH,
            environment_sha256=_HASH,
            workspace_before_sha256=_HASH,
            workspace_after_sha256=_HASH,
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            finished_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
            duration_ms=1000,
            exit_code=0,
            sanitized_output_ref=output_ref,
            parsed_result_ref=parsed_ref,
        )
        parsed = ParsedTestResult(run_id=run_id, phase=TestPhase.POST_PATCH, outcome=ParsedOutcome.PASSED, node_ids=(), exception_type=None, summary="pytest passed", in_project_frames=(), truncated=False, source_revision="demo-b")
        return ActionExecution(safe_summary="pytest passed", source_revision="demo-b", test_run=test_run, parsed_result=parsed)


class _DemoRuntime:
    def __init__(self) -> None:
        self._views: dict[str, object] = {}

    def run(self, *, repository: Path, task_description: str, mode: str, trust_repo: bool):
        if mode != "demo" or not trust_repo:
            raise ValueError("demo trust is required")
        session_store = InMemorySessionStore()
        session_store.save(CoreSession(task_id=_DEMO_TASK_ID, user_task=task_description, config_summary="demo", workspace_summary="offline demo workspace"))
        diff = "--- a/counter.py\n+++ b/counter.py\n@@ -1 +1 @@\n-return 0\n+return 1\n"
        core = HarnessCore(
            llm=ScriptedMockLLM([{"type": "apply_patch", "diff": diff}]),
            session_store=session_store,
            context_builder=ContextBuilder(),
            policy_engine=PolicyEngine(),
            action_executor=_DemoExecutor(),
            full_test_runner=_DemoFullTests(),
            feedback_engine=FeedbackEngine(),
            patch_preparer=_DemoPreparer(),
            patch_safety_resolver=_DemoSafetyResolver(),
        )
        outcome = ApplicationService(core).run_task(_DEMO_TASK_ID)
        view = SimpleNamespace(task_id=str(_DEMO_TASK_ID.value), status=outcome.status, safe_summary=outcome.reason)
        self._views[str(_DEMO_TASK_ID.value)] = view
        return view

    def status(self, task_id: UUID):
        try:
            return self._views[str(task_id)]
        except KeyError:
            raise KeyError("task not found") from None

    def resume(self, task_id: UUID):
        view = self.status(task_id)
        if view.status is not TaskStatus.PAUSED_FOR_HUMAN:
            raise ValueError("task is not resumable")
        return view


_REPAIR_DEMO_PATCH = "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n def add(a: int, b: int) -> int:\n-    return a - b\n+    return a + b\n"
_REPAIR_DEMO_ACTIONS = (
    {"type": "read_file", "path": "calculator.py"},
    {"type": "search_code", "path": ".", "query": "return a - b", "case_sensitive": True},
    {"type": "apply_patch", "diff": _REPAIR_DEMO_PATCH},
)


def _demo_workspace_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    ignored_parts = {".git", ".pytest_cache", "__pycache__"}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or any(part in ignored_parts for part in path.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8", errors="strict")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


class _ScriptedProviderFactory:
    def __init__(self, actions) -> None:
        self.actions = tuple(actions)
        self.clients = []

    def create(self, *, frozen_config):
        del frozen_config
        client = ScriptedMockLLM(self.actions)
        self.clients.append(client)
        return client


class _OfflineDemoRuntime:
    def __init__(self, *, data_root, scripted_actions, max_actions, trusted_python) -> None:
        from coding_agent_harness.config.defaults import BUILTIN_CONFIG
        from coding_agent_harness.config.resolver import resolve_config

        limits = {} if max_actions is None else {"max_actions": max_actions}
        self.data_root = Path(data_root).resolve()
        self.data_root.joinpath("worktrees").mkdir(parents=True, exist_ok=True)
        self.provider_factory = _ScriptedProviderFactory(scripted_actions)
        self.frozen_config = resolve_config(BUILTIN_CONFIG, {"llm": {"model": "offline-scripted"}, "limits": limits}, {}, "real")
        self.runtime = build_default_real_runtime(
            data_root=self.data_root,
            frozen_config=self.frozen_config,
            provider_factory=self.provider_factory,
            trusted_python=trusted_python,
            workspace_hasher=_demo_workspace_sha256,
        )
        self.external_action_calls = 0
        self.patch_apply_calls = 0

    def run(self, *, repository: Path, task_description: str, mode: str, trust_repo: bool):
        if mode != "demo":
            raise ValueError("demo mode is required")
        view = self.runtime.run(repository=repository, task_description=task_description, mode="real", trust_repo=trust_repo)
        self._update_counters(view.task_id)
        return view

    def status(self, task_id: UUID):
        return self.runtime.status(task_id)

    def resume(self, task_id: UUID):
        view = self.runtime.resume(task_id)
        self._update_counters(view.task_id)
        return view

    def _update_counters(self, task_id: str) -> None:
        session = self.runtime.application.session_store.load(TaskId(value=UUID(task_id)))
        external = {"list_files", "read_file", "search_code", "run_tests", "git_diff", "git_status", "run_diagnostic"}
        self.external_action_calls = sum(entry.action_type in external for entry in session.history)
        self.patch_apply_calls = sum(entry.action_type == "apply_patch" for entry in session.history)


class _DemoRouter:
    def __init__(self, *, data_root, trusted_python) -> None:
        self.data_root = data_root
        self.trusted_python = trusted_python
        self.active = None
        self.legacy = _DemoRuntime()

    @staticmethod
    def _recognized(repository: Path) -> bool:
        return repository.joinpath("calculator.py").is_file() and repository.joinpath("tests", "test_calculator.py").is_file()

    def _offline(self, actions=()):
        return _OfflineDemoRuntime(data_root=self.data_root, scripted_actions=actions, max_actions=None, trusted_python=self.trusted_python)

    def run(self, *, repository: Path, task_description: str, mode: str, trust_repo: bool):
        repository = Path(repository).resolve(strict=True)
        if not self._recognized(repository):
            return self.legacy.run(repository=repository, task_description=task_description, mode=mode, trust_repo=trust_repo)
        self.active = self._offline(_REPAIR_DEMO_ACTIONS)
        return self.active.run(repository=repository, task_description=task_description, mode=mode, trust_repo=trust_repo)

    def status(self, task_id: UUID):
        if self.active is not None:
            return self.active.status(task_id)
        try:
            return self._offline().status(task_id)
        except KeyError:
            return self.legacy.status(task_id)

    def resume(self, task_id: UUID):
        if self.active is not None:
            return self.active.resume(task_id)
        return self._offline().resume(task_id)


def build_demo_runtime(*, keyring_factory=None, provider_factory=None, data_root=None, scripted_actions=None, max_actions=None, trusted_python=None):
    del keyring_factory, provider_factory
    if data_root is None:
        from platformdirs import user_data_path

        data_root = user_data_path("coding-agent-harness", appauthor=False) / "demo"
    if scripted_actions is not None:
        return _OfflineDemoRuntime(data_root=data_root, scripted_actions=scripted_actions, max_actions=max_actions, trusted_python=trusted_python)
    return _DemoRouter(data_root=data_root, trusted_python=trusted_python)
