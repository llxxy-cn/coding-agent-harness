from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from coding_agent_harness.domain.enums import ActionStatus, ApprovalStatus, TaskStatus
from coding_agent_harness.domain.models import TaskId, ValidatedAction

from .migrations import apply_migrations


def _tid(task_id: TaskId) -> str:
    return str(task_id.value)


class SQLiteStateStore:
    def __init__(self, database: str | Path | sqlite3.Connection) -> None:
        if isinstance(database, sqlite3.Connection):
            self.connection = database
            self._owned = False
        else:
            self.connection = sqlite3.connect(str(database), isolation_level=None)
            self._owned = True
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        apply_migrations(self.connection)

    def create_task(self, task_id: TaskId, status: TaskStatus) -> None:
        self.connection.execute("INSERT INTO tasks(task_id,status) VALUES (?,?)", (_tid(task_id), status.value))

    def get_task_status(self, task_id: TaskId) -> TaskStatus:
        row = self.connection.execute("SELECT status FROM tasks WHERE task_id=?", (_tid(task_id),)).fetchone()
        if row is None:
            raise KeyError("task not found")
        return TaskStatus(row[0])

    def load_snapshot(self, task_id: TaskId) -> dict[str, object] | None:
        task = self.connection.execute("SELECT status FROM tasks WHERE task_id=?", (_tid(task_id),)).fetchone()
        if task is None:
            return None
        actions = [dict(row) for row in self.connection.execute("SELECT action_id, status FROM actions WHERE task_id=? ORDER BY action_id", (_tid(task_id),))]
        approvals = [dict(row) for row in self.connection.execute("SELECT action_id, status FROM approvals WHERE task_id=? ORDER BY action_id", (_tid(task_id),))]
        intents = [dict(row) for row in self.connection.execute("SELECT action_id, created_at FROM execution_intents WHERE task_id=? ORDER BY action_id", (_tid(task_id),))]
        return {"task_id": _tid(task_id), "status": TaskStatus(task[0]), "actions": actions, "approvals": approvals, "intents": intents}

    def compare_and_set_task_status(self, task_id: TaskId, expected: TaskStatus, target: TaskStatus) -> bool:
        cur = self.connection.execute("UPDATE tasks SET status=? WHERE task_id=? AND status=?", (target.value, _tid(task_id), expected.value))
        return cur.rowcount == 1

    def create_action(self, task_id: TaskId, action_id: UUID, status: ActionStatus) -> None:
        self.connection.execute("INSERT INTO actions(task_id,action_id,status) VALUES (?,?,?)", (_tid(task_id), str(action_id), status.value))

    def get_action_status(self, task_id: TaskId, action_id: UUID) -> ActionStatus:
        row = self.connection.execute("SELECT status FROM actions WHERE task_id=? AND action_id=?", (_tid(task_id), str(action_id))).fetchone()
        if row is None:
            raise KeyError("action not found")
        return ActionStatus(row[0])

    def compare_and_set_action_status(self, task_id: TaskId, action_id: UUID, expected: ActionStatus, target: ActionStatus) -> bool:
        cur = self.connection.execute("UPDATE actions SET status=? WHERE task_id=? AND action_id=? AND status=?", (target.value, _tid(task_id), str(action_id), expected.value))
        return cur.rowcount == 1

    def acquire_lease(self, task_id: TaskId, owner: str, ttl_seconds: int = 60) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        until = now + ttl_seconds
        task_key = _tid(task_id)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            task = self.connection.execute(
                "SELECT lease_owner, lease_until FROM tasks WHERE task_id=?",
                (task_key,),
            ).fetchone()
            if task is None:
                self.connection.rollback()
                return False
            active = self.connection.execute(
                "SELECT task_id FROM tasks WHERE lease_owner IS NOT NULL AND lease_until >= ?",
                (now,),
            ).fetchone()
            if active is not None and active[0] != task_key:
                self.connection.rollback()
                return False
            cur = self.connection.execute(
                "UPDATE tasks SET lease_owner=?, lease_until=? WHERE task_id=? AND (lease_until IS NULL OR lease_until < ? OR lease_owner=?)",
                (owner, until, task_key, now, owner),
            )
            if cur.rowcount != 1:
                self.connection.rollback()
                return False
            self.connection.commit()
            return True
        except Exception:
            self.connection.rollback()
            raise

    def create_approval(self, task_id: TaskId, action_id: UUID, status: ApprovalStatus) -> None:
        self.connection.execute("INSERT INTO approvals(task_id,action_id,status) VALUES (?,?,?)", (_tid(task_id), str(action_id), status.value))

    def get_approval_status(self, task_id: TaskId, action_id: UUID) -> ApprovalStatus:
        row = self.connection.execute("SELECT status FROM approvals WHERE task_id=? AND action_id=?", (_tid(task_id), str(action_id))).fetchone()
        if row is None:
            raise KeyError("approval not found")
        return ApprovalStatus(row[0])

    def record_approval_decision(self, task_id: TaskId, action_id: UUID, decision: ApprovalStatus) -> None:
        self.connection.execute("UPDATE approvals SET status=? WHERE task_id=? AND action_id=? AND status=?", (decision.value, _tid(task_id), str(action_id), ApprovalStatus.PENDING.value))

    def log_intent(self, task_id: TaskId, action_id: UUID, action: ValidatedAction) -> None:
        # The action argument satisfies the frozen port; identity is bound by
        # the actions table's (task_id, action_id) key. Task 8 owns canonical
        # Action content binding; Task 5 must not invent a canonical algorithm.
        self.connection.execute("INSERT INTO execution_intents(task_id, action_id) VALUES (?, ?)", (_tid(task_id), str(action_id)))

    def consume_approval(self, task_id: TaskId, action_id: UUID, target_status: ActionStatus) -> bool:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute("SELECT status FROM approvals WHERE task_id=? AND action_id=?", (_tid(task_id), str(action_id))).fetchone()
            if row is None or row[0] != ApprovalStatus.APPROVED.value:
                self.connection.rollback()
                return False
            action = self.connection.execute("SELECT status FROM actions WHERE task_id=? AND action_id=?", (_tid(task_id), str(action_id))).fetchone()
            if action is None or action[0] != ActionStatus.AWAITING_APPROVAL.value:
                self.connection.rollback()
                return False
            if target_status is not ActionStatus.EXECUTING:
                self.connection.rollback()
                raise ValueError("approval consumption target must be executing")
            changed = self.connection.execute("UPDATE approvals SET status=? WHERE task_id=? AND action_id=? AND status=?", (ApprovalStatus.CONSUMED.value, _tid(task_id), str(action_id), ApprovalStatus.APPROVED.value)).rowcount
            if changed != 1:
                self.connection.rollback()
                return False
            changed = self.connection.execute("UPDATE actions SET status=? WHERE task_id=? AND action_id=? AND status=?", (ActionStatus.EXECUTING.value, _tid(task_id), str(action_id), ActionStatus.AWAITING_APPROVAL.value)).rowcount
            if changed != 1:
                self.connection.rollback()
                return False
            self.connection.execute("INSERT INTO execution_intents(task_id,action_id) VALUES (?,?)", (_tid(task_id), str(action_id)))
            self.connection.commit()
            return True
        except Exception:
            self.connection.rollback()
            raise

    def intent_count(self, task_id: TaskId, action_id: UUID) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM execution_intents WHERE task_id=? AND action_id=?", (_tid(task_id), str(action_id))).fetchone()[0]

    def recover_inflight(self) -> None:
        self.connection.execute("UPDATE actions SET status=? WHERE status=?", (ActionStatus.UNKNOWN_OUTCOME.value, ActionStatus.EXECUTING.value))

    def can_retry_action(self, task_id: TaskId, action_id: UUID) -> bool:
        return self.get_action_status(task_id, action_id) not in {ActionStatus.UNKNOWN_OUTCOME, ActionStatus.INTERRUPTED}
