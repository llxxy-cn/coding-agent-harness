from __future__ import annotations

from pathlib import Path

from coding_agent_harness.domain.actions import ListFilesAction, ReadFileAction, SearchCodeAction
from coding_agent_harness.domain.enums import ToolErrorCode
from coding_agent_harness.domain.models import ToolResult
from coding_agent_harness.domain.tool_payloads import FileEntry, ListFilesPayload, ReadFilePayload, SearchCodePayload, SearchMatch
from coding_agent_harness.security.paths import resolve_guarded_path


def _error(code: ToolErrorCode, message: str) -> ToolResult:
    return ToolResult(ok=False, payload=None, error_code=code, sanitized_message=message)


class LocalFileSystem:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def execute(self, action):
        try:
            if isinstance(action, ListFilesAction):
                facts = resolve_guarded_path(self.root, action.path)
                if not facts.absolute_path.is_dir():
                    return _error(ToolErrorCode.NOT_FOUND, "directory not found")
                iterator = facts.absolute_path.rglob("*") if action.recursive else facts.absolute_path.glob("*")
                entries = []
                for path in iterator:
                    if path.is_file():
                        rel = path.relative_to(self.root).as_posix()
                        resolve_guarded_path(self.root, rel)
                        entries.append(FileEntry(path=rel))
                entries.sort(key=lambda item: item.path)
                return ToolResult(ok=True, payload=ListFilesPayload(files=tuple(entries)), error_code=None, sanitized_message=None)
            if isinstance(action, ReadFileAction):
                facts = resolve_guarded_path(self.root, action.path)
                with facts.absolute_path.open("rb") as handle:
                    data = handle.read(512 * 1024 + 1)
                if b"\x00" in data[:8192]:
                    return _error(ToolErrorCode.UNSUPPORTED, "binary file rejected")
                text = data.decode("utf-8")
                lines = text.splitlines(keepends=True)
                if action.start_line is not None:
                    lines = lines[action.start_line - 1 : action.end_line]
                    selected = "".join(lines)
                    truncated = len(selected.encode("utf-8")) > 512 * 1024
                    if truncated:
                        selected = selected.encode("utf-8")[: 512 * 1024].decode("utf-8", errors="ignore")
                        next_line = action.start_line + selected.count("\n")
                    else:
                        next_line = None
                    return ToolResult(ok=True, payload=ReadFilePayload(text=selected, truncated=truncated, next_start_line=next_line), error_code=None, sanitized_message=None)
                truncated = len(data) > 512 * 1024
                if truncated:
                    text = data[: 512 * 1024].decode("utf-8", errors="ignore")
                return ToolResult(ok=True, payload=ReadFilePayload(text=text, truncated=truncated, next_start_line=(text.count("\n") + 1 if truncated else None)), error_code=None, sanitized_message=None)
            if isinstance(action, SearchCodeAction):
                facts = resolve_guarded_path(self.root, action.path)
                paths = [facts.absolute_path] if facts.absolute_path.is_file() else sorted(facts.absolute_path.rglob("*"), key=lambda p: p.as_posix())
                matches = []
                for path in paths:
                    if not path.is_file():
                        continue
                    rel = path.relative_to(self.root).as_posix()
                    try:
                        text = path.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, OSError):
                        continue
                    for number, line in enumerate(text.splitlines(), 1):
                        haystack = line if action.case_sensitive else line.lower()
                        needle = action.query if action.case_sensitive else action.query.lower()
                        if needle in haystack:
                            matches.append(SearchMatch(path=rel, line=number, column=haystack.index(needle) + 1, text=line))
                            if len(matches) >= 200:
                                break
                    if len(matches) >= 200:
                        break
                matches.sort(key=lambda item: (item.path, item.line, item.column))
                return ToolResult(ok=True, payload=SearchCodePayload(matches=tuple(matches[:200]), truncated=len(matches) >= 200), error_code=None, sanitized_message=None)
            return _error(ToolErrorCode.UNSUPPORTED, "unsupported file action")
        except (ValueError, FileNotFoundError, UnicodeDecodeError, OSError) as exc:
            return _error(ToolErrorCode.SAFETY_VIOLATION, str(exc))
