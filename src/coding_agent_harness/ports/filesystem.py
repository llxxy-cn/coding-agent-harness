"""Guarded filesystem operation port."""

from typing import Protocol, TypeVar, runtime_checkable

from coding_agent_harness.domain.models import PayloadT, ToolResult, ValidatedAction


FileRequestT = TypeVar("FileRequestT", bound=ValidatedAction)


@runtime_checkable
class FileSystemPort(Protocol[FileRequestT, PayloadT]):
    def execute(self, action: FileRequestT) -> ToolResult[PayloadT]: ...
