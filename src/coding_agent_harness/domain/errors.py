"""Stable protocol error messages safe for persistence and feedback."""

from .enums import ProtocolErrorCode


PROTOCOL_ERROR_MESSAGES = {
    ProtocolErrorCode.INVALID_JSON: "Action must be a valid JSON object.",
    ProtocolErrorCode.INVALID_TOP_LEVEL: "Action must be a JSON object.",
    ProtocolErrorCode.MISSING_TYPE: "Action field 'type' is required.",
    ProtocolErrorCode.INVALID_TYPE: "Action field 'type' must match ^[a-z][a-z0-9_]{0,63}$.",
    ProtocolErrorCode.UNKNOWN_ACTION: "Action type is not supported.",
    ProtocolErrorCode.SCHEMA_VIOLATION: "Action fields do not match the required schema.",
}
