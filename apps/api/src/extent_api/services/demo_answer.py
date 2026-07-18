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
from extent_api.token_forms import tokens_equivalent

_WORD = re.compile(r"[a-z0-9]+")
_DATE_VALUE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|"
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4}\b",
    re.I,
)
_NON_DATE_MATERIAL = re.compile(
    r"(?:[$€£]|\b(?:USD|CAD|EUR|GBP)\b)\s*\d|\b\d+(?:\.\d+)?\s*%|"
    r"\b(?=[A-Z0-9_/-]*[A-Z])(?=[A-Z0-9_/-]*\d)[A-Z][A-Z0-9]*(?:[-_/][A-Z0-9]+)+\b",
    re.I,
)
_MATERIAL_VALUE = re.compile(
    rf"(?:{_NON_DATE_MATERIAL.pattern})|(?:{_DATE_VALUE.pattern})",
    re.I,
)
_TEMPORAL_QUESTION = re.compile(
    r"^\s*when\b|\b(?:date|dated|effective|expiration|expire[ds]?|issued|period|renewal)\b",
    re.I,
)
_NEGATED_ISSUANCE = re.compile(
    r"\b(?:had\s+not|has\s+not|not|never)\s+(?:yet\s+)?(?:been\s+)?issued\b|"
    r"\bissued\b.{0,40}\b(?:not\s+received|pending)\b",
    re.I,
)
_WHO_VERBAL_QUESTION = re.compile(
    r"^\s*who\s+(?:(?:can|could|did|does|may|might|must|should|will|would)\s+)?"
    r"(?P<verb>[^\W\d_]+)\b",
    re.I,
)
_STOP_WORDS = frozenset(
    {
        "about",
        "and",
        "are",
        "did",
        "do",
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
        passage = next(
            (
                candidate
                for candidate in sorted(
                    passages,
                    key=lambda item: _relevance(item, question=question),
                    reverse=True,
                )
                if _passage_matches_question(candidate, question=question)
            ),
            None,
        )
        if passage is None:
            return AnswerDraft(claims=[], summary="No matching sample evidence was found.")
        quote = passage.exact_quote.strip()
        claim_text = _extractive_claim_text(quote, question=question)
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
                    text=_bounded_claim_text(claim_text),
                )
            ],
            summary="Answered directly from the best-matching prepared sample evidence.",
        )


def _relevance(passage: ModelPassage, *, question: str) -> tuple[int, int, int, int]:
    question_tokens = _tokens(question)
    quote_tokens = _tokens(passage.exact_quote)
    source_tokens = _tokens(passage.source_name)
    return (
        3 * _token_overlap(question_tokens, quote_tokens)
        + _token_overlap(question_tokens, source_tokens)
        + int(_MATERIAL_VALUE.search(passage.exact_quote) is not None) * 4,
        int("\t" in passage.exact_quote),
        int(bool(quote_tokens - question_tokens)),
        -len(passage.exact_quote),
    )


def _token_overlap(left: frozenset[str], right: frozenset[str]) -> int:
    return sum(
        any(tokens_equivalent(left_token, right_token) for right_token in right)
        for left_token in left
    )


def _passage_has_requested_value(quote: str, *, question: str) -> bool:
    if _TEMPORAL_QUESTION.search(question) is not None:
        if _DATE_VALUE.search(quote) is None:
            return False
        return not (
            "issued" in question.casefold() and _NEGATED_ISSUANCE.search(quote) is not None
        )
    if re.match(r"^\s*(?:how\s+much|what)\b", question, re.I):
        return _NON_DATE_MATERIAL.search(quote) is not None
    return True


def _passage_matches_question(passage: ModelPassage, *, question: str) -> bool:
    if not _passage_has_requested_value(passage.exact_quote, question=question):
        return False
    question_tokens = _tokens(question)
    evidence_tokens = _tokens(f"{passage.source_name} {passage.exact_quote}")
    verbal = _WHO_VERBAL_QUESTION.search(question)
    if verbal is not None and verbal.group("verb").casefold() not in {
        "are",
        "is",
        "was",
        "were",
    }:
        verb = verbal.group("verb").casefold()
        if not any(tokens_equivalent(verb, token) for token in evidence_tokens):
            return False
    minimum_matches = 1 if len(question_tokens) <= 1 else max(2, len(question_tokens) * 2 // 3)
    return (
        _token_overlap(
            question_tokens,
            evidence_tokens,
        )
        >= minimum_matches
    )


def _extractive_claim_text(quote: str, *, question: str) -> str:
    cells = [" ".join(cell.split()) for cell in quote.split("\t")]
    if len(cells) >= 2 and cells[0] and cells[1]:
        question_tokens = _tokens(question)
        label_tokens = _tokens(cells[0])
        if _token_overlap(question_tokens, label_tokens) >= min(2, len(question_tokens)):
            return f"{cells[0]}: {cells[1]}"
    return quote


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _WORD.findall(value.casefold())
        if len(token) >= 3 and token not in _STOP_WORDS
    )


def _bounded_claim_text(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 800 else normalized[:797].rstrip() + "..."
