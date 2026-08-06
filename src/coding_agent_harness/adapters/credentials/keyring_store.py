from __future__ import annotations

from typing import Protocol

from coding_agent_harness.security.provider_errors import ProviderError, ProviderErrorCode


CredentialError = ProviderError


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, value: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class KeyringCredentialStore:
    def __init__(self, *, backend: KeyringBackend, service_name: str = "coding-agent-harness", username: str = "openai") -> None:
        self._backend = backend
        self._service_name = service_name
        self._username = username

    def __repr__(self) -> str:
        return "KeyringCredentialStore(configured=<redacted>)"

    __str__ = __repr__

    def set(self, value: str) -> None:
        self._validate_value(value)
        if self._read_optional() is not None:
            raise ProviderError(ProviderErrorCode.CREDENTIAL_UNAVAILABLE)
        self._write(value)

    def status(self) -> bool:
        return self._read_optional() is not None

    def update(self, value: str) -> None:
        self._validate_value(value)
        if self._read_optional() is None:
            raise ProviderError(ProviderErrorCode.CREDENTIAL_MISSING)
        self._write(value)

    def clear(self) -> None:
        if self._read_optional() is None:
            return
        try:
            self._backend.delete_password(self._service_name, self._username)
        except Exception:
            raise ProviderError(ProviderErrorCode.CREDENTIAL_UNAVAILABLE) from None

    def _read_for_provider(self) -> str:
        value = self._read_optional()
        if value is None:
            raise ProviderError(ProviderErrorCode.CREDENTIAL_MISSING)
        return value

    def _read_optional(self) -> str | None:
        try:
            value = self._backend.get_password(self._service_name, self._username)
        except Exception:
            raise ProviderError(ProviderErrorCode.CREDENTIAL_UNAVAILABLE) from None
        if value is not None and (not isinstance(value, str) or not value):
            raise ProviderError(ProviderErrorCode.CREDENTIAL_UNAVAILABLE)
        return value

    def _write(self, value: str) -> None:
        try:
            self._backend.set_password(self._service_name, self._username, value)
        except Exception:
            raise ProviderError(ProviderErrorCode.CREDENTIAL_UNAVAILABLE) from None

    @staticmethod
    def _validate_value(value: str) -> None:
        if not isinstance(value, str) or not value or any(char in value for char in "\r\n\x00"):
            raise ProviderError(ProviderErrorCode.CREDENTIAL_UNAVAILABLE)
