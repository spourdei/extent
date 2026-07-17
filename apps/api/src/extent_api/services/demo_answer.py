"""Provider-backed answers with a deterministic extractive fallback for the public demo."""

from __future__ import annotations

import re
from typing import Protocol
from uuid import uuid5

from extent_api.providers.chat_completion import (
    ModelConversationTurn,
    ModelGenerationError,
    ModelPassage,
    ModelQueryInterpretation,
)
from extent_api.services.demo_corpus import DEMO_NAMESPACE
from extent_api.services.publication import (
    AnswerDraft,
    ClaimDraft,
    DraftEvidenceRef,
)

_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "about",
        "and",
        "are",
        "does",
        "for",
        "from",
        "how",
        "is",
        "the",
        "this",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
    }
)


class _AnswerProvider(Protocol):
    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft: ...


class ResilientDemoAnswerProvider:
    """Keep the sample answerable when its optional external model is unavailable."""

    def __init__(self, delegate: _AnswerProvider | None = None) -> None:
        self._delegate = delegate

    def interpret(self, *, question: str) -> ModelQueryInterpretation | None:
        if self._delegate is None:
            return None
        interpret = getattr(self._delegate, "interpret", None)
        if not callable(interpret):
            return None
        try:
            result = interpret(question=question)
        except ModelGenerationError:
            return None
        return result if isinstance(result, ModelQueryInterpretation) else None

    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        if self._delegate is not None:
            try:
                return self._delegate.generate(
                    history=history,
                    passages=passages,
                    question=question,
                )
            except ModelGenerationError:
                pass

        if not passages:
            return AnswerDraft(claims=[], summary="No matching sample evidence was found.")
        passage = max(passages, key=lambda candidate: _relevance(candidate, question=question))
        quote = passage.exact_quote.strip()
        return AnswerDraft(
            claims=[
                ClaimDraft(
                    claim_id=uuid5(
                        DEMO_NAMESPACE,
                        f"extractive-answer:{question.casefold()}:{passage.block_id}",
                    ),
                    evidence=[
                        DraftEvidenceRef(
                            block_id=passage.block_id,
                            exact_quote=quote,
                        )
                    ],
                    relation="fact",
                    text=quote,
                )
            ],
            summary="Answered directly from the best-matching prepared sample evidence.",
        )


def _relevance(passage: ModelPassage, *, question: str) -> tuple[int, int]:
    question_tokens = _tokens(question)
    quote_tokens = _tokens(passage.exact_quote)
    source_tokens = _tokens(passage.source_name)
    return (
        3 * len(question_tokens & quote_tokens) + len(question_tokens & source_tokens),
        -len(passage.exact_quote),
    )


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _WORD.findall(value.casefold())
        if len(token) >= 3 and token not in _STOP_WORDS
    )
