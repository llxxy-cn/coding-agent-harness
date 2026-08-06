from __future__ import annotations

import json

from coding_agent_harness.core.harness import CoreSession
from coding_agent_harness.domain.models import TaskId


_SCHEMA_VERSION = 1


class PersistentCoreSessionStore:
    def __init__(self, state_store) -> None:
        self.state_store = state_store
        self.connection = state_store.connection

    def load(self, task_id: TaskId) -> CoreSession:
        row = self.connection.execute("SELECT data_json FROM feedback_states WHERE task_id=?", (str(task_id.value),)).fetchone()
        if row is None:
            raise KeyError("task not found")
        try:
            envelope = json.loads(row[0])
            if not isinstance(envelope, dict) or set(envelope) - {"schema_version", "session", "workspace"} or envelope.get("schema_version") != _SCHEMA_VERSION:
                raise ValueError
            session = CoreSession.model_validate(envelope["session"])
            if session.task_id != task_id or self.state_store.get_task_status(task_id) is not session.status:
                raise ValueError
            return session
        except Exception:
            raise ValueError("session state is invalid") from None

    def save(self, session: CoreSession) -> None:
        task_key = str(session.task_id.value)
        workspace = None
        existing = self.connection.execute("SELECT data_json FROM feedback_states WHERE task_id=?", (task_key,)).fetchone()
        if existing is not None:
            try:
                workspace = json.loads(existing[0]).get("workspace")
            except Exception:
                raise ValueError("session state is invalid") from None
        payload = self._encode(session, workspace)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            task = self.connection.execute("SELECT status FROM tasks WHERE task_id=?", (task_key,)).fetchone()
            if task is None:
                self.connection.execute("INSERT INTO tasks(task_id,status) VALUES (?,?)", (task_key, session.status.value))
            elif task[0] != session.status.value:
                changed = self.connection.execute("UPDATE tasks SET status=? WHERE task_id=? AND status=?", (session.status.value, task_key, task[0])).rowcount
                if changed != 1:
                    raise ValueError("session state conflict")
            self.connection.execute(
                "INSERT INTO feedback_states(task_id,data_json) VALUES (?,?) ON CONFLICT(task_id) DO UPDATE SET data_json=excluded.data_json",
                (task_key, payload),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise ValueError("session state could not be saved") from None

    def bind_workspace(self, task_id: TaskId, workspace) -> None:
        session = self.load(task_id)
        if hasattr(workspace, "model_dump"):
            mapping = workspace.model_dump(mode="json")
        else:
            mapping = {
                "root": str(workspace.root),
                "summary": workspace.summary,
                "isolated": workspace.isolated,
            }
        payload = self._encode(session, mapping)
        self.connection.execute("UPDATE feedback_states SET data_json=? WHERE task_id=?", (payload, str(task_id.value)))

    def load_workspace(self, task_id: TaskId) -> dict[str, object] | None:
        row = self.connection.execute("SELECT data_json FROM feedback_states WHERE task_id=?", (str(task_id.value),)).fetchone()
        if row is None:
            raise KeyError("task not found")
        try:
            value = json.loads(row[0]).get("workspace")
            return value if isinstance(value, dict) else None
        except Exception:
            raise ValueError("session state is invalid") from None

    @staticmethod
    def _encode(session: CoreSession, workspace) -> str:
        envelope = {"schema_version": _SCHEMA_VERSION, "session": session.model_dump(mode="json"), "workspace": workspace}
        return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
