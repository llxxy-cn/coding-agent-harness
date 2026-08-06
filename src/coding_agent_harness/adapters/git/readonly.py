from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from coding_agent_harness.domain.enums import ToolErrorCode
from coding_agent_harness.domain.models import ToolResult
from coding_agent_harness.domain.tool_payloads import GitDiffPayload, GitStatusPayload


class ReadonlyGitAdapter:
    def __init__(self, root: str | Path, base_commit: str, launcher: Callable) -> None:
        self.root = Path(root).resolve()
        self.base_commit = base_commit
        self.launcher = launcher

    def _run(self, argv):
        env = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT"}}
        try:
            return self.launcher(argv, self.root, False, env)
        except OSError:
            return None

    def status(self) -> ToolResult:
        completed = self._run(("git", "status", "--porcelain=v1"))
        if completed is None:
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.ENVIRONMENT_ERROR, sanitized_message="git unavailable")
        entries = tuple(sorted(line for line in (completed.stdout or "").splitlines() if line))
        return ToolResult(ok=True, payload=GitStatusPayload(entries=entries), error_code=None, sanitized_message=None)

    def diff(self) -> ToolResult:
        completed = self._run(("git", "diff", self.base_commit, "--"))
        if completed is None:
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.ENVIRONMENT_ERROR, sanitized_message="git unavailable")
        raw = completed.stdout or ""
        diff = raw[:1_048_576]
        return ToolResult(ok=True, payload=GitDiffPayload(diff=diff, truncated=len(raw) > len(diff)), error_code=None, sanitized_message=None)
