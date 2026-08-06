from pathlib import Path
import sqlite3

CURRENT_SCHEMA_VERSION = 1


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript((Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8"))
    if connection.execute("SELECT 1 FROM schema_migrations WHERE version=?", (CURRENT_SCHEMA_VERSION,)).fetchone() is None:
        connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (CURRENT_SCHEMA_VERSION,))
    connection.commit()
