"""Deterministic capability routing for evidence questions.

The planner deliberately identifies *capabilities*, not business vocabulary.  It
keeps ordinary scalar lookups on the bounded retrieval path while preventing
questions that make set-wide claims from being answered from a top-k sample.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

QueryMode = Literal["direct", "exhaustive", "mixed", "structured"]
QueryIntent = Literal[
    "aggregate",
    "compare",
    "completeness",
    "exceptions",
    "filter",
    "group",
    "join",
    "list",
    "lookup",
    "summary",
]

_WORD = re.compile(r"[^\W_]+|\d+", re.UNICODE)
_LIST = re.compile(r"\b(?:all|each|every|complete\s+list|list|enumerate|show\s+all)\b", re.I)
_AGGREGATE = re.compile(
    r"\b(?:average|avg|count|how\s+many|maximum|max|minimum|min|sum)\b",
    re.I,
)
_TOTAL = re.compile(r"\b(?:aggregate|total)\b", re.I)
_SET_NOUN = re.compile(r"\b(?:dataset|file|record|row|source|table)s?\b", re.I)
_GROUP = re.compile(r"\b(?:break\s*down|group(?:ed)?|per)\b|\bby\b", re.I)
_BREAKDOWN = re.compile(r"\b(?:break\s*down|group(?:ed)?(?:\s+\w+){0,4}\s+by)\b", re.I)
_FILTER = re.compile(
    r"\b(?:after|before|below|except|excluding|greater\s+than|less\s+than|"
    r"missing|not\s+equal|over|under|where|with(?:out)?)\b|(?:<=|>=|!=|<>|<|>)",
    re.I,
)
_EXCEPTIONS = re.compile(
    r"\b(?:anomal(?:y|ies)|duplicate|exception|fail(?:s|ed|ing)?|missing|"
    r"not\s+match(?:ed|ing)?|outlier|unmatched|violation)\b",
    re.I,
)
_UNIVERSAL = re.compile(
    r"\b(?:does|do|did)\s+(?:all|each|every)\b|"
    r"\b(?:all|each|every)\b.{0,80}\b(?:have|match|meet|satisfy|contain|equal|"
    r"include|comply)\b|\bcompleteness\b|"
    r"\b(?:is|are)\s+(?:the\s+)?(?:data|dataset|file|records?|rows?|sources?|tables?)\s+complete\b|"
    r"\b(?:data|dataset|file|records?|rows?|sources?|tables?)\s+(?:is|are)\s+complete\b",
    re.I,
)
_JOIN = re.compile(
    r"\b(?:join|reconcile|cross[- ]?reference|unmatched|cardinality|"
    r"one[- ]to[- ]many|many[- ]to[- ]one)\b|"
    r"\b(?:across|between|against)\b.{0,80}\b(?:files?|sources?|tables?|datasets?)\b",
    re.I,
)
_COMPARE = re.compile(r"\b(?:compare|comparison|conflict|contradict|difference)\b", re.I)
_SUMMARY = re.compile(r"\b(?:summari[sz]e|summary|overview)\b", re.I)


@dataclass(frozen=True)
class QueryPlan:
    intents: tuple[QueryIntent, ...]
    mode: QueryMode
    requires_complete_data: bool

    @property
    def is_analytical(self) -> bool:
        return self.mode in {"structured", "mixed"}


def plan_query(question: str) -> QueryPlan:
    """Classify the execution capability required by ``question``.

    A universal, aggregate, joined, filtered, grouped, or exhaustive request is
    never safe to answer from retrieved samples.  A comparison is marked mixed:
    it may be a table reconciliation or a narrative conflict, which the caller
    resolves after inspecting complete ready data.
    """

    normalized = " ".join(question.strip().split())
    intents: set[QueryIntent] = set()
    if _LIST.search(normalized):
        intents.add("list")
    if _AGGREGATE.search(normalized) or (
        _TOTAL.search(normalized)
        and (
            _SET_NOUN.search(normalized)
            or _LIST.search(normalized)
            or re.search(r"\b(?:by|per|across|where|for\s+each|of\s+all)\b", normalized, re.I)
        )
    ):
        intents.add("aggregate")
    if _BREAKDOWN.search(normalized):
        # A breakdown is an implicit grouped count even when the user does not
        # spell out an aggregate verb (for example, "break down items by state").
        intents.add("aggregate")
        intents.add("group")
    elif _GROUP.search(normalized) and "aggregate" in intents:
        intents.add("group")
    if _FILTER.search(normalized):
        intents.add("filter")
    if _EXCEPTIONS.search(normalized):
        intents.add("exceptions")
    if _UNIVERSAL.search(normalized):
        intents.add("completeness")
    if _JOIN.search(normalized):
        intents.add("join")
    if _COMPARE.search(normalized):
        intents.add("compare")
    if _SUMMARY.search(normalized):
        intents.add("summary")
    if not intents:
        intents.add("lookup")

    complete_intents = {
        "aggregate",
        "compare",
        "completeness",
        "group",
        "join",
        "list",
    }
    requires_complete_data = bool(intents & complete_intents)
    if "filter" in intents and (
        intents & {"aggregate", "list"} or _SET_NOUN.search(normalized)
    ):
        requires_complete_data = True
    if "exceptions" in intents and (
        _SET_NOUN.search(normalized)
        or "list" in intents
        or "join" in intents
        or re.search(r"\bidentify\s+(?:the\s+)?exceptions?\b", normalized, re.I)
    ):
        requires_complete_data = True
    if "summary" in intents and (
        _SET_NOUN.search(normalized)
        or "list" in intents
        or re.search(r"\b(?:fields?|columns?)\b", normalized, re.I)
    ):
        requires_complete_data = True
    if "join" in intents or "compare" in intents:
        mode: QueryMode = "mixed"
    elif requires_complete_data and intents & {
        "aggregate",
        "completeness",
        "exceptions",
        "filter",
        "group",
        "summary",
    }:
        mode = "structured"
    elif "list" in intents:
        mode = "exhaustive"
    else:
        mode = "direct"
    return QueryPlan(
        intents=tuple(sorted(intents)),
        mode=mode,
        requires_complete_data=requires_complete_data,
    )


def normalized_query_tokens(value: str) -> tuple[str, ...]:
    """Expose the planner's schema-neutral tokenization to structured execution."""

    return tuple(match.group(0).casefold() for match in _WORD.finditer(value))
