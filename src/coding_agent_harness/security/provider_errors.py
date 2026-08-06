from __future__ import annotations

from enum import Enum, unique


@unique
class ProviderErrorCode(str, Enum):
    CREDENTIAL_MISSING = "credential_missing"
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"


_MESSAGES = {
    ProviderErrorCode.CREDENTIAL_MISSING: "credential is not configured",
    ProviderErrorCode.CREDENTIAL_UNAVAILABLE: "credential store unavailable",
    ProviderErrorCode.PROVIDER_UNAVAILABLE: "provider request failed",
    ProviderErrorCode.INVALID_PROVIDER_RESPONSE: "provider response is invalid",
}


class ProviderError(RuntimeError):
    def __init__(self, code: ProviderErrorCode) -> None:
        self.code = code
        self.sanitized_message = _MESSAGES[code]
        super().__init__(self.sanitized_message)

    def __repr__(self) -> str:
        return f"ProviderError(code={self.code.value!r})"
