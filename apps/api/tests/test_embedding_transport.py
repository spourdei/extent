"""Wire-contract tests for the OpenAI-compatible embedding transport."""

import json
from types import TracebackType
from urllib.request import Request

import pytest

from extent_api.providers import embeddings
from extent_api.providers.embeddings import UrlLibEmbeddingTransport


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
        assert size == 2_000_001
        return self._body


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://models.example.com/v1", "https://models.example.com/v1/embeddings"),
        (
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            "https://generativelanguage.googleapis.com/v1beta/openai/embeddings",
        ),
        (
            "https://models.example.com/v1/embeddings/",
            "https://models.example.com/v1/embeddings",
        ),
    ],
)
def test_embedding_transport_uses_portable_embeddings_contract(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    expected_url: str,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: int) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(b'{"data":[]}')

    monkeypatch.setattr(embeddings, "urlopen", fake_urlopen)

    body = UrlLibEmbeddingTransport().embed(
        api_key="secret-key",
        base_url=base_url,
        dimensions=1_536,
        inputs=("first", "second"),
        model="embedding-model",
        timeout_seconds=45,
    )

    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url == expected_url
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {
        "dimensions": 1_536,
        "input": ["first", "second"],
        "model": "embedding-model",
    }
    assert captured["timeout"] == 45
    assert body == b'{"data":[]}'
