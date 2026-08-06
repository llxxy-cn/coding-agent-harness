import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from coding_agent_harness.adapters.artifacts.local_store import LocalArtifactStore
from coding_agent_harness.domain.models import ArtifactRef, TaskId


def test_local_store_round_trip_and_manifest_verification(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    task_id = TaskId(value=uuid4())
    content = b"safe sanitized output"
    reference = store.put(task_id, "sanitized_test_output", 1, "application/json", content)
    assert store.load(reference) == content
    assert reference.byte_length == len(content)
    assert reference.sha256 == hashlib.sha256(content).hexdigest()
    assert not list(tmp_path.rglob("*.db"))


def test_local_store_rejects_escape_and_symlinked_artifacts(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    task_id = TaskId(value=uuid4())
    with pytest.raises(ValueError):
        store.put(task_id, "../escape", 1, "application/json", b"x")
    with pytest.raises(ValueError):
        store.put(task_id, "ok", 1, "application/json; charset=utf-8", b"x")
    reference = store.put(task_id, "ok", 1, "application/json", b"x")
    path = store.path_for(reference)
    path.unlink()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")
    try:
        os.symlink(outside, path)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires SeCreateSymbolicLinkPrivilege")
        raise
    with pytest.raises(ValueError):
        store.load(reference)


def test_local_store_detects_length_and_same_length_corruption(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    task_id = TaskId(value=uuid4())
    reference = store.put(task_id, "ok", 1, "application/json", b"original")
    path = store.path_for(reference)
    path.write_bytes(b"short")
    with pytest.raises(ValueError):
        store.load(reference)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        store.load(reference)


def test_local_store_rejects_cross_task_reference_and_schema_has_no_raw_output_columns(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    task_id = TaskId(value=uuid4())
    other_task = TaskId(value=uuid4())
    reference = store.put(task_id, "ok", 1, "application/json", b"x")
    other_ref = reference.model_copy(update={"task_id": other_task})
    with pytest.raises(ValueError):
        store.load(other_ref)
    schema = Path(__file__).parents[3] / "src" / "coding_agent_harness" / "adapters" / "sqlite" / "schema.sql"
    schema_text = schema.read_text(encoding="utf-8").lower()
    assert "raw_stdout" not in schema_text
    assert "raw_stderr" not in schema_text
    assert "raw_output" not in schema_text
