"""Single-generation language-model port."""

from typing import Protocol, TypeVar, runtime_checkable


ContextT = TypeVar("ContextT")


@runtime_checkable
class LLMClient(Protocol[ContextT]):
    def generate(self, context: ContextT) -> str | dict[str, object]: ...
