from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

from coding_agent_harness.domain.models import ArtifactRef, TaskId


class LocalArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _validate_schema(self, schema_id: str) -> None:
        if not schema_id or schema_id.startswith(".") or "/" in schema_id or "\\" in schema_id or ".." in schema_id:
            raise ValueError("schema id must be a bounded identifier")

    def put(self, task_id: TaskId, schema_id: str, schema_version: int, media_type: str, content: bytes) -> ArtifactRef:
        self._validate_schema(schema_id)
        if ";" in media_type or "/" not in media_type or media_type != media_type.lower():
            raise ValueError("media type must be lowercase and parameter-free")
        artifact_id = uuid4()
        relative = Path(str(task_id.value)) / f"{artifact_id}.bin"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return ArtifactRef(artifact_id=artifact_id, task_id=task_id, schema_id=schema_id, schema_version=schema_version, media_type=media_type, byte_length=len(content), sha256=hashlib.sha256(content).hexdigest())

    def path_for(self, artifact_ref: ArtifactRef) -> Path:
        return self.root / str(artifact_ref.task_id.value) / f"{artifact_ref.artifact_id}.bin"

    def load(self, artifact_ref: ArtifactRef) -> bytes:
        path = self.path_for(artifact_ref)
        if path.is_symlink():
            raise ValueError("symlinked artifact rejected")
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError("artifact missing") from exc
        if self.root not in resolved.parents:
            raise ValueError("artifact escapes store")
        content = path.read_bytes()
        if len(content) != artifact_ref.byte_length or hashlib.sha256(content).hexdigest() != artifact_ref.sha256:
            raise ValueError("artifact integrity mismatch")
        return content
