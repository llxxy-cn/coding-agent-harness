"""Workspace lifecycle and Git operation port."""

from typing import Protocol, TypeVar, runtime_checkable


WorkspaceRequestT = TypeVar("WorkspaceRequestT")
WorkspaceResultT = TypeVar("WorkspaceResultT")


@runtime_checkable
class WorkspacePort(Protocol[WorkspaceRequestT, WorkspaceResultT]):
    def execute(self, request: WorkspaceRequestT) -> WorkspaceResultT: ...
