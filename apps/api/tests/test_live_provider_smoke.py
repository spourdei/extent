"""Opt-in, credential-safe smoke tests for configured model providers.

Enable with ``EXTENT_RUN_LIVE_SMOKE=1``. Credentials are obtained exclusively
through ``Settings`` and are never printed or included in assertion messages.
"""

from __future__ import annotations

import math
import os
from uuid import UUID

import pytest

from extent_api.config import Settings
from extent_api.providers.chat_completion import (
    ChatCompletionAnswerProvider,
    ModelGenerationError,
    ModelPassage,
)
from extent_api.providers.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingGenerationError,
    OpenAICompatibleEmbeddingProvider,
)

pytestmark = pytest.mark.live


def _live_settings() -> Settings:
    if os.environ.get("EXTENT_RUN_LIVE_SMOKE") != "1":
        pytest.skip("live provider smoke is opt-in")
    return Settings()


def test_live_embedding_retrieval_uses_fresh_compatible_vectors() -> None:
    settings = _live_settings()
    if not settings.embedding_api_configured:
        pytest.skip("embedding provider is not configured")
    assert settings.embedding_api_key is not None
    provider = OpenAICompatibleEmbeddingProvider(
        api_key=settings.embedding_api_key.get_secret_value(),
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        timeout_seconds=settings.model_timeout_seconds,
    )
    documents = [
        "The cobalt observatory stores a brass astrolabe.",
        "The riverside studio schedules ceramic glazing.",
        "The orchard ledger records pear harvest weights.",
    ]
    try:
        vectors = provider.embed([*documents, "Where is the brass astrolabe stored?"])
    except EmbeddingGenerationError as error:
        pytest.fail(f"embedding smoke failed: {error.code}", pytrace=False)
    query = vectors[-1]
    scores = [_cosine(query, vector) for vector in vectors[:-1]]

    assert provider.dimensions == EMBEDDING_DIMENSIONS == 1_536
    assert len(query) == EMBEDDING_DIMENSIONS
    assert scores.index(max(scores)) == 0


def test_live_answer_model_gold_context_returns_schema_valid_multifield_conflict() -> None:
    settings = _live_settings()
    if not settings.model_api_configured:
        pytest.skip("answer provider is not configured")
    assert settings.model_api_key is not None
    provider = ChatCompletionAnswerProvider(
        api_key=settings.model_api_key.get_secret_value(),
        base_url=settings.model_base_url,
        model=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
    )
    controlled_id = UUID("70000000-0000-4000-8000-000000000001")
    narrative_id = UUID("70000000-0000-4000-8000-000000000002")
    try:
        draft = provider.generate(
            history=[],
            passages=[
                ModelPassage(
                    block_id=controlled_id,
                    exact_quote=(
                        "Approved change-control register AC-17: Unit Q tier is amber and "
                        "quota is 18."
                    ),
                    locator_label="line 1",
                    source_name="controlled-register.txt",
                ),
                ModelPassage(
                    block_id=narrative_id,
                    exact_quote="Unsupported narrative note: Unit Q tier is green.",
                    locator_label="line 1",
                    source_name="narrative-note.txt",
                ),
            ],
            question=(
                "What are Unit Q's authoritative tier and quota, and is there a material "
                "conflict?"
            ),
        )
    except ModelGenerationError as error:
        pytest.fail(f"answer smoke failed: {error.code}", pytrace=False)

    assert 1 <= len(draft.claims) <= 3
    assert all(1 <= len(claim.evidence) <= 2 for claim in draft.claims)
    assert all(
        reference.block_id in {controlled_id, narrative_id}
        for claim in draft.claims
        for reference in claim.evidence
    )
    combined = " ".join(
        [
            draft.summary,
            *(claim.text for claim in draft.claims),
            *(claim.value or "" for claim in draft.claims),
        ]
    ).casefold()
    assert "amber" in combined
    assert "18" in combined


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)
