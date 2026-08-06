from __future__ import annotations

import inspect

import pytest

from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.ports.credentials import CredentialStore


SECRET = "sk-test-keyring-secret"


class FakeKeyringBackend:
    def __init__(self, value: str | None = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get_password", service, username))
        if self.error is not None:
            raise self.error
        return self.value

    def set_password(self, service: str, username: str, value: str) -> None:
        self.calls.append(("set_password", service, username, value))
        if self.error is not None:
            raise self.error
        self.value = value

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete_password", service, username))
        if self.error is not None:
            raise self.error
        self.value = None


class FakeSdkConstructor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.client = object()

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.client


def _config():
    return resolve_config(BUILTIN_CONFIG, {"llm": {"model": "gpt-test-model"}}, {}, "real")


def test_public_credential_protocol_has_no_plaintext_reader() -> None:
    public_methods = {name for name, value in inspect.getmembers(CredentialStore) if callable(value) and not name.startswith("_")}
    assert public_methods == {"set", "status", "update", "clear"}
    assert not public_methods.intersection({"get", "read", "resolve"})


def test_keyring_store_supports_lifecycle_without_returning_values() -> None:
    from coding_agent_harness.adapters.credentials.keyring_store import KeyringCredentialStore

    backend = FakeKeyringBackend()
    store = KeyringCredentialStore(backend=backend)
    assert store.status() is False
    assert store.set(SECRET) is None
    assert store.status() is True
    assert store.update("sk-test-updated") is None
    assert store.clear() is None
    assert store.status() is False


def test_keyring_store_repr_and_status_do_not_disclose_secret() -> None:
    from coding_agent_harness.adapters.credentials.keyring_store import KeyringCredentialStore

    store = KeyringCredentialStore(backend=FakeKeyringBackend(SECRET))
    assert store.status() is True
    assert SECRET not in repr(store)
    assert SECRET not in str(store)


def test_factory_reads_key_internally_and_only_sdk_constructor_receives_it() -> None:
    from coding_agent_harness.adapters.credentials.keyring_store import KeyringCredentialStore
    from coding_agent_harness.adapters.llm.openai_factory import OpenAIClientFactory

    store = KeyringCredentialStore(backend=FakeKeyringBackend(SECRET))
    sdk_constructor = FakeSdkConstructor()
    factory = OpenAIClientFactory(sdk_constructor=sdk_constructor)

    llm = factory.create(credential_store=store, frozen_config=_config(), timeout_seconds=60, max_output_tokens=4096)

    assert len(sdk_constructor.calls) == 1
    assert sdk_constructor.calls[0]["api_key"] == SECRET
    assert SECRET not in repr(factory)
    assert SECRET not in repr(llm)
    assert SECRET not in vars(factory).values()


def test_missing_key_fails_before_sdk_construction() -> None:
    from coding_agent_harness.adapters.credentials.keyring_store import CredentialError, KeyringCredentialStore
    from coding_agent_harness.adapters.llm.openai_factory import OpenAIClientFactory

    sdk_constructor = FakeSdkConstructor()
    factory = OpenAIClientFactory(sdk_constructor=sdk_constructor)

    with pytest.raises(CredentialError, match="credential is not configured"):
        factory.create(credential_store=KeyringCredentialStore(backend=FakeKeyringBackend()), frozen_config=_config(), timeout_seconds=60, max_output_tokens=4096)
    assert sdk_constructor.calls == []


def test_keyring_backend_error_is_stable_and_redacted() -> None:
    from coding_agent_harness.adapters.credentials.keyring_store import CredentialError, KeyringCredentialStore

    store = KeyringCredentialStore(backend=FakeKeyringBackend(error=RuntimeError(f"backend leaked {SECRET}")))
    with pytest.raises(CredentialError, match="credential store unavailable") as caught:
        store.status()
    assert SECRET not in str(caught.value)
