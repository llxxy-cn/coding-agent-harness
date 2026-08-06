from uuid import uuid4
import pytest

from coding_agent_harness.adapters.sqlite.state_store import SQLiteStateStore
from coding_agent_harness.domain.enums import ActionStatus, ApprovalStatus, TaskStatus
from coding_agent_harness.domain.models import TaskId


def test_approval_requires_explicit_resume_and_is_consumed_atomically(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "state.db")
    task_id = TaskId(value=uuid4())
    action_id = uuid4()
    store.create_task(task_id, TaskStatus.AWAITING_APPROVAL)
    store.create_action(task_id, action_id, ActionStatus.AWAITING_APPROVAL)
    store.create_approval(task_id, action_id, ApprovalStatus.PENDING)
    store.record_approval_decision(task_id, action_id, ApprovalStatus.APPROVED)
    assert store.get_action_status(task_id, action_id) is ActionStatus.AWAITING_APPROVAL
    assert store.consume_approval(task_id, action_id, ActionStatus.EXECUTING)
    assert store.get_approval_status(task_id, action_id) is ApprovalStatus.CONSUMED
    assert store.get_action_status(task_id, action_id) is ActionStatus.EXECUTING
    assert store.intent_count(task_id, action_id) == 1
    assert not store.consume_approval(task_id, action_id, ActionStatus.EXECUTING)


def test_failed_atomic_consume_rolls_back_everything(tmp_path) -> None:
    store = SQLiteStateStore(tmp_path / "state.db")
    task_id = TaskId(value=uuid4())
    action_id = uuid4()
    store.create_task(task_id, TaskStatus.AWAITING_APPROVAL)
    store.create_action(task_id, action_id, ActionStatus.AWAITING_APPROVAL)
    store.create_approval(task_id, action_id, ApprovalStatus.PENDING)
    store.record_approval_decision(task_id, action_id, ApprovalStatus.APPROVED)
    store.connection.execute(
        "CREATE TRIGGER fail_intent BEFORE INSERT ON execution_intents BEGIN SELECT RAISE(ABORT, 'injected intent failure'); END"
    )
    with pytest.raises(Exception, match="injected intent failure"):
        store.consume_approval(task_id, action_id, ActionStatus.EXECUTING)
    assert store.get_approval_status(task_id, action_id) is ApprovalStatus.APPROVED
    assert store.get_action_status(task_id, action_id) is ActionStatus.AWAITING_APPROVAL
    assert store.intent_count(task_id, action_id) == 0
