from __future__ import annotations

from coding_agent_harness.config.models import CapabilitySet
from coding_agent_harness.domain.actions import ValidatedAction
from coding_agent_harness.domain.tool_payloads import ToolPayloadUnion
from coding_agent_harness.domain.enums import ToolErrorCode
from coding_agent_harness.domain.models import ToolPayload, ToolResult


class TypedToolDispatcher:
    def __init__(self, registry: dict[type, object] | None = None) -> None:
        self.handler_calls: list[str] = []
        self.registry = registry or {}

    def dispatch(self, action: ValidatedAction, capabilities: CapabilitySet) -> ToolResult[ToolPayloadUnion]:
        handler = self.registry.get(type(action))
        if handler is None:
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.UNSUPPORTED, sanitized_message="action is not registered")
        if capabilities.mode != "real":
            return ToolResult(ok=False, payload=None, error_code=ToolErrorCode.UNSUPPORTED, sanitized_message="action is not available")
        self.handler_calls.append(type(action).__name__)
        return handler()
