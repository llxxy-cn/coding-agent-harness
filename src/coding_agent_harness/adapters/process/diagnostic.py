from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from coding_agent_harness.config.models import CapabilitySet
from coding_agent_harness.domain.actions import RunDiagnosticAction
from coding_agent_harness.domain.enums import ToolErrorCode
from coding_agent_harness.domain.models import ToolResult
from coding_agent_harness.domain.tool_payloads import DiagnosticPayload


class DiagnosticRunner:
    def __init__(self, root: str | Path, capabilities: CapabilitySet, launcher: Callable) -> None:
        self.root = Path(root).resolve()
        self.capabilities = capabilities
        self.last_argv: tuple[str, ...] | None = None
        self.last_shell: bool | None = None
        self.invocations: list[tuple[str, ...]] = []
        self.launcher = launcher

    def run(self, action: RunDiagnosticAction) -> ToolResult:
        if action.diagnostic_id not in self.capabilities.diagnostic_ids:
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.UNSUPPORTED, sanitized_message="diagnostic is not enabled")
        templates = {"ruff_check": ("ruff", "check", "."), "mypy_check": ("mypy", ".")}
        argv = templates.get(action.diagnostic_id)
        if argv is None or action.arguments:
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.INVALID_REQUEST, sanitized_message="diagnostic arguments are not allowed")
        self.last_argv, self.last_shell = argv, False
        self.invocations.append(argv)
        try:
            env = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT"}}
            completed = self.launcher(argv, self.root, False, env)
            return ToolResult(ok=True, payload=DiagnosticPayload(diagnostic_id=action.diagnostic_id, exit_code=completed.returncode, output=(completed.stdout or "")[:65536]), error_code=None, sanitized_message=None)
        except TimeoutError:
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.TIMEOUT, sanitized_message="diagnostic timed out")
        except OSError:
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.ENVIRONMENT_ERROR, sanitized_message="diagnostic environment unavailable")
