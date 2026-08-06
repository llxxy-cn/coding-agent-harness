"""Credential lifecycle port that never returns credential values."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CredentialStore(Protocol):
    def set(self, value: str) -> None: ...

    def status(self) -> bool: ...

    def update(self, value: str) -> None: ...

    def clear(self) -> None: ...
