"""Bounded OpenAI-compatible embedding adapter."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from hashlib import sha256
from time import sleep
from typing import Annotated, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from extent_api.config import Settings

EMBEDDING_DIMENSIONS = 1_536
_MAX_BATCH_SIZE = 32
_MAX_INPUT_CHARACTERS = 50_000
_MAX_RESPONSE_BYTES = 2_000_000
_RETRY_DELAYS_SECONDS = (0.25, 1.0)
_EMBEDDINGS_PATH = "/embeddings"

Embedding = tuple[float, ...]


def _embeddings_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith(_EMBEDDINGS_PATH):
        return normalized
    return f"{normalized}{_EMBEDDINGS_PATH}"


class EmbeddingGenerationError(RuntimeError):
    def __init__(self, code: Literal["invalid_response", "provider_unavailable"]):
        super().__init__(code)
        self.code = code


class EmbeddingTransport(Protocol):
    def embed(
        self,
        *,
        api_key: str,
        base_url: str,
        dimensions: int,
        inputs: Sequence[str],
        model: str,
        timeout_seconds: int,
    ) -> bytes: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> list[Embedding]: ...


class UrlLibEmbeddingTransport:
    def embed(
        self,
        *,
        api_key: str,
        base_url: str,
        dimensions: int,
        inputs: Sequence[str],
        model: str,
        timeout_seconds: int,
    ) -> bytes:
        request = Request(
            _embeddings_url(base_url),
            data=json.dumps(
                {"dimensions": dimensions, "input": list(inputs), "model": model}
            ).encode(),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            code: Literal["invalid_response", "provider_unavailable"] = (
                "provider_unavailable"
                if error.code == 429 or error.code >= 500
                else "invalid_response"
            )
            raise EmbeddingGenerationError(code) from error
        except (URLError, OSError, TimeoutError) as error:
            raise EmbeddingGenerationError("provider_unavailable") from error
        if len(body) > _MAX_RESPONSE_BYTES:
            raise EmbeddingGenerationError("invalid_response")
        return body


class _EmbeddingItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    embedding: Annotated[
        list[float], Field(min_length=EMBEDDING_DIMENSIONS, max_length=EMBEDDING_DIMENSIONS)
    ]
    index: Annotated[int, Field(ge=0, lt=_MAX_BATCH_SIZE)]
    object: Literal["embedding"]

    @field_validator("embedding")
    @classmethod
    def values_are_finite(cls, values: list[float]) -> list[float]:
        if not all(math.isfinite(value) for value in values):
            raise ValueError("embedding values must be finite")
        if not any(value != 0 for value in values):
            raise ValueError("embedding vector must be nonzero")
        return values


class _EmbeddingUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data: Annotated[list[_EmbeddingItem], Field(min_length=1, max_length=_MAX_BATCH_SIZE)]
    model: Annotated[str, Field(min_length=1, max_length=160)]
    object: Literal["list"]
    usage: _EmbeddingUsage


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int,
        sleeper: Callable[[float], None] = sleep,
        transport: EmbeddingTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._sleeper = sleeper
        self._timeout_seconds = timeout_seconds
        self._transport = transport or UrlLibEmbeddingTransport()

    @property
    def configuration_id(self) -> str:
        """Non-secret identity preventing vectors from incompatible spaces mixing."""

        material = f"{self._base_url.rstrip('/')}\n{self._model}\n{EMBEDDING_DIMENSIONS}"
        return sha256(material.encode()).hexdigest()

    @property
    def dimensions(self) -> int:
        return EMBEDDING_DIMENSIONS

    @property
    def model(self) -> str:
        return self._model

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        inputs = tuple(texts)
        if not 1 <= len(inputs) <= _MAX_BATCH_SIZE:
            raise ValueError("embedding batch must contain between 1 and 32 inputs")
        if any(not text.strip() or len(text) > _MAX_INPUT_CHARACTERS for text in inputs):
            raise ValueError("embedding input must contain 1 to 50,000 characters")

        for attempt in range(len(_RETRY_DELAYS_SECONDS) + 1):
            try:
                body = self._transport.embed(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    dimensions=EMBEDDING_DIMENSIONS,
                    inputs=inputs,
                    model=self._model,
                    timeout_seconds=self._timeout_seconds,
                )
                return _parse_embeddings(body, expected_count=len(inputs))
            except EmbeddingGenerationError as error:
                if error.code != "provider_unavailable" or attempt == len(
                    _RETRY_DELAYS_SECONDS
                ):
                    raise
                self._sleeper(_RETRY_DELAYS_SECONDS[attempt])
        raise AssertionError("bounded embedding retry loop did not terminate")


def configured_embedding_provider(
    settings: Settings,
) -> OpenAICompatibleEmbeddingProvider | None:
    """Build the one embedding configuration shared by ingestion and querying."""

    if settings.embedding_api_key is None:
        return None
    return OpenAICompatibleEmbeddingProvider(
        api_key=settings.embedding_api_key.get_secret_value(),
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        timeout_seconds=settings.model_timeout_seconds,
    )


def embed_texts(provider: EmbeddingProvider, texts: Sequence[str]) -> list[Embedding]:
    """Embed an arbitrary block sequence using bounded provider batches."""

    inputs = tuple(texts)
    embeddings: list[Embedding] = []
    for offset in range(0, len(inputs), _MAX_BATCH_SIZE):
        batch = inputs[offset : offset + _MAX_BATCH_SIZE]
        generated = provider.embed(batch)
        if len(generated) != len(batch):
            raise EmbeddingGenerationError("invalid_response")
        embeddings.extend(generated)
    return embeddings


def _parse_embeddings(body: bytes, *, expected_count: int) -> list[Embedding]:
    try:
        parsed = _EmbeddingResponse.model_validate_json(body)
    except ValidationError as error:
        raise EmbeddingGenerationError("invalid_response") from error
    ordered = sorted(parsed.data, key=lambda item: item.index)
    if [item.index for item in ordered] != list(range(expected_count)):
        raise EmbeddingGenerationError("invalid_response")
    return [tuple(item.embedding) for item in ordered]
