"""Deterministic exhaustive extraction for explicit label/value questions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID, uuid5

from extent_api.database.query_repository import ClaimRecord, PassageRecord, RetrievedBlock
from extent_api.query_models import EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT
from extent_api.token_forms import tokens_equivalent

EXHAUSTIVE_EXTRACTION_POLICY_VERSION = "exhaustive-extraction-policy-v1"

_COMMAND_PREFIX = (
    r"^(?:(?:please|could\s+you|can\s+you|would\s+you)\s+)?"
    r"(?:(?:search|scan)\s+(?:all|every|each)\s+"
    r"(?:files?|documents?|sources?)(?:[,;]\s*|\s+and(?:\s+then)?\s+))?"
)
_EXHAUSTIVE_QUANTIFIER = (
    r"(?:(?:all|every|each)(?:\s+single)?(?:\s+of(?:\s+the)?)?|"
    r"(?:the\s+)?complete\s+list\s+of)"
)
_REQUEST_PATTERNS = (
    re.compile(
        _COMMAND_PREFIX + r"(?:collect|enumerate|extract|find|get|give|list|return|show)\s+"
        r"(?:me\s+)?(?:a\s+list\s+of\s+)?" + _EXHAUSTIVE_QUANTIFIER + r"\s+"
        r"(?P<target>.+)$",
        re.I,
    ),
    re.compile(
        _COMMAND_PREFIX
        + r"(?:give|get)\s+me\s+(?:a\s+)?list\s+of\s+"
        + _EXHAUSTIVE_QUANTIFIER
        + r"\s+"
        r"(?P<target>.+)$",
        re.I,
    ),
    re.compile(
        _COMMAND_PREFIX + r"(?:what|which)\s+are\s+" + _EXHAUSTIVE_QUANTIFIER + r"\s+"
        r"(?P<target>.+)$",
        re.I,
    ),
    re.compile(
        _COMMAND_PREFIX + r"(?:the\s+)?complete\s+list\s+of\s+(?P<target>.+)$",
        re.I,
    ),
    re.compile(
        _COMMAND_PREFIX + r"extract\s+(?P<target>.+?)\s+"
        r"(?:from|across|in|throughout)\s+(?:all|every|each)\s+"
        r"(?:files?|documents?|sources?|folders?|the\s+workspace)\b.*$",
        re.I,
    ),
)
_SCOPE_SUFFIX = re.compile(
    r"\s+(?:from|in|across|throughout)\s+"
    r"(?:(?:all|every|each|the)\s+)?"
    r"(?:files?|documents?|sources?|folders?|workspace|corpus)\b.*$",
    re.I,
)
_TRAILING_FILLER = re.compile(
    r"\s+(?:(?:that\s+)?(?:you|we)\s+(?:can\s+)?(?:see|find|have)\w*|please)\s*$",
    re.I,
)
_QUOTED_TARGET = re.compile(r"^[\"'“](?P<target>.+?)[\"'”]$")
_WORD = re.compile(r"[^\W_]+|\d+", re.UNICODE)
_LINE = re.compile(r"[^\n]+")
_STRONG_SEPARATOR = re.compile(r"\s*(?P<separator>:|=|\s[\u2013\u2014]\s|\s-\s)\s*")
_COPULA_SEPARATOR = re.compile(r"\s+\b(?:is|are|was|were)\b\s+", re.I)
_CLAUSE_BOUNDARY = re.compile(
    r"[;|]|\band\s+separately\b|(?<=[A-Za-z0-9])\.(?=\s+[A-Z])",
    re.I,
)
_PERIOD_COPULAR_PAIR = re.compile(r"\.\s+[^.;|\n]{1,80}?\s+(?:is|are|was|were)\s+", re.I)
_MONEY_LITERAL = re.compile(
    r"(?:(?P<prefix_sign>[+-]?)\s*(?P<prefix>[$€£]|(?:USD|CAD|EUR|GBP)\b)\s*"
    r"(?P<prefix_amount>[+-]?\d+(?:,\d{3})*(?:\.\d{1,2})?))|"
    r"(?:(?P<suffix_amount>[+-]?\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*"
    r"(?P<suffix>USD|CAD|EUR|GBP)\b)",
    re.I,
)
_PERCENT_LITERAL = re.compile(r"(?<![\w.])(?P<amount>[+-]?\d+(?:\.\d+)?)\s*%")
_ISO_DATE_LITERAL = re.compile(r"\b(?P<date>\d{4}-\d{2}-\d{2})\b")
_MONTH_DATE_LITERAL = re.compile(
    r"\b(?P<date>"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})\b",
    re.I,
)
_EMAIL_LITERAL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_URL_LITERAL = re.compile(r"\bhttps?://[^\s<>]+", re.I)
_IDENTIFIER_LITERAL = re.compile(
    r"\b(?=[A-Z0-9_/-]*[A-Z])(?=[A-Z0-9_/-]*\d)"
    r"[A-Z][A-Z0-9]*(?:[-_/][A-Z0-9]+)+\b",
    re.I,
)
_NUMBER_LITERAL = re.compile(r"(?<![\w.])(?P<amount>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)(?![\w.])")
_MARKDOWN_DIVIDER = re.compile(r"^:?-{3,}:?$")
_GENERIC_TAIL_TOKENS = {"value", "values"}
_CORPUS_TARGET_TOKENS = {
    "corpus",
    "document",
    "file",
    "folder",
    "passage",
    "source",
    "workspace",
}
_MAX_TARGET_CHARS = 60
_MAX_TARGET_TOKENS = 8
_MAX_LABEL_CHARS = 160
_MAX_LABEL_WORDS = 8
_MAX_VALUE_CHARS = 120
_MAX_QUOTE_CHARS = 2_000

ValueKind = Literal["date", "email", "identifier", "money", "number", "percent", "text", "url"]


@dataclass(frozen=True)
class ExhaustiveRequest:
    display_target: str
    normalized_target: str
    target_tokens: tuple[str, ...]


@dataclass(frozen=True)
class ExhaustiveRequestNeedsClarification:
    message: str = "Name one labeled field to extract—for example, “List every renewal date.”"


ExhaustiveRequestDecision = ExhaustiveRequest | ExhaustiveRequestNeedsClarification | None


@dataclass(frozen=True)
class ExhaustiveExtractionResult:
    ambiguous_count: int
    claims: tuple[ClaimRecord, ...]
    occurrence_count: int
    overflowed: bool
    unique_count: int


@dataclass(frozen=True)
class _LineSpan:
    end: int
    start: int
    text: str


@dataclass(frozen=True)
class _TypedValue:
    end: int
    kind: ValueKind
    normalized_value: str
    raw_value: str
    start: int


@dataclass(frozen=True)
class _Candidate:
    kind: ValueKind
    label: str
    normalized_value: str
    quote_end: int
    quote_start: int
    raw_value: str
    context_quote_end: int | None = None
    context_quote_start: int | None = None


@dataclass
class _GroupedValue:
    citations: list[PassageRecord] = field(default_factory=list)
    kind: ValueKind = "text"
    label: str = ""
    normalized_value: str = ""
    raw_value: str = ""
    source_file_ids: set[UUID] = field(default_factory=set)


def parse_exhaustive_request(question: str) -> ExhaustiveRequestDecision:
    """Parse one explicit exhaustive target without relying on a domain vocabulary."""

    normalized_question = " ".join(question.strip().split())
    if not normalized_question:
        return None

    target: str | None = None
    for pattern in _REQUEST_PATTERNS:
        match = pattern.search(normalized_question)
        if match is not None:
            target = match.group("target")
            break
    if target is None:
        return None

    target = target.strip(" \t\n\r?!.,:;")
    target = _TRAILING_FILLER.sub("", target)
    target = _SCOPE_SUFFIX.sub("", target)
    target = target.strip(" \t\n\r?!.,:;")
    quoted = _QUOTED_TARGET.fullmatch(target)
    explicitly_quoted = quoted is not None
    if quoted is not None:
        target = quoted.group("target").strip()
    if not target:
        return ExhaustiveRequestNeedsClarification()
    if not explicitly_quoted and re.search(r"\b(?:and|or)\b", target, re.I) is not None:
        return ExhaustiveRequestNeedsClarification(
            "Ask for one labeled field at a time, or quote a compound field name."
        )

    display_words = [match.group(0) for match in _WORD.finditer(target)]
    while display_words and display_words[0].casefold() in {
        "a",
        "an",
        "distinct",
        "single",
        "the",
        "unique",
    }:
        display_words.pop(0)
    normalized_tokens = [
        unicodedata.normalize("NFKC", word).casefold() for word in display_words
    ]
    if (
        not explicitly_quoted
        and normalized_tokens
        and normalized_tokens[-1] in _GENERIC_TAIL_TOKENS
    ):
        normalized_tokens.pop()
        display_words.pop()
    if (
        not normalized_tokens
        or len(normalized_tokens) > _MAX_TARGET_TOKENS
        or all(
            any(
                tokens_equivalent(token, corpus_token) for corpus_token in _CORPUS_TARGET_TOKENS
            )
            for token in normalized_tokens
        )
    ):
        return ExhaustiveRequestNeedsClarification()

    display_target = " ".join(display_words)
    if not display_target or len(display_target) > _MAX_TARGET_CHARS:
        return ExhaustiveRequestNeedsClarification(
            "Use a shorter label for one field to extract."
        )
    return ExhaustiveRequest(
        display_target=display_target,
        normalized_target=" ".join(normalized_tokens),
        target_tokens=tuple(normalized_tokens),
    )


def extract_values(
    blocks: list[RetrievedBlock],
    *,
    idempotency_key: str,
    request: ExhaustiveRequest,
    run_id: UUID,
) -> ExhaustiveExtractionResult:
    """Scan all supplied blocks for supported explicit structures in stable order."""

    grouped: dict[tuple[str, ValueKind, str], _GroupedValue] = {}
    occurrence_count = 0
    ambiguous_count = 0
    blocks_by_source: dict[UUID, list[RetrievedBlock]] = {}
    for block in blocks:
        blocks_by_source.setdefault(block.source_file_id, []).append(block)
    metadata_sources = {
        source_file_id
        for source_file_id, source_blocks in blocks_by_source.items()
        if any(isinstance(block.structured_metadata, dict) for block in source_blocks)
    }
    candidate_stream: list[tuple[RetrievedBlock, _Candidate]] = []
    for block in blocks:
        candidates, block_ambiguous = _block_candidates(
            block.text,
            ignore_table_lines=block.source_file_id in metadata_sources,
            request=request,
        )
        ambiguous_count += block_ambiguous
        candidate_stream.extend((block, candidate) for candidate in candidates)
    for source_blocks in blocks_by_source.values():
        candidate_stream.extend(_metadata_candidates(source_blocks, request=request))

    for block, candidate in candidate_stream:
        quote = block.text[candidate.quote_start : candidate.quote_end]
        if not quote or len(quote) > _MAX_QUOTE_CHARS or candidate.raw_value not in quote:
            ambiguous_count += 1
            continue
        key = (
            _normalized_label(candidate.label),
            candidate.kind,
            candidate.normalized_value,
        )
        occurrence_count += 1
        group = grouped.get(key)
        if group is None:
            group = _GroupedValue(
                kind=candidate.kind,
                label=candidate.label,
                normalized_value=candidate.normalized_value,
                raw_value=candidate.raw_value,
            )
            grouped[key] = group
        if block.source_file_id in group.source_file_ids or len(group.citations) >= 2:
            continue
        group.source_file_ids.add(block.source_file_id)
        group.citations.append(
            _passage_for_span(
                block,
                end=candidate.quote_end,
                normalized_value=candidate.normalized_value,
                raw_value=candidate.raw_value,
                start=candidate.quote_start,
            )
        )
        if (
            candidate.context_quote_start is not None
            and candidate.context_quote_end is not None
            and len(group.citations) < 2
        ):
            group.citations.append(
                _passage_for_span(
                    block,
                    end=candidate.context_quote_end,
                    normalized_value=None,
                    raw_value=None,
                    start=candidate.context_quote_start,
                )
            )

    unique_count = len(grouped)
    if unique_count > EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT:
        return ExhaustiveExtractionResult(
            ambiguous_count=ambiguous_count,
            claims=(),
            occurrence_count=occurrence_count,
            overflowed=True,
            unique_count=unique_count,
        )

    claim_namespace = uuid5(run_id, idempotency_key)
    claims = tuple(
        ClaimRecord(
            citations=tuple(group.citations),
            claim_id=uuid5(claim_namespace, f"{key[0]}\0{key[1]}\0{key[2]}"),
            relation="fact",
            text=group.label,
            value=group.raw_value,
        )
        for key, group in grouped.items()
        if group.citations
    )
    return ExhaustiveExtractionResult(
        ambiguous_count=ambiguous_count,
        claims=claims,
        occurrence_count=occurrence_count,
        overflowed=False,
        unique_count=unique_count,
    )


def _passage_for_span(
    block: RetrievedBlock,
    *,
    end: int,
    normalized_value: str | None,
    raw_value: str | None,
    start: int,
) -> PassageRecord:
    return PassageRecord(
        block_id=block.block_id,
        drive_file_id=block.drive_file_id,
        end_exclusive_in_block=end,
        exact_quote=block.text[start:end],
        line_start_one_based=(
            block.line_start_one_based + block.text.count("\n", 0, start)
            if block.origin_kind == "text_lines" and block.line_start_one_based is not None
            else None
        ),
        normalized_value=normalized_value,
        origin_kind=block.origin_kind,
        page_index_zero_based=block.page_index_zero_based,
        path=block.path,
        printed_page_label=block.printed_page_label,
        raw_value=raw_value,
        role="support",
        source_name=block.source_name,
        start_in_block=start,
    )


def _block_candidates(
    text: str, *, ignore_table_lines: bool = False, request: ExhaustiveRequest
) -> tuple[list[_Candidate], int]:
    lines = [
        _LineSpan(start=match.start(), end=match.end(), text=match.group(0))
        for match in _LINE.finditer(text)
    ]
    candidates: list[_Candidate] = []
    resolved_lines: set[int] = set()

    table_candidates, table_lines, table_headers = (
        ([], set(), set())
        if ignore_table_lines
        else _column_table_candidates(lines, request=request)
    )
    candidates.extend(table_candidates)
    resolved_lines.update(table_lines)
    vertical_candidates, vertical_lines, vertical_headers = _vertical_table_candidates(
        lines, request=request
    )
    candidates.extend(vertical_candidates)
    resolved_lines.update(vertical_lines)
    table_headers.update(vertical_headers)

    for index, line in enumerate(lines):
        if index in table_headers or (ignore_table_lines and _split_table_row(line.text)):
            continue
        line_candidates = _line_candidates(line, request=request)
        if line_candidates:
            candidates.extend(line_candidates)
            if len(line_candidates) >= _direct_value_structure_count(
                line.text, request=request
            ):
                resolved_lines.add(index)

    for index, line in enumerate(lines[:-1]):
        if (
            index in resolved_lines
            or (ignore_table_lines and _split_table_row(line.text))
            or not _is_target_only(line.text, request=request)
        ):
            continue
        next_index = index + 1
        while next_index < len(lines) and not lines[next_index].text.strip():
            next_index += 1
        if next_index >= len(lines):
            continue
        following = lines[next_index]
        value = _value_from_segment(following.text, allow_opaque=True)
        if value is None:
            value = _explicit_opaque_value(following.text)
        if value is None or _contains_target(following.text, request=request):
            continue
        label = _clean_label(line.text)
        if label is None:
            continue
        candidates.append(
            _Candidate(
                kind=value.kind,
                label=label,
                normalized_value=value.normalized_value,
                quote_end=following.end,
                quote_start=line.start,
                raw_value=value.raw_value,
            )
        )
        resolved_lines.add(index)

    ambiguous_count = sum(
        index not in resolved_lines
        and not (ignore_table_lines and _split_table_row(line.text))
        and _line_has_unresolved_value_structure(line.text, request=request)
        for index, line in enumerate(lines)
    )
    return _deduplicate_candidates(candidates), ambiguous_count


def _explicit_opaque_value(value: str) -> _TypedValue | None:
    start, end = _trimmed_span(value, 0, len(value))
    if end <= start or "\n" in value:
        return None
    raw = value[start:end].rstrip(" \t.,")
    if (
        not raw
        or len(raw) > _MAX_VALUE_CHARS
        or not any(character.isalnum() for character in raw)
    ):
        return None
    normalized = _normalized_opaque(raw)
    return _TypedValue(
        end=start + len(raw),
        kind="text",
        normalized_value=normalized,
        raw_value=raw,
        start=start,
    )


def _vertical_table_candidates(
    lines: list[_LineSpan], *, request: ExhaustiveRequest
) -> tuple[list[_Candidate], set[int], set[int]]:
    candidates: list[_Candidate] = []
    resolved_lines: set[int] = set()
    header_lines: set[int] = set()
    for header_index, header in enumerate(lines[:-2]):
        if (
            not _label_matches_target(header.text, request=request)
            or _typed_values(header.text)
            or _split_table_row(header.text) is not None
        ):
            continue
        pairs: list[tuple[int, _LineSpan, _LineSpan, _TypedValue]] = []
        cursor = header_index + 1
        while cursor + 1 < len(lines):
            label_line = lines[cursor]
            value_line = lines[cursor + 1]
            if (
                _split_table_row(label_line.text) is not None
                or _split_table_row(value_line.text) is not None
            ):
                break
            label = _clean_label(label_line.text)
            value = _value_from_segment(value_line.text, allow_opaque=False)
            if label is None or value is None or _typed_values(label_line.text):
                break
            pairs.append((cursor, label_line, value_line, value))
            cursor += 2
        if len(pairs) < 2:
            continue
        header_label = _clean_label(header.text)
        if header_label is None:
            continue
        header_lines.add(header_index)
        resolved_lines.add(header_index)
        for label_index, label_line, value_line, value in pairs:
            label = _clean_label(f"{label_line.text} — {header_label}")
            if label is None:
                continue
            candidates.append(
                _Candidate(
                    context_quote_end=header.end,
                    context_quote_start=header.start,
                    kind=value.kind,
                    label=label,
                    normalized_value=value.normalized_value,
                    quote_end=value_line.end,
                    quote_start=label_line.start,
                    raw_value=value.raw_value,
                )
            )
            if _contains_target(label_line.text, request=request):
                resolved_lines.add(label_index)
    return candidates, resolved_lines, header_lines


def _metadata_candidates(
    blocks: list[RetrievedBlock], *, request: ExhaustiveRequest
) -> list[tuple[RetrievedBlock, _Candidate]]:
    metadata = next(
        (
            block.structured_metadata
            for block in blocks
            if isinstance(block.structured_metadata, dict)
        ),
        None,
    )
    if not isinstance(metadata, dict):
        return []
    raw_tables = metadata.get("tables")
    if not isinstance(raw_tables, list):
        return []
    candidates: list[tuple[RetrievedBlock, _Candidate]] = []
    for raw_table in raw_tables:
        if not isinstance(raw_table, dict) or raw_table.get("complete") is not True:
            continue
        raw_headers = raw_table.get("headers")
        raw_rows = raw_table.get("rows")
        if not isinstance(raw_headers, list) or not isinstance(raw_rows, list):
            continue
        headers = [str(header) for header in raw_headers]
        rows = [
            [str(value) for value in raw_row.get("values", [])]
            for raw_row in raw_rows
            if isinstance(raw_row, dict) and isinstance(raw_row.get("values"), list)
        ]
        rows = [row for row in rows if len(row) == len(headers)]
        if not rows:
            continue
        table_context = " ".join(
            str(value) for value in (raw_table.get("title"), raw_table.get("section")) if value
        )
        target_columns = [
            index
            for index, header in enumerate(headers)
            if _label_matches_target(header, request=request)
            or _metadata_context_matches_target(table_context, header=header, request=request)
        ]
        if len(target_columns) == 1:
            target_column = target_columns[0]
            for row in rows:
                label = _clean_label(headers[target_column])
                _append_metadata_candidate(
                    candidates,
                    blocks=blocks,
                    label=label,
                    row=row,
                    value_column=target_column,
                )

        for row in rows:
            for label_column, raw_label in enumerate(row[:-1]):
                if not _label_matches_target(raw_label, request=request):
                    continue
                value_columns = _metadata_value_columns(
                    headers,
                    label_column=label_column,
                    row=row,
                )
                for value_column in value_columns:
                    label = _clean_label(f"{raw_label} — {headers[value_column]}")
                    _append_metadata_candidate(
                        candidates,
                        blocks=blocks,
                        label=label,
                        row=row,
                        value_column=value_column,
                    )

        generic_row_headers = {"control", "field", "item", "record", "subjectivity", "term"}
        if (
            len(request.target_tokens) == 1
            and _normalized_label(headers[0]) not in generic_row_headers
        ):
            matching_rows = [
                row for row in rows if _label_matches_target(row[0], request=request)
            ]
            typed_columns = {
                column
                for row in matching_rows
                for column in _metadata_value_columns(
                    headers,
                    label_column=0,
                    row=row,
                )
            }
            if typed_columns and len(rows) >= 2:
                for row in rows:
                    for value_column in sorted(typed_columns):
                        label = _clean_label(f"{row[0]} — {headers[value_column]}")
                        _append_metadata_candidate(
                            candidates,
                            blocks=blocks,
                            label=label,
                            row=row,
                            value_column=value_column,
                            opaque=False,
                        )
    return candidates


def _metadata_value_columns(
    headers: list[str], *, label_column: int, row: list[str]
) -> list[int]:
    generic_labels = {"control", "field", "item", "record", "subjectivity", "term"}
    generic_values = {
        "position",
        "quoted term",
        "quoted value",
        "recorded position",
        "status",
        "value",
    }
    if (
        label_column == 0
        and len(headers) > 1
        and _normalized_label(headers[0]) in generic_labels
        and _normalized_label(headers[1]) in generic_values
    ):
        return [1]
    typed_columns = [
        column
        for column in range(label_column + 1, len(row))
        if (value := _value_from_segment(row[column], allow_opaque=False)) is not None
        and value.kind != "text"
    ]
    return typed_columns or [label_column + 1]


def _metadata_context_matches_target(
    context: str, *, header: str, request: ExhaustiveRequest
) -> bool:
    combined = _normalized_tokens(f"{context} {header}")
    return all(
        any(tokens_equivalent(target, token) for token in combined)
        for target in request.target_tokens
    )


def _append_metadata_candidate(
    candidates: list[tuple[RetrievedBlock, _Candidate]],
    *,
    blocks: list[RetrievedBlock],
    label: str | None,
    opaque: bool = True,
    row: list[str],
    value_column: int,
) -> None:
    if label is None or value_column >= len(row):
        return
    value = _value_from_segment(row[value_column], allow_opaque=opaque)
    if value is None:
        return
    quote = "\t".join(row)
    located = next(
        ((block, start) for block in blocks if (start := block.text.find(quote)) >= 0),
        None,
    )
    if located is None:
        return
    block, start = located
    candidates.append(
        (
            block,
            _Candidate(
                kind=value.kind,
                label=label,
                normalized_value=value.normalized_value,
                quote_end=start + len(quote),
                quote_start=start,
                raw_value=value.raw_value,
            ),
        )
    )


def _line_has_unresolved_value_structure(text: str, *, request: ExhaustiveRequest) -> bool:
    """Distinguish value-shaped ambiguity from an ordinary mention of the target."""

    if not _contains_target(text, request=request):
        return False
    if _split_table_row(text) is not None:
        return True
    if _is_target_only(text, request=request):
        return True
    for clause_start, clause_end in _clause_segments(text):
        clause = text[clause_start:clause_end]
        strong = _STRONG_SEPARATOR.search(clause)
        if strong is not None:
            return True
        copula = _COPULA_SEPARATOR.search(clause)
        if copula is not None and _is_target_only(clause[: copula.start()], request=request):
            return True
    return _direct_value_structure_count(text, request=request) > 0


def _direct_value_structure_count(text: str, *, request: ExhaustiveRequest) -> int:
    direct_values: set[tuple[int, int]] = set()
    for clause_start, clause_end in _clause_segments(text):
        clause = text[clause_start:clause_end]
        values = _typed_values(clause)
        for target_start, target_end in _target_spans(clause, request=request):
            direct = [
                value
                for value in values
                if _target_value_spans_are_direct(
                    clause,
                    target_span=(target_start, target_end),
                    value_span=(value.start, value.end),
                )
            ]
            if any(value.kind != "number" and value.start >= target_end for value in direct):
                direct = [
                    value
                    for value in direct
                    if not (value.kind == "number" and value.end <= target_start)
                ]
            for value in direct:
                trailing = clause[value.end :]
                if re.match(
                    r"\s+(?:higher|lower|increase|decrease|difference)\b",
                    trailing,
                    re.I,
                ):
                    continue
                direct_values.add((clause_start + value.start, clause_start + value.end))
    return len(direct_values)


def _column_table_candidates(
    lines: list[_LineSpan], *, request: ExhaustiveRequest
) -> tuple[list[_Candidate], set[int], set[int]]:
    candidates: list[_Candidate] = []
    header_lines = _ambiguous_undivided_grid_lines(lines, request=request)
    resolved_lines: set[int] = set()
    index = 0
    while index < len(lines) - 1:
        if index in header_lines:
            index += 1
            continue
        header = _split_table_row(lines[index].text)
        if header is None:
            index += 1
            continue
        delimiter, header_cells = header
        indexed_header_tokens = [
            (token, column)
            for column, cell in enumerate(header_cells)
            for token in _normalized_tokens(cell)
        ]
        split_target_columns = {
            indexed_header_tokens[start + len(request.target_tokens) - 1][1]
            for start in range(0, len(indexed_header_tokens) - len(request.target_tokens) + 1)
            if _token_sequences_match(
                tuple(
                    token
                    for token, _ in indexed_header_tokens[
                        start : start + len(request.target_tokens)
                    ]
                ),
                request.target_tokens,
            )
        }
        target_columns = sorted(
            {
                column
                for column, cell in enumerate(header_cells)
                if _label_matches_target(cell, request=request)
            }
            | split_target_columns
        )
        if len(target_columns) != 1:
            index += 1
            continue

        row_index = index + 1
        divider = _split_table_row(lines[row_index].text)
        has_divider = divider is not None and _is_table_divider(divider[1])
        if has_divider:
            header_lines.add(index)
            row_index += 1
        first_data_index = row_index
        accepted = 0
        rejected = False
        table_candidates: list[_Candidate] = []
        target_column = target_columns[0]
        while row_index < len(lines):
            split_row = _split_table_row(lines[row_index].text)
            if split_row is None or split_row[0] != delimiter:
                break
            _, cells = split_row
            if len(cells) != len(header_cells) or _is_table_divider(cells):
                break
            if _label_matches_target(cells[target_column], request=request):
                break
            value = _value_from_segment(cells[target_column], allow_opaque=True)
            if value is not None:
                header_label = header_cells[target_column].strip()
                context = cells[0].strip() if target_column > 0 else ""
                label = _clean_label(f"{context} — {header_label}" if context else header_label)
                if label is not None:
                    quote_includes_header = (
                        lines[row_index].end - lines[index].start <= _MAX_QUOTE_CHARS
                    )
                    table_candidates.append(
                        _Candidate(
                            context_quote_end=(
                                None if quote_includes_header else lines[index].end
                            ),
                            context_quote_start=(
                                None if quote_includes_header else lines[index].start
                            ),
                            kind=value.kind,
                            label=label,
                            normalized_value=value.normalized_value,
                            quote_end=lines[row_index].end,
                            quote_start=(
                                lines[index].start
                                if quote_includes_header
                                else lines[row_index].start
                            ),
                            raw_value=value.raw_value,
                        )
                    )
                    accepted += 1
                else:
                    rejected = True
            else:
                rejected = True
            row_index += 1
        data_rows = row_index - first_data_index
        if accepted and (has_divider or data_rows >= 1):
            candidates.extend(table_candidates)
            header_lines.add(index)
            if not rejected:
                resolved_lines.add(index)
            index = row_index
            continue
        index += 1
    return candidates, resolved_lines, header_lines


def _ambiguous_undivided_grid_lines(
    lines: list[_LineSpan], *, request: ExhaustiveRequest
) -> set[int]:
    """Abstain when an undivided grid could equally be vertical pairs or a table."""

    ambiguous: set[int] = set()
    index = 0
    while index < len(lines):
        first = _split_table_row(lines[index].text)
        if first is None or _is_table_divider(first[1]):
            index += 1
            continue
        delimiter = first[0]
        column_count = len(first[1])
        group: list[tuple[int, list[str]]] = []
        while index < len(lines):
            split = _split_table_row(lines[index].text)
            if (
                split is None
                or split[0] != delimiter
                or len(split[1]) != column_count
                or _is_table_divider(split[1])
            ):
                break
            group.append((index, split[1]))
            index += 1
        target_lines = [
            line_index
            for line_index, cells in group
            if any(_label_matches_target(cell, request=request) for cell in cells)
        ]
        if len(group) >= 2 and len(target_lines) == 1:
            ambiguous.add(target_lines[0])
    return ambiguous


def _line_candidates(line: _LineSpan, *, request: ExhaustiveRequest) -> list[_Candidate]:
    trimmed_start, trimmed_end = _trimmed_span(line.text, 0, len(line.text))
    if trimmed_end <= trimmed_start:
        return []
    text = line.text[trimmed_start:trimmed_end]
    base = line.start + trimmed_start

    table = _split_table_row(text)
    if table is not None:
        _, cells = table
        table_candidates: list[_Candidate] = []
        for column, cell in enumerate(cells[:-1]):
            if not _label_matches_target(cell, request=request):
                continue
            value = _value_from_segment(cells[column + 1], allow_opaque=True)
            label = _clean_label(cell)
            if value is not None and label is not None:
                table_candidates.append(
                    _Candidate(
                        kind=value.kind,
                        label=label,
                        normalized_value=value.normalized_value,
                        quote_end=base + len(text),
                        quote_start=base,
                        raw_value=value.raw_value,
                    )
                )
        if table_candidates:
            return _deduplicate_candidates(table_candidates)

    delimited = _delimited_candidates(text, request=request)
    if delimited:
        return [
            _Candidate(
                kind=candidate.kind,
                label=candidate.label,
                normalized_value=candidate.normalized_value,
                quote_end=base + candidate.quote_end,
                quote_start=base + candidate.quote_start,
                raw_value=candidate.raw_value,
            )
            for candidate in delimited
        ]

    target_spans = _target_spans(text, request=request)
    if not target_spans:
        return []
    candidates: list[_Candidate] = []
    for target_start, target_end in target_spans:
        clause_start, clause_end = _clause_span(text, target_start, target_end)
        clause = text[clause_start:clause_end]
        typed_values = _typed_values(clause)
        target_end_in_clause = target_end - clause_start
        following_values = [
            value for value in typed_values if value.start >= target_end_in_clause
        ]
        if len(following_values) == 1:
            typed_values = following_values
        if len(typed_values) != 1:
            continue
        value = typed_values[0]
        if (
            len(value.raw_value) > _MAX_VALUE_CHARS
            or len(value.normalized_value) > _MAX_VALUE_CHARS
        ):
            continue
        absolute_value_span = (clause_start + value.start, clause_start + value.end)
        if not _target_value_spans_are_direct(
            text,
            target_span=(target_start, target_end),
            value_span=absolute_value_span,
        ):
            continue
        if target_end <= absolute_value_span[0]:
            unconsumed = text[absolute_value_span[1] : clause_end]
        else:
            unconsumed = text[clause_start : absolute_value_span[0]]
        trailing_context = (
            target_end <= absolute_value_span[0]
            and unconsumed.lstrip().startswith((",", "."))
            and not _typed_values(unconsumed)
        )
        if _WORD.search(unconsumed) is not None and not trailing_context:
            continue
        label = _label_around_target(
            text,
            target_span=(target_start, target_end),
            value_span=absolute_value_span,
            clause_span=(clause_start, clause_end),
        )
        if label is None or not _label_matches_target(label, request=request):
            continue
        candidates.append(
            _Candidate(
                kind=value.kind,
                label=label,
                normalized_value=value.normalized_value,
                quote_end=base + clause_end,
                quote_start=base + clause_start,
                raw_value=value.raw_value,
            )
        )
    return _deduplicate_candidates(candidates)


def _delimited_candidates(text: str, *, request: ExhaustiveRequest) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    clauses = _clause_segments(text)
    for clause_start, clause_end in clauses:
        clause = text[clause_start:clause_end]
        strong = _STRONG_SEPARATOR.search(clause)
        separator = strong or _COPULA_SEPARATOR.search(clause)
        if separator is None:
            continue
        left = clause[: separator.start()]
        right = clause[separator.end() :]
        if _label_matches_target(left, request=request):
            value = _value_from_segment(right, allow_opaque=True)
            label = _clean_label(left)
            copula_is_supported = (
                strong is not None
                or value is None
                or value.kind != "text"
                or _is_target_only(left, request=request)
            )
            if value is not None and label is not None and copula_is_supported:
                quote_start, quote_end = _trimmed_span(text, clause_start, clause_end)
                candidates.append(
                    _Candidate(
                        kind=value.kind,
                        label=label,
                        normalized_value=value.normalized_value,
                        quote_end=quote_end,
                        quote_start=quote_start,
                        raw_value=value.raw_value,
                    )
                )
        if (
            strong is not None
            and strong.group("separator").strip() in {"\u2014", "\u2013", "-"}
            and _label_matches_target(right, request=request)
        ):
            value = _value_from_segment(left, allow_opaque=True)
            label = _clean_label(right)
            if value is not None and label is not None:
                quote_start, quote_end = _trimmed_span(text, clause_start, clause_end)
                candidates.append(
                    _Candidate(
                        kind=value.kind,
                        label=label,
                        normalized_value=value.normalized_value,
                        quote_end=quote_end,
                        quote_start=quote_start,
                        raw_value=value.raw_value,
                    )
                )
    return _deduplicate_candidates(candidates)


def _value_from_segment(value: str, *, allow_opaque: bool) -> _TypedValue | None:
    start, end = _trimmed_span(value, 0, len(value))
    if end <= start:
        return None
    segment = value[start:end]
    typed_values = _typed_values(segment)
    if (
        len(typed_values) == 1
        and typed_values[0].start == 0
        and segment[typed_values[0].end :].lstrip().startswith((",", "."))
    ):
        typed = typed_values[0]
        return _TypedValue(
            end=start + typed.end,
            kind=typed.kind,
            normalized_value=typed.normalized_value,
            raw_value=typed.raw_value,
            start=start + typed.start,
        )
    if (
        len(typed_values) == 1
        and not segment[: typed_values[0].start].strip(" ~≈")
        and not segment[typed_values[0].end :].strip(" \t.;,")
    ):
        typed = typed_values[0]
        if (
            len(typed.raw_value) > _MAX_VALUE_CHARS
            or len(typed.normalized_value) > _MAX_VALUE_CHARS
        ):
            return None
        return _TypedValue(
            end=start + typed.end,
            kind=typed.kind,
            normalized_value=typed.normalized_value,
            raw_value=typed.raw_value,
            start=start + typed.start,
        )
    if not allow_opaque or "\n" in segment:
        return None
    opaque = segment.rstrip(" \t.;,")
    if (
        not opaque
        or len(opaque) > _MAX_VALUE_CHARS
        or re.search(r"[;|]", opaque) is not None
        or _STRONG_SEPARATOR.search(opaque) is not None
        or _PERIOD_COPULAR_PAIR.search(opaque) is not None
    ):
        return None
    normalized = _normalized_opaque(opaque)
    if not normalized or not any(character.isalnum() for character in opaque):
        return None
    return _TypedValue(
        end=start + len(opaque),
        kind="text",
        normalized_value=normalized,
        raw_value=opaque,
        start=start,
    )


def _typed_values(text: str) -> list[_TypedValue]:
    candidates: list[tuple[int, int, _TypedValue]] = []
    for match in _MONEY_LITERAL.finditer(text):
        amount_text = match.group("prefix_amount") or match.group("suffix_amount")
        currency = match.group("prefix") or match.group("suffix")
        if amount_text is None or currency is None:
            continue
        prefix_sign = match.group("prefix_sign") or ""
        if prefix_sign and not amount_text.startswith(("+", "-")):
            amount_text = f"{prefix_sign}{amount_text}"
        amount = _decimal(amount_text)
        if amount is None:
            continue
        candidates.append(
            (
                0,
                -(match.end() - match.start()),
                _TypedValue(
                    end=match.end(),
                    kind="money",
                    normalized_value=f"{currency.upper()} {_canonical_decimal(amount)}",
                    raw_value=match.group(0).strip(),
                    start=match.start(),
                ),
            )
        )
    for match in _PERCENT_LITERAL.finditer(text):
        amount = _decimal(match.group("amount"))
        if amount is None:
            continue
        candidates.append(
            (
                1,
                -(match.end() - match.start()),
                _TypedValue(
                    end=match.end(),
                    kind="percent",
                    normalized_value=f"{_canonical_decimal(amount)}%",
                    raw_value=match.group(0).strip(),
                    start=match.start(),
                ),
            )
        )
    for priority, pattern in ((2, _ISO_DATE_LITERAL), (3, _MONTH_DATE_LITERAL)):
        for match in pattern.finditer(text):
            parsed = _parse_date(match.group("date"))
            if parsed is None:
                continue
            candidates.append(
                (
                    priority,
                    -(match.end() - match.start()),
                    _TypedValue(
                        end=match.end(),
                        kind="date",
                        normalized_value=parsed.isoformat(),
                        raw_value=match.group(0).strip(),
                        start=match.start(),
                    ),
                )
            )
    for priority, kind, pattern in (
        (4, "email", _EMAIL_LITERAL),
        (5, "url", _URL_LITERAL),
        (6, "identifier", _IDENTIFIER_LITERAL),
    ):
        for match in pattern.finditer(text):
            raw = match.group(0).rstrip(".,")
            candidates.append(
                (
                    priority,
                    -(match.end() - match.start()),
                    _TypedValue(
                        end=match.start() + len(raw),
                        kind=kind,  # type: ignore[arg-type]
                        normalized_value=_normalized_opaque(raw),
                        raw_value=raw,
                        start=match.start(),
                    ),
                )
            )
    for match in _NUMBER_LITERAL.finditer(text):
        amount = _decimal(match.group("amount"))
        if amount is None:
            continue
        normalized = _canonical_decimal(amount)
        candidates.append(
            (
                7,
                -(match.end() - match.start()),
                _TypedValue(
                    end=match.end(),
                    kind="number",
                    normalized_value=normalized,
                    raw_value=match.group(0).strip(),
                    start=match.start(),
                ),
            )
        )

    accepted: list[_TypedValue] = []
    for _, _, candidate in sorted(
        candidates, key=lambda item: (item[2].start, item[0], item[1])
    ):
        if any(
            candidate.start < existing.end and existing.start < candidate.end
            for existing in accepted
        ):
            continue
        accepted.append(candidate)
    return sorted(accepted, key=lambda candidate: (candidate.start, candidate.end))


def _target_spans(text: str, *, request: ExhaustiveRequest) -> list[tuple[int, int]]:
    words = _normalized_word_spans(text)
    width = len(request.target_tokens)
    return [
        (words[index][1], words[index + width - 1][2])
        for index in range(0, len(words) - width + 1)
        if _token_sequences_match(
            tuple(word[0] for word in words[index : index + width]),
            request.target_tokens,
        )
    ]


def _contains_target(text: str, *, request: ExhaustiveRequest) -> bool:
    return bool(_target_spans(text, request=request))


def _label_matches_target(label: str, *, request: ExhaustiveRequest) -> bool:
    label_tokens = _normalized_tokens(label)
    width = len(request.target_tokens)
    return len(label_tokens) >= width and _token_sequences_match(
        label_tokens[-width:], request.target_tokens
    )


def _is_target_only(text: str, *, request: ExhaustiveRequest) -> bool:
    return _token_sequences_match(_normalized_tokens(text), request.target_tokens)


def _label_around_target(
    text: str,
    *,
    clause_span: tuple[int, int],
    target_span: tuple[int, int],
    value_span: tuple[int, int],
) -> str | None:
    clause_start, clause_end = clause_span
    if target_span[1] <= value_span[0]:
        label_start, label_end = clause_start, target_span[1]
    else:
        label_start, label_end = target_span[0], clause_end
    label_text = text[label_start:label_end].strip(" \t:-=,.;")
    words = list(_WORD.finditer(label_text))
    if len(words) > _MAX_LABEL_WORDS:
        target_offset = target_span[0] - label_start
        target_word = next(
            (
                index
                for index, word in enumerate(words)
                if word.start() <= target_offset < word.end()
            ),
            len(words) - 1,
        )
        first = max(0, target_word - 5)
        last = min(len(words), first + _MAX_LABEL_WORDS)
        first = max(0, last - _MAX_LABEL_WORDS)
        label_text = " ".join(word.group(0) for word in words[first:last])
    return _clean_label(label_text)


def _target_value_spans_are_direct(
    text: str,
    *,
    target_span: tuple[int, int],
    value_span: tuple[int, int],
) -> bool:
    if target_span[1] <= value_span[0]:
        gap = text[target_span[1] : value_span[0]]
    elif value_span[1] <= target_span[0]:
        gap = text[value_span[1] : target_span[0]]
    else:
        return False
    if len(gap) > 16:
        return False
    words = tuple(match.group(0).casefold() for match in _WORD.finditer(gap))
    return not words or set(words) <= {"are", "is", "of", "was", "were"}


def _clean_label(label: str) -> str | None:
    cleaned = " ".join(label.strip(" \t:-=,.;|").split())
    cleaned = re.sub(
        r"^(?:(?:the\s+)?(?:document|file|source)\s+)?"
        r"(?:lists?|reports?|shows?|states?|supports?)\s+",
        "",
        cleaned,
        flags=re.I,
    )
    if not cleaned or len(cleaned) > _MAX_LABEL_CHARS:
        return None
    return cleaned


def _normalized_label(label: str) -> str:
    return " ".join(_normalized_tokens(label))


def _normalized_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        unicodedata.normalize("NFKC", match.group(0)).casefold()
        for match in _WORD.finditer(text)
    )


def _normalized_word_spans(text: str) -> list[tuple[str, int, int]]:
    return [
        (
            unicodedata.normalize("NFKC", match.group(0)).casefold(),
            match.start(),
            match.end(),
        )
        for match in _WORD.finditer(text)
    ]


def _token_sequences_match(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return len(left) == len(right) and all(
        tokens_equivalent(left_token, right_token)
        for left_token, right_token in zip(left, right, strict=True)
    )


def _split_table_row(text: str) -> tuple[str, list[str]] | None:
    delimiter = "|" if "|" in text else "\t" if "\t" in text else None
    if delimiter is None:
        return None
    cells = [cell.strip() for cell in text.strip().strip("|").split(delimiter)]
    if len(cells) < 2:
        return None
    return delimiter, cells


def _is_table_divider(cells: list[str]) -> bool:
    return bool(cells) and all(_MARKDOWN_DIVIDER.fullmatch(cell) is not None for cell in cells)


def _clause_segments(text: str) -> list[tuple[int, int]]:
    boundaries = _clause_boundaries(text)
    starts = [0, *(boundary.end() for boundary in boundaries)]
    ends = [*(boundary.start() for boundary in boundaries), len(text)]
    return [
        _trimmed_span(text, start, end)
        for start, end in zip(starts, ends, strict=True)
        if _trimmed_span(text, start, end)[1] > _trimmed_span(text, start, end)[0]
    ]


def _clause_span(text: str, start: int, end: int) -> tuple[int, int]:
    clause_start = 0
    clause_end = len(text)
    for boundary in _clause_boundaries(text):
        if boundary.end() <= start:
            clause_start = boundary.end()
        elif boundary.start() >= end:
            clause_end = boundary.start()
            break
    return _trimmed_span(text, clause_start, clause_end)


def _clause_boundaries(text: str) -> list[re.Match[str]]:
    return list(_CLAUSE_BOUNDARY.finditer(text))


def _deduplicate_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    seen: set[tuple[int, int, str, ValueKind, str]] = set()
    unique: list[_Candidate] = []
    for candidate in candidates:
        key = (
            candidate.quote_start,
            candidate.quote_end,
            _normalized_label(candidate.label),
            candidate.kind,
            candidate.normalized_value,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def _canonical_decimal(value: Decimal) -> str:
    canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return canonical or "0"


def _parse_date(value: str) -> date | None:
    cleaned = re.sub(r"(\d{1,2})(?:st|nd|rd|th)", r"\1", value)
    cleaned = cleaned.replace(".", "")
    for date_format in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    return None


def _normalized_opaque(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())
