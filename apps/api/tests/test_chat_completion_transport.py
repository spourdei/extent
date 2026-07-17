"""Wire-contract tests for the OpenAI-compatible chat transport."""

import json
from types import TracebackType
from urllib.request import Request

import pytest

from extent_api.providers import chat_completion
from extent_api.providers.chat_completion import (
    ChatCompletionAnswerProvider,
    UrlLibChatCompletionTransport,
)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, size: int) -> bytes:
        assert size == 1_000_001
        return self._body


class _StaticTransport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[dict[str, str]] = []

    def complete(
        self,
        *,
        api_key: str,
        base_url: str,
        messages: list[dict[str, str]],
        model: str,
        timeout_seconds: int,
    ) -> str:
        del api_key, base_url, model, timeout_seconds
        self.messages = messages
        return self.content


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
        (
            "https://models.example.com/v1/chat/completions/",
            "https://models.example.com/v1/chat/completions",
        ),
    ],
)
def test_chat_transport_uses_portable_chat_completions_contract(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    expected_url: str,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: int) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(b'{"choices":[{"message":{"content":"result"}}]}')

    monkeypatch.setattr(chat_completion, "urlopen", fake_urlopen)
    messages = [
        {"role": "system", "content": "Return JSON."},
        {"role": "user", "content": "Question"},
    ]

    content = UrlLibChatCompletionTransport().complete(
        api_key="secret-key",
        base_url=base_url,
        messages=messages,
        model="model-name",
        timeout_seconds=45,
    )

    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url == expected_url
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"messages": messages, "model": "model-name"}
    assert captured["timeout"] == 45
    assert content == "result"


def test_chat_provider_returns_strict_query_interpretation() -> None:
    transport = _StaticTransport(
        json.dumps(
            {
                "canonical_question": ("What is the sum of Recovery across Claim_ID records?"),
                "intents": ["aggregate"],
                "mode": "structured",
                "needs_clarification": None,
            }
        )
    )
    provider = ChatCompletionAnswerProvider(
        api_key="secret",
        base_url="https://models.example.com/v1",
        model="model-name",
        timeout_seconds=30,
        transport=transport,
    )

    interpretation = provider.interpret(question="Add up Recovery over Claim_ID entries.")

    assert interpretation.mode == "structured"
    assert interpretation.intents == ["aggregate"]
    assert interpretation.canonical_question.endswith("Claim_ID records?")
    assert json.loads(transport.messages[1]["content"]) == {
        "question": "Add up Recovery over Claim_ID entries."
    }
