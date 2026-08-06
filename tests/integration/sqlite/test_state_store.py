import sqlite3
from uuid import uuid4

import pytest

from coding_agent_harness.domain.actions import GitStatusAction
from coding_agent_harness.adapters.sqlite.state_store import SQLiteStateStore
from coding_agent_harness.domain.enums import ActionStatus, TaskStatus
from coding_agent_harness.domain.models import TaskId
from coding_agent_harness.ports.state import StateStore
from coding_agent_harness.ports.artifacts import ArtifactStore
from coding_agent_harness.adapters.artifacts.local_store import LocalArtifactStore


def _task() -> TaskId:
    return TaskId(value=uuid4())


def test_state_store_persists_enum_values_and_cas_checks_only_precondition(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "state.db")
    task_id = _task()
    store.create_task(task_id, TaskStatus.CREATED)
    assert store.get_task_status(task_id) is TaskStatus.CREATED
    assert store.compare_and_set_task_status(task_id, TaskStatus.CREATED, TaskStatus.PREFLIGHT)
    assert not store.compare_and_set_task_status(task_id, TaskStatus.CREATED, TaskStatus.SUCCEEDED)
    raw = sqlite3.connect(tmp_path / "state.db").execute(
        "SELECT status FROM tasks WHERE task_id=?", (str(task_id.value),)
    ).fetchone()[0]
    assert raw == TaskStatus.PREFLIGHT.value


def test_one_active_lease_and_crash_recovery_disable_retry(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "state.db")
    first, second = _task(), _task()
    store.create_task(first, TaskStatus.CREATED)
    store.create_task(second, TaskStatus.CREATED)
    assert store.acquire_lease(first, "worker-a")
    assert not store.acquire_lease(second, "worker-b")
    action_id = uuid4()
    store.create_action(first, action_id, ActionStatus.EXECUTING)
    store.recover_inflight()
    assert store.get_action_status(first, action_id) is ActionStatus.UNKNOWN_OUTCOME
    assert not store.can_retry_action(first, action_id)


def test_real_adapters_satisfy_task3_runtime_protocols(tmp_path) -> None:
    assert isinstance(SQLiteStateStore(tmp_path / "state.db"), StateStore)
    assert isinstance(LocalArtifactStore(tmp_path / "artifacts"), ArtifactStore)


def test_log_intent_is_persistent_and_duplicate_is_rejected(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "state.db")
    task_id = _task()
    action_id = uuid4()
    store.create_task(task_id, TaskStatus.CREATED)
    store.create_action(task_id, action_id, ActionStatus.READY)
    action = GitStatusAction(type="git_status")
    store.log_intent(task_id, action_id, action)
    assert store.intent_count(task_id, action_id) == 1
    with pytest.raises(sqlite3.IntegrityError):
        store.log_intent(task_id, action_id, action)
    assert store.intent_count(task_id, action_id) == 1
