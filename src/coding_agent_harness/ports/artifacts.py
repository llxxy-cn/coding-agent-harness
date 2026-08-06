"""Validated artifact persistence port."""

from typing import Protocol, runtime_checkable

from coding_agent_harness.domain.models import ArtifactRef, TaskId


@runtime_checkable
class ArtifactStore(Protocol):
    def put(self, task_id: TaskId, schema_id: str, schema_version: int, media_type: str, content: bytes) -> ArtifactRef: ...

    def load(self, artifact_ref: ArtifactRef) -> bytes: ...
