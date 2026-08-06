from __future__ import annotations

from typing import TypeAlias

from .models import ToolPayload


class FileEntry(ToolPayload):
    path: str


class ListFilesPayload(ToolPayload):
    files: tuple[FileEntry, ...]


class ReadFilePayload(ToolPayload):
    text: str
    truncated: bool
    next_start_line: int | None = None


class SearchMatch(ToolPayload):
    path: str
    line: int
    column: int
    text: str


class SearchCodePayload(ToolPayload):
    matches: tuple[SearchMatch, ...]
    truncated: bool


class GitStatusPayload(ToolPayload):
    entries: tuple[str, ...]


class GitDiffPayload(ToolPayload):
    diff: str
    truncated: bool


class DiagnosticPayload(ToolPayload):
    diagnostic_id: str
    exit_code: int
    output: str


ToolPayloadUnion: TypeAlias = ListFilesPayload | ReadFilePayload | SearchCodePayload | GitStatusPayload | GitDiffPayload | DiagnosticPayload
