"""OpenAI-compatible chat adapter with strict JSON validation and bounded I/O."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from extent_api.services.publication import (
    AnswerDraft,
    ClaimDraft,
    DraftEvidenceRef,
)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_MAX_RESPONSE_BYTES = 1_000_000
_CHAT_COMPLETIONS_PATH = "/chat/completions"


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith(_CHAT_COMPLETIONS_PATH):
        return normalized
    return f"{normalized}{_CHAT_COMPLETIONS_PATH}"


class ModelPassage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: UUID
    exact_quote: Annotated[str, Field(min_length=1, max_length=2_000)]
    locator_label: Annotated[str, Field(min_length=1, max_length=80)]
    source_name: Annotated[str, Field(min_length=1, max_length=1_024)]


class ModelConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_summaries: Annotated[list[str], Field(max_length=3)]
    question: Annotated[str, Field(min_length=1, max_length=2_000)]


class ModelGenerationError(RuntimeError):
    def __init__(self, code: Literal["invalid_response", "provider_unavailable"]):
        super().__init__(code)
        self.code = code


class ChatCompletionTransport(Protocol):
    def complete(
        self,
        *,
        api_key: str,
        base_url: str,
        messages: list[dict[str, str]],
        model: str,
        timeout_seconds: int,
    ) -> str: ...


class UrlLibChatCompletionTransport:
    """Small synchronous transport; credentials and provider payloads never leave the API."""

    def complete(
        self,
        *,
        api_key: str,
        base_url: str,
        messages: list[dict[str, str]],
        model: str,
        timeout_seconds: int,
    ) -> str:
        payload = json.dumps(
            {
                "messages": messages,
                "model": model,
            },
            ensure_ascii=False,
        ).encode()
        request = Request(
            _chat_completions_url(base_url),
            data=payload,
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
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            raise ModelGenerationError("provider_unavailable") from error
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ModelGenerationError("invalid_response")
        try:
            decoded = json.loads(body)
            content = decoded["choices"][0]["message"]["content"]
        except (
            IndexError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise ModelGenerationError("invalid_response") from error
        if not isinstance(content, str) or not content.strip():
            raise ModelGenerationError("invalid_response")
        return content


class _GeneratedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _GeneratedEvidenceRef(_GeneratedModel):
    block_id: UUID
    effective_date: date | None = None
    entity: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    exact_quote: Annotated[str, Field(min_length=1, max_length=2_000)]
    field: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    scope: Annotated[str, Field(min_length=1, max_length=240)] | None = None
    value: Annotated[str, Field(min_length=1, max_length=120)] | None = None


class _GeneratedClaim(_GeneratedModel):
    effective_date: date | None = None
    evidence: Annotated[list[_GeneratedEvidenceRef], Field(min_length=1, max_length=2)]
    relation: Literal["fact", "change", "conflict", "unclear"]
    text: Annotated[str, Field(min_length=1, max_length=800)]
    value: Annotated[str, Field(min_length=1, max_length=120)] | None = None


class _GeneratedAnswer(_GeneratedModel):
    claims: Annotated[list[_GeneratedClaim], Field(max_length=3)]
    needs_clarification: Annotated[str, Field(min_length=1, max_length=400)] | None = None
    summary: Annotated[str, Field(min_length=1, max_length=2_000)]


class ChatCompletionAnswerProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int,
        transport: ChatCompletionTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport or UrlLibChatCompletionTransport()

    def generate(
        self,
        *,
        history: Sequence[ModelConversationTurn],
        passages: Sequence[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        content = self._transport.complete(
            api_key=self._api_key,
            base_url=self._base_url,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "evidence": [
                                passage.model_dump(mode="json") for passage in passages
                            ],
                            "history": [turn.model_dump(mode="json") for turn in history],
                            "question": question,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self._model,
            timeout_seconds=self._timeout_seconds,
        )
        fenced = _JSON_FENCE.fullmatch(content.strip())
        raw_json = fenced.group(1) if fenced is not None else content
        try:
            generated = _GeneratedAnswer.model_validate_json(raw_json)
        except ValidationError as error:
            raise ModelGenerationError("invalid_response") from error
        if generated.needs_clarification is not None and generated.claims:
            raise ModelGenerationError("invalid_response")
        return AnswerDraft(
            claims=[
                ClaimDraft(
                    claim_id=uuid4(),
                    effective_date=claim.effective_date,
                    evidence=[
                        DraftEvidenceRef(**reference.model_dump())
                        for reference in claim.evidence
                    ],
                    relation=claim.relation,
                    text=claim.text,
                    value=claim.value,
                )
                for claim in generated.claims
            ],
            needs_clarification=generated.needs_clarification,
            summary=generated.summary,
        )


_SYSTEM_PROMPT = """You draft evidence-bounded answers for a deterministic verifier.
Return exactly one JSON object and no Markdown. Use this schema:
{
  "summary": "short answer or abstention",
  "needs_clarification": null,
  "claims": [{
    "relation": "fact|change|conflict|unclear",
    "text": "one atomic claim",
    "value": null,
    "effective_date": null,
    "evidence": [{
      "block_id": "UUID copied from evidence",
      "exact_quote": "verbatim unique substring copied from exact_quote",
      "value": null,
      "effective_date": null,
      "entity": null,
      "field": null,
      "scope": null
    }]
  }]
}
History contains at most two prior user questions and their approved claim summaries. Use it
only to resolve the current question's referent; it is not evidence and cannot support a claim.
If a follow-up referent is not unambiguous from that history, return no claims and put one short
clarifying question in needs_clarification. Otherwise needs_clarification must be null. Cite
only the supplied evidence for every claim.
Answer only what the question asks and order claims from most direct to least direct. For a
singular fact question with a stated scope, return one claim containing the direct final or
overall value. Do not add components, subtotals, or related values unless the question asks for
them. If a value question has no scope and the evidence contains multiple plausible scoped
values, return up to three atomic scoped claims rather than choosing one arbitrarily. Use at
most three claims and at most two evidence branches per claim. Never invent a number, date,
name, fact, quote, or block ID. Exact quotes must be copied byte-for-byte from supplied
evidence. A change or conflict needs two distinct evidence blocks and populated entity, field,
scope, and value fields. When supplied evidence disagrees, do not abstain merely because of
that disagreement: return one atomic conflict claim for each disputed field the question asks
about, with both evidence branches and all comparison fields populated. The deterministic
verifier will decide whether one source has sufficient authority. If the evidence cannot answer
the question, return an empty claims list.
"""
