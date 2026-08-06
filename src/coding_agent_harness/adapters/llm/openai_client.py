from __future__ import annotations

import json

from coding_agent_harness.config.models import FrozenConfig
from coding_agent_harness.core.context import PromptContext
from coding_agent_harness.security.provider_errors import ProviderError, ProviderErrorCode


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


class OpenAILLMClient:
    def __init__(self, *, client, frozen_config: FrozenConfig, timeout_seconds: int, max_output_tokens: int) -> None:
        model = frozen_config.llm.model
        if not isinstance(model, str) or not model:
            raise ValueError("provider model is not configured")
        self._client = client
        self._model = model
        self._timeout_seconds = _positive_int(timeout_seconds, "timeout_seconds")
        self._max_output_tokens = _positive_int(max_output_tokens, "max_output_tokens")

    def __repr__(self) -> str:
        return f"OpenAILLMClient(model={self._model!r})"

    def generate(self, context: PromptContext) -> str | dict[str, object]:
        request_input = json.dumps(context.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        try:
            response = self._client.responses.create(
                model=self._model,
                input=request_input,
                max_output_tokens=self._max_output_tokens,
                timeout=self._timeout_seconds,
            )
        except Exception:
            raise ProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE) from None
        output = getattr(response, "output_text", None)
        if isinstance(output, str) and output.strip():
            return output
        raise ProviderError(ProviderErrorCode.INVALID_PROVIDER_RESPONSE)
