import sqlite3

from coding_agent_harness.adapters.sqlite.migrations import apply_migrations


REQUIRED_TABLES = {
    "tasks",
    "actions",
    "tool_results",
    "test_runs",
    "feedback_states",
    "approvals",
    "memories",
    "audit_events",
    "patch_attempts",
    "patch_files",
    "artifact_refs",
    "schema_migrations",
}


def test_migrations_create_versioned_schema_with_foreign_keys() -> None:
    connection = sqlite3.connect(":memory:")
    apply_migrations(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert REQUIRED_TABLES <= tables
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == sorted(set(versions)) and versions


def test_migrations_are_idempotent_and_foreign_keys_reject_orphans() -> None:
    connection = sqlite3.connect(":memory:")
    apply_migrations(connection)
    apply_migrations(connection)
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
    with __import__("pytest").raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO actions(task_id, action_id, status) VALUES (?, ?, ?)",
            ("missing-task", "missing-action", "received"),
        )
