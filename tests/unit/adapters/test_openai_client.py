from __future__ import annotations

from types import SimpleNamespace

import pytest

from coding_agent_harness.config.defaults import BUILTIN_CONFIG
from coding_agent_harness.config.resolver import resolve_config
from coding_agent_harness.core.context import PromptContext


SECRET = "sk-test-provider-secret"


def _config():
    return resolve_config(BUILTIN_CONFIG, {"llm": {"model": "gpt-test-model"}}, {}, "real")


def _context() -> PromptContext:
    return PromptContext(
        user_task="fix counter",
        config_summary="real provider",
        action_schema=("git_status",),
        workspace_summary="clean governed workspace",
        history=(),
        feedback_summary=None,
        remaining_actions=4,
        remaining_feedback=2,
        sha256="a" * 64,
    )


class FakeResponses:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeSdkClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def test_single_response_uses_frozen_model_and_injected_limits() -> None:
    from coding_agent_harness.adapters.llm.openai_client import OpenAILLMClient

    responses = FakeResponses(SimpleNamespace(output_text='{"type":"git_status"}'))
    client = OpenAILLMClient(
        client=FakeSdkClient(responses),
        frozen_config=_config(),
        timeout_seconds=60,
        max_output_tokens=4096,
    )

    result = client.generate(_context())

    assert result == '{"type":"git_status"}'
    assert len(responses.calls) == 1
    request = responses.calls[0]
    assert request["model"] == "gpt-test-model"
    assert request["timeout"] == 60
    assert request["max_output_tokens"] == 4096
    assert "fix counter" in str(request["input"])
    assert "tools" not in request


def test_non_string_response_is_rejected_at_provider_boundary() -> None:
    from coding_agent_harness.adapters.llm.openai_client import OpenAILLMClient
    from coding_agent_harness.security.provider_errors import ProviderError

    for output in ({"type": "git_status"}, ["git_status"], None):
        responses = FakeResponses(SimpleNamespace(output_text=output))
        client = OpenAILLMClient(client=FakeSdkClient(responses), frozen_config=_config(), timeout_seconds=60, max_output_tokens=4096)
        with pytest.raises(ProviderError, match="provider response is invalid"):
            client.generate(_context())


def test_malformed_provider_response_raises_stable_error() -> None:
    from coding_agent_harness.adapters.llm.openai_client import OpenAILLMClient
    from coding_agent_harness.security.provider_errors import ProviderError

    client = OpenAILLMClient(client=FakeSdkClient(FakeResponses(SimpleNamespace(output_text=None))), frozen_config=_config(), timeout_seconds=60, max_output_tokens=4096)

    with pytest.raises(ProviderError, match="provider response is invalid") as caught:
        client.generate(_context())
    assert SECRET not in str(caught.value)


def test_sdk_exception_is_redacted_and_not_retried() -> None:
    from coding_agent_harness.adapters.llm.openai_client import OpenAILLMClient
    from coding_agent_harness.security.provider_errors import ProviderError

    responses = FakeResponses(error=RuntimeError(f"authorization failed for {SECRET}"))
    client = OpenAILLMClient(client=FakeSdkClient(responses), frozen_config=_config(), timeout_seconds=60, max_output_tokens=4096)

    with pytest.raises(ProviderError, match="provider request failed") as caught:
        client.generate(_context())
    assert SECRET not in str(caught.value)
    assert len(responses.calls) == 1


def test_provider_limits_reject_bool_strings_and_non_positive_values() -> None:
    from coding_agent_harness.adapters.llm.openai_client import OpenAILLMClient

    sdk = FakeSdkClient(FakeResponses(SimpleNamespace(output_text='{"type":"git_status"}')))
    invalid = ((True, 4096), ("60", 4096), (0, 4096), (60, False), (60, "4096"), (60, -1))
    for timeout_seconds, max_output_tokens in invalid:
        with pytest.raises((TypeError, ValueError)):
            OpenAILLMClient(client=sdk, frozen_config=_config(), timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens)
