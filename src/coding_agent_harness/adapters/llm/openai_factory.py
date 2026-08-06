from __future__ import annotations

from openai import OpenAI

from coding_agent_harness.adapters.credentials.keyring_store import KeyringCredentialStore
from coding_agent_harness.adapters.llm.openai_client import OpenAILLMClient
from coding_agent_harness.config.models import FrozenConfig
from coding_agent_harness.security.provider_errors import ProviderError, ProviderErrorCode


class OpenAIClientFactory:
    def __init__(self, *, sdk_constructor=None) -> None:
        self._sdk_constructor = sdk_constructor or OpenAI

    def __repr__(self) -> str:
        return "OpenAIClientFactory()"

    def create(
        self,
        *,
        credential_store: KeyringCredentialStore,
        frozen_config: FrozenConfig,
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> OpenAILLMClient:
        try:
            api_key = credential_store._read_for_provider()
            sdk_client = self._sdk_constructor(api_key=api_key, timeout=timeout_seconds, max_retries=0)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE) from None
        return OpenAILLMClient(
            client=sdk_client,
            frozen_config=frozen_config,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )
