"""Complete, schema-neutral execution over tabular evidence.

This module intentionally operates on every ready source block supplied by the
repository.  It never receives a top-k retrieval sample.  The executor keeps
typed values for computation and exact row spans for audit/citation lineage.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID, uuid5

from extent_api.database.query_repository import ClaimRecord, PassageRecord, RetrievedBlock
from extent_api.query_models import EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT
from extent_api.services.query_planning import QueryPlan, normalized_query_tokens
from extent_api.token_forms import tokens_equivalent

STRUCTURED_ANALYSIS_POLICY_VERSION = "structured-analysis-policy-v1"

ValueKind = Literal["boolean", "date", "identifier", "null", "number", "text"]
AnalysisStatus = Literal["complete", "incomplete", "not_applicable", "unsupported"]

_NULLS = {"", "-", "n/a", "na", "none", "null", "unknown"}
_TRUE = {"true", "yes", "y"}
_FALSE = {"false", "no", "n"}
_NUMBER = re.compile(
    r"^\s*(?P<prefix>[$€£])?\s*(?P<number>[+-]?(?:\d+(?:,\d{3})*|\d*)(?:\.\d+)?)"
    r"\s*(?P<suffix>%|USD|CAD|EUR|GBP)?\s*$",
    re.I,
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_NORMALIZED_ISO_DATE = re.compile(r"^\d{4}\s+\d{1,2}\s+\d{1,2}$")
_NORMALIZED_SLASH_DATE = re.compile(r"^\d{1,2}\s+\d{1,2}\s+\d{4}$")
_IDENTIFIER = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9_.:/-]*$")
_MARKDOWN_DIVIDER = re.compile(r"^:?-{3,}:?$")
_QUESTION_STOPWORDS = {
    "a",
    "all",
    "and",
    "are",
    "by",
    "count",
    "does",
    "each",
    "every",
    "for",
    "from",
    "group",
    "have",
    "how",
    "in",
    "is",
    "list",
    "many",
    "of",
    "on",
    "or",
    "record",
    "records",
    "show",
    "summarize",
    "summary",
    "table",
    "the",
    "total",
    "what",
    "which",
    "with",
}
_AGGREGATE_WORDS = {
    "aggregate",
    "average",
    "avg",
    "count",
    "maximum",
    "max",
    "minimum",
    "min",
    "sum",
    "total",
}


@dataclass(frozen=True)
class TypedValue:
    kind: ValueKind
    raw: str
    value: bool | date | Decimal | str | None
    unit: str | None = None

    @property
    def is_null(self) -> bool:
        return self.kind == "null"


@dataclass(frozen=True)
class StructuredRow:
    citation: PassageRecord
    ordinal: int
    table_id: str
    values: tuple[TypedValue, ...]


@dataclass(frozen=True)
class StructuredTable:
    headers: tuple[str, ...]
    header_citation: PassageRecord
    rows: tuple[StructuredRow, ...]
    section: str | None
    source_file_id: UUID
    source_name: str
    table_id: str
    title: str | None
    malformed_rows: int = 0


@dataclass(frozen=True)
class RowAudit:
    operation: str
    source_name: str
    table_id: str
    row_ordinal: int
    citation: PassageRecord


@dataclass(frozen=True)
class ReconciliationAudit:
    duplicate_key_count: int = 0
    left_rows: int = 0
    matched_keys: int = 0
    right_rows: int = 0
    unmatched_left_keys: tuple[str, ...] = ()
    unmatched_right_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructuredAnalysisResult:
    audits: tuple[RowAudit, ...]
    claims: tuple[ClaimRecord, ...]
    examined_rows: int
    malformed_rows: int
    matched_rows: int
    message: str
    reconciliation: ReconciliationAudit
    status: AnalysisStatus
    tables_examined: int

    @property
    def applicable(self) -> bool:
        return self.status != "not_applicable"

    @property
    def complete(self) -> bool:
        return self.status == "complete"


@dataclass(frozen=True)
class _SourceLine:
    block: RetrievedBlock
    end: int
    line_number: int | None
    start: int
    text: str


@dataclass(frozen=True)
class _Condition:
    column: int
    operator: Literal["eq", "ge", "gt", "is_null", "le", "lt", "ne", "not_null"]
    other_column: int | None = None
    value: TypedValue | None = None


def analyze_structured_question(
    blocks: list[RetrievedBlock],
    *,
    idempotency_key: str,
    plan: QueryPlan,
    question: str,
    run_id: UUID,
) -> StructuredAnalysisResult:
    """Execute one question over complete tables reconstructed from ``blocks``."""

    tables = extract_structured_tables(blocks)
    if not tables:
        return _result(
            message="No supported structured table was found in the readable evidence.",
            status="not_applicable",
        )

    selected = _select_tables(tables, question=question, join="join" in plan.intents)
    if not selected:
        return _result(
            message="Structured tables were found, but none matched the requested fields.",
            status="unsupported",
            tables_examined=len(tables),
        )
    duplicate_headers = [table for table in selected if _has_duplicate_headers(table)]
    if duplicate_headers:
        return _analysis_failure(
            selected,
            examined=sum(len(table.rows) for table in selected),
            malformed=sum(table.malformed_rows for table in selected),
            message=(
                "Analysis capability failed: a relevant table has duplicate normalized "
                "column headers, so field references are ambiguous."
            ),
        )
    if "join" in plan.intents:
        return _reconcile(
            selected,
            idempotency_key=idempotency_key,
            question=question,
            run_id=run_id,
            universal="completeness" in plan.intents,
        )
    if "completeness" in plan.intents:
        return _universal(
            selected,
            idempotency_key=idempotency_key,
            question=question,
            run_id=run_id,
        )
    if "aggregate" in plan.intents:
        return _aggregate(
            selected,
            grouped="group" in plan.intents,
            idempotency_key=idempotency_key,
            question=question,
            run_id=run_id,
        )
    return _list_or_summarize(
        selected,
        exception_only="exceptions" in plan.intents,
        idempotency_key=idempotency_key,
        question=question,
        run_id=run_id,
    )


def extract_structured_tables(blocks: list[RetrievedBlock]) -> tuple[StructuredTable, ...]:
    """Reconstruct CSV, DOCX, and delimited document tables with row lineage."""

    by_source: dict[UUID, list[RetrievedBlock]] = {}
    for block in blocks:
        by_source.setdefault(block.source_file_id, []).append(block)

    tables: list[StructuredTable] = []
    for source_blocks in by_source.values():
        source_tables = _tables_from_metadata(source_blocks)
        if source_tables:
            tables.extend(source_tables)
            continue
        lines = _source_lines(source_blocks)
        if not lines:
            continue
        pipeline = next(
            (
                str(value)
                for block in source_blocks
                if (value := getattr(block, "pipeline_version", None)) is not None
            ),
            None,
        )
        is_csv = (
            pipeline in {"csv-record-v1", "csv-record-v2"}
            or PurePosixPath(source_blocks[0].source_name).suffix.casefold() == ".csv"
        )
        if is_csv:
            table = _delimited_table(
                lines,
                delimiter="\t",
                section=None,
                table_index=1,
                title=None,
            )
            if table is not None:
                tables.append(table)
            continue
        tables.extend(_document_tables(lines))
    return tuple(tables)


def parse_typed_value(raw: str) -> TypedValue:
    """Infer conservative scalar types while preserving identifiers and nulls."""

    value = " ".join(raw.replace("\x00", "").split())
    key = value.casefold()
    if key in _NULLS:
        return TypedValue(kind="null", raw=value, value=None)
    if key in _TRUE:
        return TypedValue(kind="boolean", raw=value, value=True)
    if key in _FALSE:
        return TypedValue(kind="boolean", raw=value, value=False)
    parsed_date = _parse_date(value)
    if parsed_date is not None:
        return TypedValue(kind="date", raw=value, value=parsed_date)
    if _IDENTIFIER.fullmatch(value) is not None or (
        len(value) > 1 and value[0] == "0" and value.isdigit()
    ):
        return TypedValue(kind="identifier", raw=value, value=value)
    number = _NUMBER.fullmatch(value)
    if number is not None and number.group("number") not in {"", "+", "-", "."}:
        try:
            decimal = Decimal(number.group("number").replace(",", ""))
        except InvalidOperation:
            pass
        else:
            unit = _unit(number.group("prefix"), number.group("suffix"))
            return TypedValue(kind="number", raw=value, unit=unit, value=decimal)
    return TypedValue(kind="text", raw=value, value=value)


def _tables_from_metadata(blocks: list[RetrievedBlock]) -> list[StructuredTable]:
    # New ingestion attaches complete normalized table metadata to the first
    # source block. Text reconstruction remains a compatibility path for old runs.
    seen: set[str] = set()
    tables: list[StructuredTable] = []
    for block in blocks:
        metadata = getattr(block, "structured_metadata", None)
        if not isinstance(metadata, dict):
            continue
        pipeline_version = getattr(block, "pipeline_version", None)
        schema_version = metadata.get("schemaVersion")
        if pipeline_version in {"csv-record-v2", "docx-body-v2"} and (
            schema_version != "structured-table-artifact-v2"
            or metadata.get("parserVersion") != pipeline_version
            or metadata.get("sourceVersion") != getattr(block, "source_content_hash", None)
        ):
            # A v2 parser artifact is accepted only when its parser and immutable
            # source identities agree with the block that carries it.
            continue
        raw_tables = metadata.get("tables")
        if not isinstance(raw_tables, list):
            continue
        for raw_table in raw_tables:
            if not isinstance(raw_table, dict):
                continue
            table_id = f"{block.source_file_id}:{raw_table.get('tableId', '')}"
            if not table_id or table_id in seen:
                continue
            if raw_table.get("complete") is not True:
                continue
            parsed = _metadata_table(blocks, raw_table, table_id=table_id)
            if parsed is not None:
                seen.add(table_id)
                tables.append(parsed)
    return tables


def _metadata_table(
    blocks: list[RetrievedBlock],
    raw_table: dict[object, object],
    *,
    table_id: str,
) -> StructuredTable | None:
    headers = raw_table.get("headers")
    raw_rows = raw_table.get("rows")
    if not isinstance(headers, list) or not isinstance(raw_rows, list) or len(headers) < 2:
        return None
    header_values = tuple(str(item) for item in headers)
    header_quote = "\t".join(header_values)
    source_lines = _source_lines(blocks)
    raw_line_starts: list[int] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        line_start = raw_row.get("lineStartOneBased")
        if isinstance(line_start, int):
            raw_line_starts.append(line_start)
    header_line = min(raw_line_starts) - 1 if raw_line_starts else None
    header_citation = _line_citation(
        source_lines,
        exact_quote=header_quote,
        line_start_one_based=header_line,
    )
    if header_citation is None:
        return None
    rows: list[StructuredRow] = []
    unresolved_rows = 0
    for fallback_ordinal, raw_row in enumerate(raw_rows, start=1):
        if not isinstance(raw_row, dict) or not isinstance(raw_row.get("values"), list):
            unresolved_rows += 1
            continue
        values = tuple(str(item) for item in raw_row["values"])  # type: ignore[index]
        if len(values) != len(header_values):
            unresolved_rows += 1
            continue
        quote = "\t".join(values)
        line_start = raw_row.get("lineStartOneBased")
        citation = _line_citation(
            source_lines,
            exact_quote=quote,
            line_start_one_based=line_start if isinstance(line_start, int) else None,
        )
        if citation is None:
            unresolved_rows += 1
            continue
        ordinal = raw_row.get("ordinal")
        rows.append(
            StructuredRow(
                citation=citation,
                ordinal=ordinal if isinstance(ordinal, int) else fallback_ordinal,
                table_id=table_id,
                values=tuple(parse_typed_value(item) for item in values),
            )
        )
    block = blocks[0]
    malformed_rows = raw_table.get("malformedRows")
    malformed_count = (
        malformed_rows if isinstance(malformed_rows, int) else 0
    ) + unresolved_rows
    if not rows and malformed_count == 0:
        return None
    return StructuredTable(
        headers=header_values,
        header_citation=header_citation,
        malformed_rows=malformed_count,
        rows=tuple(rows),
        section=_optional_text(raw_table.get("section")),
        source_file_id=block.source_file_id,
        source_name=block.source_name,
        table_id=table_id,
        title=_optional_text(raw_table.get("title")),
    )


def _line_citation(
    lines: list[_SourceLine],
    *,
    exact_quote: str,
    line_start_one_based: int | None,
) -> PassageRecord | None:
    matches = [
        line
        for line in lines
        if line.text == exact_quote
        and (line_start_one_based is None or line.line_number == line_start_one_based)
    ]
    if len(matches) != 1:
        return None
    line = matches[0]
    return _passage(line.block, line.start, line.end)


def _source_lines(blocks: list[RetrievedBlock]) -> list[_SourceLine]:
    ordered = sorted(
        enumerate(blocks),
        key=lambda item: (
            item[1].line_start_one_based or 0,
            item[0],
            str(item[1].block_id),
        ),
    )
    lines: list[_SourceLine] = []
    for _, block in ordered:
        line_number = block.line_start_one_based
        cursor = 0
        for raw in block.text.splitlines(keepends=True):
            text = raw.rstrip("\r\n")
            if text.strip():
                leading = len(text) - len(text.lstrip(" "))
                end = len(text.rstrip(" "))
                lines.append(
                    _SourceLine(
                        block=block,
                        end=cursor + end,
                        line_number=line_number,
                        start=cursor + leading,
                        text=text[leading:end],
                    )
                )
            if line_number is not None:
                line_number += raw.count("\n") or 1
            cursor += len(raw)
        if block.text and not block.text.endswith(("\n", "\r")) and not block.text.splitlines():
            lines.append(
                _SourceLine(
                    block=block,
                    end=len(block.text),
                    line_number=block.line_start_one_based,
                    start=0,
                    text=block.text,
                )
            )
    return lines


def _document_tables(lines: list[_SourceLine]) -> list[StructuredTable]:
    tables: list[StructuredTable] = []
    index = 0
    table_index = 1
    while index < len(lines):
        delimiter = _delimiter(lines[index].text)
        if delimiter is None:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and _delimiter(lines[end].text) == delimiter:
            end += 1
        run = lines[index:end]
        title = (
            lines[index - 1].text
            if index > 0 and _delimiter(lines[index - 1].text) is None
            else None
        )
        table = _delimited_table(
            run,
            delimiter=delimiter,
            section=title,
            table_index=table_index,
            title=title,
        )
        if table is not None:
            tables.append(table)
            table_index += 1
        index = end
    return tables


def _delimited_table(
    lines: list[_SourceLine],
    *,
    delimiter: str,
    section: str | None,
    table_index: int,
    title: str | None,
) -> StructuredTable | None:
    if len(lines) < 2:
        return None
    header_cells = _cells(lines[0].text, delimiter)
    if len(header_cells) < 2 or any(not cell for cell in header_cells):
        return None
    data_start = 1
    if len(lines) > 1:
        divider = _cells(lines[1].text, delimiter)
        if len(divider) == len(header_cells) and all(
            _MARKDOWN_DIVIDER.fullmatch(cell) is not None for cell in divider
        ):
            data_start = 2
    if len(lines) <= data_start:
        return None
    source = lines[0].block
    table_id = f"{source.source_file_id}:{table_index}"
    malformed = 0
    rows: list[StructuredRow] = []
    for ordinal, line in enumerate(lines[data_start:], start=1):
        cells = _cells(line.text, delimiter)
        if len(cells) != len(header_cells):
            malformed += 1
            continue
        rows.append(
            StructuredRow(
                citation=_passage(line.block, line.start, line.end),
                ordinal=ordinal,
                table_id=table_id,
                values=tuple(parse_typed_value(cell) for cell in cells),
            )
        )
    if not rows and malformed == 0:
        return None
    return StructuredTable(
        headers=tuple(header_cells),
        header_citation=_passage(lines[0].block, lines[0].start, lines[0].end),
        malformed_rows=malformed,
        rows=tuple(rows),
        section=section,
        source_file_id=source.source_file_id,
        source_name=source.source_name,
        table_id=table_id,
        title=title,
    )


def _select_tables(
    tables: tuple[StructuredTable, ...], *, question: str, join: bool
) -> tuple[StructuredTable, ...]:
    scored = [(table, _table_score(table, question)) for table in tables]
    positive = [(table, score) for table, score in scored if score > 0]
    if join:
        ordered = sorted(scored, key=lambda item: item[1], reverse=True)
        return tuple(table for table, _ in ordered[: max(2, min(len(ordered), 4))])
    if not positive:
        return tables if len(tables) == 1 else ()
    best = max(score for _, score in positive)
    anchor = next(table for table, score in positive if score == best)
    selected = [anchor]
    # Rows can only share positional execution when their schemas have the same
    # normalized order.  Set equality allowed reordered/ragged rows to be indexed
    # with the first table's column positions.
    header_key = tuple(_normalized_header(header) for header in selected[0].headers)
    selected.extend(
        table
        for table, score in positive
        if table is not anchor
        and score >= best - 1
        and tuple(_normalized_header(header) for header in table.headers) == header_key
    )
    return tuple(selected)


def _table_score(table: StructuredTable, question: str) -> int:
    score = sum(max(0, _column_score(header, question)) for header in table.headers)
    question_key = _normalized_text(question)
    for label in (table.title, table.section, PurePosixPath(table.source_name).stem):
        if label and _normalized_text(label) in question_key:
            score += 4
    return score


def _mentioned_columns(table: StructuredTable, question: str) -> list[int]:
    scored = [
        (_column_score(header, question), index) for index, header in enumerate(table.headers)
    ]
    return [index for score, index in sorted(scored, reverse=True) if score > 0]


def _column_score(header: str, question: str) -> int:
    header_key = _normalized_text(header)
    question_key = _normalized_text(question)
    if not header_key:
        return 0
    if re.search(rf"\b{re.escape(header_key)}\b", question_key):
        return 8 + len(header_key.split())
    header_tokens = normalized_query_tokens(header_key)
    question_tokens = normalized_query_tokens(question_key)
    meaningful = [token for token in header_tokens if token not in _QUESTION_STOPWORDS]
    if not meaningful:
        return 0
    matched = sum(
        any(tokens_equivalent(token, candidate) for candidate in question_tokens)
        for token in meaningful
    )
    return matched if matched == len(meaningful) else 0


def _conditions(table: StructuredTable, question: str) -> tuple[_Condition, ...]:
    normalized = _normalized_text(_expand_symbolic_comparators(question))
    conditions: list[_Condition] = []
    for column, header in enumerate(table.headers):
        header_key = _normalized_text(header)
        match = re.search(rf"\b{re.escape(header_key)}\b", normalized)
        if match is None:
            continue
        tail = normalized[match.end() : match.end() + 120]
        prefix = normalized[max(0, match.start() - 60) : match.start()]
        if re.search(r"(?:missing|without|(?:do|does|did)\s+not\s+have|no)\s+$", prefix):
            conditions.append(_Condition(column=column, operator="is_null"))
            continue
        if re.match(
            r"\s+(?:is\s+)?(?:missing|null|blank|empty|not\s+(?:set|provided))\b", tail
        ):
            conditions.append(_Condition(column=column, operator="is_null"))
            continue
        if re.match(
            r"\s+(?:is\s+)?(?:present|provided|not\s+(?:missing|null|blank|empty))\b", tail
        ):
            conditions.append(_Condition(column=column, operator="not_null"))
            continue
        tail = re.sub(
            r"^\s+is\s+(?=(?:above|after|at\s+(?:least|most)|before|below|"
            r"greater|less|more|over|under)\b)",
            " ",
            tail,
        )
        comparator = re.match(
            r"\s*(?P<operator>>=|<=|!=|<>|=|>|<|is\s+not|not\s+equal\s+to|"
            r"greater\s+than|more\s+than|over|above|at\s+least|less\s+than|"
            r"under|below|at\s+most|before|after|equals?|is|are)\s+"
            r"(?P<value>[^?,;]+?)(?=\s+(?:and|by|grouped|per|where|with)\b|$)",
            tail,
        )
        if comparator is None:
            continue
        raw_value = comparator.group("value").strip(" '\"")
        if not raw_value:
            continue
        referenced_columns = [
            index
            for index, candidate in enumerate(table.headers)
            if index != column and _normalized_text(candidate) == _normalized_text(raw_value)
        ]
        conditions.append(
            _Condition(
                column=column,
                operator=_operator(comparator.group("operator")),
                other_column=(referenced_columns[0] if len(referenced_columns) == 1 else None),
                value=(None if len(referenced_columns) == 1 else parse_typed_value(raw_value)),
            )
        )
    if conditions:
        return tuple(conditions)

    # Entity values often scope summaries without a "where" clause.  Matching
    # exact cell values is schema-neutral and does not assume an ID column name.
    header_spans = [
        match.span()
        for header in table.headers
        if (match := re.search(rf"\b{re.escape(_normalized_text(header))}\b", normalized))
        is not None
    ]
    matches: list[_Condition] = []
    for column in range(len(table.headers)):
        distinct = {
            _normalized_text(row.values[column].raw): row.values[column]
            for row in table.rows
            if not row.values[column].is_null
        }
        for raw_key, typed in distinct.items():
            value_matches = list(re.finditer(rf"(?<!\w){re.escape(raw_key)}(?!\w)", normalized))
            if len(raw_key) >= 2 and any(
                not any(
                    header_start <= value_match.start() and value_match.end() <= header_end
                    for header_start, header_end in header_spans
                )
                for value_match in value_matches
            ):
                matches.append(_Condition(column=column, operator="eq", value=typed))
    return tuple(matches[:1])


def _expand_symbolic_comparators(value: str) -> str:
    """Preserve symbolic comparisons through punctuation-free normalization."""

    replacements = (
        (">=", " at least "),
        ("<=", " at most "),
        ("!=", " not equal to "),
        ("<>", " not equal to "),
        (">", " greater than "),
        ("<", " less than "),
        ("=", " equals "),
    )
    expanded = unicodedata.normalize("NFKC", value)
    for symbol, words in replacements:
        expanded = expanded.replace(symbol, words)
    return expanded


def _row_matches(row: StructuredRow, conditions: tuple[_Condition, ...]) -> bool:
    return all(_condition_matches(row, condition) for condition in conditions)


def _condition_matches(row: StructuredRow, condition: _Condition) -> bool:
    if condition.column >= len(row.values):
        return False
    value = row.values[condition.column]
    if condition.operator == "is_null":
        return value.is_null
    if condition.operator == "not_null":
        return not value.is_null
    comparison_value = condition.value
    if condition.other_column is not None:
        if condition.other_column >= len(row.values):
            return False
        comparison_value = row.values[condition.other_column]
    if comparison_value is None or value.is_null or comparison_value.is_null:
        return False
    comparison = _compare(value, comparison_value)
    if comparison is None:
        return False
    return {
        "eq": comparison == 0,
        "ne": comparison != 0,
        "gt": comparison > 0,
        "ge": comparison >= 0,
        "lt": comparison < 0,
        "le": comparison <= 0,
    }[condition.operator]


def _compare(left: TypedValue, right: TypedValue) -> int | None:
    if left.kind == right.kind == "number":
        if left.unit != right.unit and right.unit is not None:
            return None
        assert isinstance(left.value, Decimal)
        assert isinstance(right.value, Decimal)
        return (left.value > right.value) - (left.value < right.value)
    if left.kind == right.kind == "date":
        assert isinstance(left.value, date)
        assert isinstance(right.value, date)
        return (left.value > right.value) - (left.value < right.value)
    if {left.kind, right.kind} <= {"identifier", "text"}:
        left_key = _normalized_text(str(left.value))
        right_key = _normalized_text(str(right.value))
        return (left_key > right_key) - (left_key < right_key)
    if left.kind != right.kind:
        return None
    left_key = _normalized_text(str(left.value))
    right_key = _normalized_text(str(right.value))
    return (left_key > right_key) - (left_key < right_key)


def _aggregate(
    tables: tuple[StructuredTable, ...],
    *,
    grouped: bool,
    idempotency_key: str,
    question: str,
    run_id: UUID,
) -> StructuredAnalysisResult:
    table = tables[0]
    conditions = _conditions(table, question)
    rows = [
        row for selected in tables for row in selected.rows if _row_matches(row, conditions)
    ]
    examined = sum(len(selected.rows) for selected in tables)
    malformed = sum(selected.malformed_rows for selected in tables)
    operation = _aggregate_operation(question)
    mentioned = _mentioned_columns(table, question)
    group_columns = _group_columns(table, question) if grouped else []
    numeric_columns = [
        index
        for index in range(len(table.headers))
        if any(row.values[index].kind == "number" for row in rows)
    ]
    value_column = next(
        (
            index
            for index in mentioned
            if index in numeric_columns and index not in group_columns
        ),
        numeric_columns[0] if len(numeric_columns) == 1 else None,
    )
    if operation != "count" and value_column is None:
        return _analysis_failure(
            tables,
            examined=examined,
            malformed=malformed,
            message=(
                "Analysis capability failed: the requested numeric field is "
                "ambiguous or unavailable."
            ),
        )
    grouped_rows: list[tuple[tuple[int, ...], tuple[str, ...], list[StructuredRow]]] = []
    if not group_columns:
        grouped_rows.append(((), (), rows))
    else:
        groups: dict[tuple[str, ...], list[StructuredRow]] = defaultdict(list)
        for row in rows:
            if all(group_index < len(row.values) for group_index in group_columns):
                key = tuple(row.values[group_index].raw for group_index in group_columns)
                groups[key].append(row)
        grouped_rows.extend(
            (tuple(group_columns), group, group_rows)
            for group, group_rows in sorted(
                groups.items(), key=lambda item: tuple(value.casefold() for value in item[0])
            )
        )
    if len(grouped_rows) > EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT:
        return _analysis_failure(
            tables,
            examined=examined,
            malformed=malformed,
            message=(
                "Complete analysis found more result groups than the bounded response "
                "can publish."
            ),
        )

    claims: list[ClaimRecord] = []
    audits: list[RowAudit] = []
    for group_indexes, group_values, group_rows in grouped_rows:
        calculated = _calculate(operation, group_rows, value_column=value_column)
        if calculated is None:
            continue
        value, unit, contributor_rows = calculated
        if operation == "count":
            label = "Count"
        else:
            assert value_column is not None
            label = f"{operation.title()} {table.headers[value_column]}"
        group_label = ""
        if group_indexes:
            parts = [
                f"{table.headers[index]} {value}"
                for index, value in zip(group_indexes, group_values, strict=True)
            ]
            group_label = f" for {', '.join(parts)}"
        rendered = _render_decimal(value)
        rendered_with_unit = f"{rendered} {unit}" if unit else rendered
        claims.append(
            _claim(
                citations=_representative_citations(
                    contributor_rows, fallback=table.header_citation
                ),
                idempotency_key=idempotency_key,
                index=len(claims),
                run_id=run_id,
                text=f"{label}{group_label} is {rendered_with_unit}.",
                value=rendered_with_unit,
            )
        )
        audits.extend(_audits(contributor_rows, operation=operation))
    status: AnalysisStatus = "incomplete" if malformed else "complete"
    message = _bounded_message(
        f"Examined {examined} rows across {len(tables)} table(s); {len(rows)} matched. "
        f"Calculated {operation} for {len(claims)} result group(s)."
        + (f" {malformed} malformed row(s) were excluded." if malformed else "")
    )
    return StructuredAnalysisResult(
        audits=tuple(audits),
        claims=tuple(claims),
        examined_rows=examined,
        malformed_rows=malformed,
        matched_rows=len(rows),
        message=message,
        reconciliation=ReconciliationAudit(),
        status=status,
        tables_examined=len(tables),
    )


def _list_or_summarize(
    tables: tuple[StructuredTable, ...],
    *,
    exception_only: bool,
    idempotency_key: str,
    question: str,
    run_id: UUID,
) -> StructuredAnalysisResult:
    table = tables[0]
    conditions = _conditions(table, question)
    rows = [
        row for selected in tables for row in selected.rows if _row_matches(row, conditions)
    ]
    examined = sum(len(selected.rows) for selected in tables)
    malformed = sum(selected.malformed_rows for selected in tables)
    columns = _mentioned_columns(table, question)
    condition_columns = {condition.column for condition in conditions}
    output_columns = [index for index in columns if index not in condition_columns]
    if not output_columns:
        output_columns = [index for index in columns if index in condition_columns]
    if not output_columns:
        output_columns = (
            list(range(len(table.headers))) if "summary" in question.casefold() else [0]
        )
    row_level = (
        re.search(r"\b(?:identify|enumerate|list|show|each|every|all)\b", question, re.I)
        is not None
    )
    if row_level:
        # A list is published as one bounded claim per row, so preserve the full
        # row rather than silently dropping fields the caller needs to audit it.
        identity = _identity_columns(table, rows)
        output_columns = list(dict.fromkeys([*identity[:1], *range(len(table.headers))]))
    result_count = len(rows) if row_level else len(rows) * len(output_columns)
    if result_count > EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT:
        return _analysis_failure(
            tables,
            examined=examined,
            malformed=malformed,
            message=(
                "Complete analysis found more matching row values than the bounded "
                "response can publish; narrow the requested fields or filter."
            ),
        )
    claims: list[ClaimRecord] = []
    audits: list[RowAudit] = []
    for row in rows:
        valid_columns = [column for column in output_columns if column < len(row.values)]
        if row_level:
            rendered = [
                f"{table.headers[column]}: {row.values[column].raw or 'null'}"
                for column in valid_columns
            ]
            if not rendered:
                malformed += 1
                continue
            value_column = next(
                (
                    condition.column
                    for condition in conditions
                    if condition.column in valid_columns
                ),
                valid_columns[0],
            )
            value = row.values[value_column].raw or "null"
            claims.append(
                _claim(
                    citations=(row.citation,),
                    idempotency_key=idempotency_key,
                    index=len(claims),
                    run_id=run_id,
                    text="; ".join(rendered) + ".",
                    value=value,
                )
            )
            audits.append(
                RowAudit(
                    citation=row.citation,
                    operation="exception" if exception_only else "select",
                    row_ordinal=row.ordinal,
                    source_name=row.citation.source_name,
                    table_id=row.table_id,
                )
            )
            continue
        for column in valid_columns:
            typed = row.values[column]
            value = typed.raw if typed.raw else "null"
            row_label = _row_label(table, row, excluded={column})
            claims.append(
                _claim(
                    citations=(row.citation,),
                    idempotency_key=idempotency_key,
                    index=len(claims),
                    run_id=run_id,
                    text=f"{row_label}{table.headers[column]}: {value}.",
                    value=value,
                )
            )
            audits.append(
                RowAudit(
                    citation=row.citation,
                    operation="exception" if exception_only else "select",
                    row_ordinal=row.ordinal,
                    source_name=row.citation.source_name,
                    table_id=row.table_id,
                )
            )
    status: AnalysisStatus = "incomplete" if malformed else "complete"
    message = _bounded_message(
        f"Examined {examined} rows across {len(tables)} table(s); {len(rows)} matched"
        + (f" and {malformed} malformed row(s) were excluded." if malformed else ".")
    )
    return StructuredAnalysisResult(
        audits=tuple(audits),
        claims=tuple(claims),
        examined_rows=examined,
        malformed_rows=malformed,
        matched_rows=len(rows),
        message=message,
        reconciliation=ReconciliationAudit(),
        status=status,
        tables_examined=len(tables),
    )


def _universal(
    tables: tuple[StructuredTable, ...],
    *,
    idempotency_key: str,
    question: str,
    run_id: UUID,
) -> StructuredAnalysisResult:
    table = tables[0]
    examined = sum(len(selected.rows) for selected in tables)
    malformed = sum(selected.malformed_rows for selected in tables)
    mentioned = _mentioned_columns(table, question)
    if not mentioned:
        return _analysis_failure(
            tables,
            examined=examined,
            malformed=malformed,
            message=(
                "Analysis capability failed: name the field required for the "
                "completeness check."
            ),
        )
    column = mentioned[0]
    conditions = _conditions(table, question)
    target_conditions = tuple(item for item in conditions if item.column == column)
    rows = [row for selected in tables for row in selected.rows]
    if target_conditions:
        failures = [row for row in rows if not _row_matches(row, target_conditions)]
        criterion = "satisfy the requested condition"
    else:
        failures = [row for row in rows if row.values[column].is_null]
        criterion = f"have {table.headers[column]}"
    if malformed:
        return _analysis_failure(
            tables,
            examined=examined,
            malformed=malformed,
            message=(
                f"Completeness cannot be verified because {malformed} malformed "
                "row(s) could not be examined."
            ),
        )
    success = not failures
    value = "true" if success else "false"
    text = (
        f"Yes; all {examined} records {criterion}."
        if success
        else f"No; {len(failures)} of {examined} records do not {criterion}."
    )
    cited_rows = rows if success else failures
    claim = _claim(
        citations=_representative_citations(cited_rows, fallback=table.header_citation),
        idempotency_key=idempotency_key,
        index=0,
        run_id=run_id,
        text=text,
        value=value,
    )
    return StructuredAnalysisResult(
        audits=tuple(_audits(rows, operation="completeness")),
        claims=(claim,),
        examined_rows=examined,
        malformed_rows=0,
        matched_rows=examined - len(failures),
        message=_bounded_message(
            f"Examined every row in {len(tables)} relevant table(s): {examined} total, "
            f"{len(failures)} exception(s)."
        ),
        reconciliation=ReconciliationAudit(),
        status="complete",
        tables_examined=len(tables),
    )


def _reconcile(
    tables: tuple[StructuredTable, ...],
    *,
    idempotency_key: str,
    question: str,
    run_id: UUID,
    universal: bool,
) -> StructuredAnalysisResult:
    if len(tables) < 2:
        return _analysis_failure(
            tables,
            examined=sum(len(table.rows) for table in tables),
            malformed=sum(table.malformed_rows for table in tables),
            message=(
                "Reconciliation requires two relevant structured tables; only one "
                "was available."
            ),
        )
    left, right = tables[:2]
    if universal:
        left, right = _orient_universal_tables(left, right, question=question)
    common = _common_columns(left, right)
    key_pair = _join_key(left, right, common=common, question=question)
    if key_pair is None:
        return _analysis_failure(
            (left, right),
            examined=len(left.rows) + len(right.rows),
            malformed=left.malformed_rows + right.malformed_rows,
            message="Reconciliation could not determine one unambiguous shared key.",
        )
    left_key, right_key = key_pair
    measure_pair = _measure_columns(left, right, common=common, question=question)
    left_groups = _group_rows(left.rows, left_key)
    right_groups = _group_rows(right.rows, right_key)
    left_keys, right_keys = set(left_groups), set(right_groups)
    matched = sorted(left_keys & right_keys)
    unmatched_left = tuple(sorted(left_keys - right_keys))
    unmatched_right = tuple(sorted(right_keys - left_keys))
    duplicates = sum(len(rows) > 1 for rows in left_groups.values()) + sum(
        len(rows) > 1 for rows in right_groups.values()
    )
    malformed = left.malformed_rows + right.malformed_rows
    if malformed:
        return _analysis_failure(
            (left, right),
            examined=len(left.rows) + len(right.rows),
            malformed=malformed,
            message=(
                f"Reconciliation is incomplete because {malformed} malformed row(s) "
                "could not be examined."
            ),
            reconciliation=ReconciliationAudit(
                duplicate_key_count=duplicates,
                left_rows=len(left.rows),
                matched_keys=len(matched),
                right_rows=len(right.rows),
                unmatched_left_keys=unmatched_left,
                unmatched_right_keys=unmatched_right,
            ),
        )
    if universal:
        success = not unmatched_left
        right_only = len(unmatched_right)
        if success:
            text = (
                f"Yes; all {len(left_keys)} key(s) from {left.source_name} match at "
                f"least one row in {right.source_name}."
            )
            if right_only:
                text += (
                    f" {right_only} right-only key(s) do not invalidate this "
                    "left-to-right completeness check."
                )
        else:
            text = (
                f"No; {len(unmatched_left)} of {len(left_keys)} key(s) from "
                f"{left.source_name} have no matching row in {right.source_name}."
            )
        cited_rows = [*left.rows, *right.rows]
        claim = _claim(
            citations=_representative_citations(cited_rows, fallback=left.header_citation),
            idempotency_key=idempotency_key,
            index=0,
            run_id=run_id,
            text=text,
            value="true" if success else "false",
        )
        reconciliation = ReconciliationAudit(
            duplicate_key_count=duplicates,
            left_rows=len(left.rows),
            matched_keys=len(matched),
            right_rows=len(right.rows),
            unmatched_left_keys=unmatched_left,
            unmatched_right_keys=unmatched_right,
        )
        return StructuredAnalysisResult(
            audits=tuple(_audits(cited_rows, operation="reconcile")),
            claims=(claim,),
            examined_rows=len(left.rows) + len(right.rows),
            malformed_rows=0,
            matched_rows=len(matched),
            message=_bounded_message(
                f"Checked all {len(left_keys)} left-side keys: {len(matched)} matched, "
                f"{len(unmatched_left)} unmatched; observed {right_only} additional "
                "right-only key(s)."
            ),
            reconciliation=reconciliation,
            status="complete",
            tables_examined=2,
        )
    if len(left_keys | right_keys) > EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT:
        return _analysis_failure(
            (left, right),
            examined=len(left.rows) + len(right.rows),
            malformed=0,
            message=(
                "Complete reconciliation found more keys than the bounded response "
                "can publish; narrow the key range."
            ),
        )

    claims: list[ClaimRecord] = []
    audits: list[RowAudit] = []
    for key in sorted(left_keys | right_keys):
        left_rows = left_groups.get(key, [])
        right_rows = right_groups.get(key, [])
        if not left_rows or not right_rows:
            side = left.source_name if left_rows else right.source_name
            rows = left_rows or right_rows
            claims.append(
                _claim(
                    citations=_representative_citations(rows, fallback=left.header_citation),
                    idempotency_key=idempotency_key,
                    index=len(claims),
                    run_id=run_id,
                    text=f"Key {key} is unmatched and appears only in {side}.",
                    value="unmatched",
                )
            )
            audits.extend(_audits(rows, operation="unmatched"))
            continue
        if measure_pair is None:
            text = (
                f"Key {key} matched {len(left_rows)} left row(s) to "
                f"{len(right_rows)} right row(s)."
            )
            value = f"{len(left_rows)}:{len(right_rows)}"
        else:
            left_measure, right_measure = measure_pair
            left_total = _sum_column(left_rows, left_measure)
            right_total = _sum_column(right_rows, right_measure)
            if left_total is None or right_total is None or left_total[1] != right_total[1]:
                return _analysis_failure(
                    (left, right),
                    examined=len(left.rows) + len(right.rows),
                    malformed=0,
                    message="Reconciliation found incompatible or non-numeric measure units.",
                )
            difference = left_total[0] - right_total[0]
            unit = left_total[1]
            rendered_left = _render_decimal(left_total[0])
            rendered_right = _render_decimal(right_total[0])
            rendered_difference = _render_decimal(difference)
            unit_suffix = f" {unit}" if unit else ""
            text = (
                f"Key {key}: {left.source_name} totals {rendered_left}{unit_suffix}; "
                f"{right.source_name} totals {rendered_right}{unit_suffix}; "
                f"difference {rendered_difference}{unit_suffix}."
            )
            value = f"{rendered_difference}{unit_suffix}"
        claims.append(
            _claim(
                citations=(left_rows[0].citation, right_rows[0].citation),
                idempotency_key=idempotency_key,
                index=len(claims),
                run_id=run_id,
                text=text,
                value=value,
            )
        )
        audits.extend(_audits([*left_rows, *right_rows], operation="reconcile"))
    reconciliation = ReconciliationAudit(
        duplicate_key_count=duplicates,
        left_rows=len(left.rows),
        matched_keys=len(matched),
        right_rows=len(right.rows),
        unmatched_left_keys=unmatched_left,
        unmatched_right_keys=unmatched_right,
    )
    message = _bounded_message(
        f"Reconciled {len(left.rows)} left and {len(right.rows)} right rows across "
        f"{len(left_keys | right_keys)} keys: {len(matched)} matched, "
        f"{len(unmatched_left) + len(unmatched_right)} unmatched, {duplicates} "
        "duplicate-key group(s)."
    )
    return StructuredAnalysisResult(
        audits=tuple(audits),
        claims=tuple(claims),
        examined_rows=len(left.rows) + len(right.rows),
        malformed_rows=0,
        matched_rows=len(matched),
        message=message,
        reconciliation=reconciliation,
        status="complete",
        tables_examined=2,
    )


def _common_columns(left: StructuredTable, right: StructuredTable) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for left_index, left_header in enumerate(left.headers):
        for right_index, right_header in enumerate(right.headers):
            if _headers_equivalent(left_header, right_header):
                pairs.append((left_index, right_index))
    return pairs


def _orient_universal_tables(
    left: StructuredTable, right: StructuredTable, *, question: str
) -> tuple[StructuredTable, StructuredTable]:
    """Put the universally quantified collection on the left side of the join."""

    match = re.search(
        r"\b(?:all|each|every)\s+(?P<target>.+?)\s+"
        r"(?:have|match|reconcile|satisfy|support)\b",
        question,
        re.I,
    )
    if match is None:
        return left, right
    target = match.group("target")
    left_score = _table_score(left, target)
    right_score = _table_score(right, target)
    return (right, left) if right_score > left_score else (left, right)


def _join_key(
    left: StructuredTable,
    right: StructuredTable,
    *,
    common: list[tuple[int, int]],
    question: str,
) -> tuple[int, int] | None:
    if not common:
        return None
    mentioned = [
        pair
        for pair in common
        if _column_score(left.headers[pair[0]], question) > 0
        and left.headers[pair[0]].casefold() not in _AGGREGATE_WORDS
    ]
    if len(mentioned) == 1:
        return mentioned[0]
    by_match = re.search(r"\bby\s+([^?,;]+)", question, re.I)
    if by_match is not None:
        scoped = [
            pair
            for pair in common
            if _column_score(left.headers[pair[0]], by_match.group(1)) > 0
        ]
        if len(scoped) == 1:
            return scoped[0]
    if len(common) == 1:
        return common[0]
    # A reconciliation key must actually connect the two tables.  Distinctness
    # alone can prefer unrelated per-source identifiers that have zero overlap.
    scored: list[tuple[tuple[int, float, float, float], tuple[int, int]]] = []
    for pair in common:
        left_values = {
            _normalized_text(row.values[pair[0]].raw)
            for row in left.rows
            if pair[0] < len(row.values) and not row.values[pair[0]].is_null
        }
        right_values = {
            _normalized_text(row.values[pair[1]].raw)
            for row in right.rows
            if pair[1] < len(row.values) and not row.values[pair[1]].is_null
        }
        overlap = left_values & right_values
        if not overlap:
            continue
        union = left_values | right_values
        coverage = min(
            len(overlap) / len(left_values),
            len(overlap) / len(right_values),
        )
        jaccard = len(overlap) / len(union)
        identifier_ratio = (
            sum(
                row.values[pair[0]].kind == "identifier"
                for row in left.rows
                if pair[0] < len(row.values)
            )
            + sum(
                row.values[pair[1]].kind == "identifier"
                for row in right.rows
                if pair[1] < len(row.values)
            )
        ) / max(1, len(left.rows) + len(right.rows))
        scored.append(((len(overlap), coverage, jaccard, identifier_ratio), pair))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _measure_columns(
    left: StructuredTable,
    right: StructuredTable,
    *,
    common: list[tuple[int, int]],
    question: str,
) -> tuple[int, int] | None:
    left_numeric = [
        index
        for index in range(len(left.headers))
        if any(row.values[index].kind == "number" for row in left.rows)
    ]
    right_numeric = [
        index
        for index in range(len(right.headers))
        if any(row.values[index].kind == "number" for row in right.rows)
    ]
    left_mentioned = [
        index for index in left_numeric if _column_score(left.headers[index], question) > 0
    ]
    right_mentioned = [
        index for index in right_numeric if _column_score(right.headers[index], question) > 0
    ]
    if len(left_mentioned) == len(right_mentioned) == 1:
        return left_mentioned[0], right_mentioned[0]

    numeric = [
        pair
        for pair in common
        if any(row.values[pair[0]].kind == "number" for row in left.rows)
        and any(row.values[pair[1]].kind == "number" for row in right.rows)
    ]
    mentioned = [pair for pair in numeric if _column_score(left.headers[pair[0]], question) > 0]
    if len(mentioned) == 1:
        return mentioned[0]
    return numeric[0] if len(numeric) == 1 else None


def _calculate(
    operation: str,
    rows: list[StructuredRow],
    *,
    value_column: int | None,
) -> tuple[Decimal, str | None, list[StructuredRow]] | None:
    if operation == "count":
        return Decimal(len(rows)), None, rows
    assert value_column is not None
    values = [
        (row, value) for row in rows if (value := row.values[value_column]).kind == "number"
    ]
    if not values:
        return None
    units = {value.unit for _, value in values}
    if len(units) > 1:
        return None
    decimals = [value.value for _, value in values]
    if not all(isinstance(value, Decimal) for value in decimals):
        return None
    typed_decimals = [value for value in decimals if isinstance(value, Decimal)]
    if operation == "sum":
        result = sum(typed_decimals, Decimal())
    elif operation == "average":
        result = sum(typed_decimals, Decimal()) / Decimal(len(typed_decimals))
    elif operation == "minimum":
        result = min(typed_decimals)
    else:
        result = max(typed_decimals)
    return result, next(iter(units)), [row for row, _ in values]


def _sum_column(rows: list[StructuredRow], column: int) -> tuple[Decimal, str | None] | None:
    calculated = _calculate("sum", rows, value_column=column)
    return None if calculated is None else (calculated[0], calculated[1])


def _aggregate_operation(question: str) -> str:
    normalized = question.casefold()
    if re.search(r"\b(?:count|how\s+many)\b", normalized):
        return "count"
    if re.search(r"\b(?:average|avg|mean)\b", normalized):
        return "average"
    if re.search(r"\b(?:minimum|min|lowest)\b", normalized):
        return "minimum"
    if re.search(r"\b(?:maximum|max|highest)\b", normalized):
        return "maximum"
    if re.search(r"\b(?:break\s*down|group(?:ed)?)\b", normalized):
        return "count"
    return "sum"


def _group_column(table: StructuredTable, question: str) -> int | None:
    columns = _group_columns(table, question)
    return columns[0] if len(columns) == 1 else None


def _group_columns(table: StructuredTable, question: str) -> list[int]:
    match = re.search(r"\b(?:by|per)\s+(?P<field>[^?,;]+)", question, re.I)
    if match is None:
        return []
    return [
        index
        for index, header in enumerate(table.headers)
        if _column_score(header, match.group("field")) > 0
    ]


def _identity_columns(table: StructuredTable, rows: list[StructuredRow]) -> list[int]:
    """Rank stable row identifiers without relying on domain-specific headers."""

    if not rows:
        return []
    scored: list[tuple[float, int]] = []
    for column in range(len(table.headers)):
        values = [row.values[column] for row in rows if column < len(row.values)]
        non_null = [value for value in values if not value.is_null]
        if not non_null:
            continue
        distinct = len({_normalized_text(value.raw) for value in non_null})
        uniqueness = distinct / len(non_null)
        identifier_ratio = sum(value.kind == "identifier" for value in non_null) / len(non_null)
        scored.append((uniqueness + identifier_ratio, column))
    return [column for _, column in sorted(scored, key=lambda item: (-item[0], item[1]))]


def _group_rows(rows: tuple[StructuredRow, ...], column: int) -> dict[str, list[StructuredRow]]:
    groups: dict[str, list[StructuredRow]] = defaultdict(list)
    for row in rows:
        groups[row.values[column].raw].append(row)
    return groups


def _row_label(table: StructuredTable, row: StructuredRow, *, excluded: set[int]) -> str:
    for index, value in enumerate(row.values):
        if index not in excluded and value.kind in {"identifier", "text"} and not value.is_null:
            return f"{table.headers[index]} {value.raw} — "
    return f"Row {row.ordinal} — "


def _claim(
    *,
    citations: tuple[PassageRecord, ...],
    idempotency_key: str,
    index: int,
    run_id: UUID,
    text: str,
    value: str,
) -> ClaimRecord:
    bounded_value = value[:120].strip()
    return ClaimRecord(
        citations=citations[:2],
        claim_id=uuid5(run_id, f"{idempotency_key}:structured:{index}"),
        relation="fact",
        text=text[:800].strip(),
        value=bounded_value or "n/a",
    )


def _passage(block: RetrievedBlock, start: int, end: int) -> PassageRecord:
    end = min(end, start + 2_000)
    quote = block.text[start:end]
    line_start = (
        None
        if block.line_start_one_based is None
        else block.line_start_one_based + block.text.count("\n", 0, start)
    )
    return PassageRecord(
        block_id=block.block_id,
        drive_file_id=block.drive_file_id,
        end_exclusive_in_block=end,
        exact_quote=quote,
        line_start_one_based=line_start,
        origin_kind=block.origin_kind,
        page_index_zero_based=block.page_index_zero_based,
        path=block.path,
        printed_page_label=block.printed_page_label,
        source_name=block.source_name,
        start_in_block=start,
    )


def _representative_citations(
    rows: list[StructuredRow], *, fallback: PassageRecord
) -> tuple[PassageRecord, ...]:
    if not rows:
        return (fallback,)
    if len(rows) == 1:
        return (rows[0].citation,)
    return (rows[0].citation, rows[-1].citation)


def _audits(rows: list[StructuredRow], *, operation: str) -> list[RowAudit]:
    return [
        RowAudit(
            citation=row.citation,
            operation=operation,
            row_ordinal=row.ordinal,
            source_name=row.citation.source_name,
            table_id=row.table_id,
        )
        for row in rows
    ]


def _analysis_failure(
    tables: tuple[StructuredTable, ...],
    *,
    examined: int,
    malformed: int,
    message: str,
    reconciliation: ReconciliationAudit | None = None,
) -> StructuredAnalysisResult:
    return StructuredAnalysisResult(
        audits=(),
        claims=(),
        examined_rows=examined,
        malformed_rows=malformed,
        matched_rows=0,
        message=_bounded_message(message),
        reconciliation=reconciliation or ReconciliationAudit(),
        status="incomplete" if malformed else "unsupported",
        tables_examined=len(tables),
    )


def _result(
    *,
    message: str,
    status: AnalysisStatus,
    tables_examined: int = 0,
) -> StructuredAnalysisResult:
    return StructuredAnalysisResult(
        audits=(),
        claims=(),
        examined_rows=0,
        malformed_rows=0,
        matched_rows=0,
        message=message,
        reconciliation=ReconciliationAudit(),
        status=status,
        tables_examined=tables_examined,
    )


def _cells(text: str, delimiter: str) -> list[str]:
    stripped = text.strip(" ") if delimiter == "\t" else text.strip()
    if delimiter == "|":
        stripped = stripped.strip("|")
    return [" ".join(cell.split()) for cell in stripped.split(delimiter)]


def _delimiter(text: str) -> str | None:
    if text.count("\t") >= 1:
        return "\t"
    if text.count("|") >= 2:
        return "|"
    return None


def _operator(value: str) -> Literal["eq", "ge", "gt", "le", "lt", "ne"]:
    normalized = " ".join(value.casefold().split())
    if normalized in {"!=", "<>", "is not", "not equal to"}:
        return "ne"
    if normalized in {">", "greater than", "more than", "over", "above", "after"}:
        return "gt"
    if normalized in {">=", "at least"}:
        return "ge"
    if normalized in {"<", "less than", "under", "below", "before"}:
        return "lt"
    if normalized in {"<=", "at most"}:
        return "le"
    return "eq"


def _parse_date(value: str) -> date | None:
    try:
        if _ISO_DATE.fullmatch(value):
            return date.fromisoformat(value)
        if _SLASH_DATE.fullmatch(value):
            return datetime.strptime(value, "%m/%d/%Y").date()
        if _NORMALIZED_ISO_DATE.fullmatch(value):
            year, month, day = (int(part) for part in value.split())
            return date(year, month, day)
        if _NORMALIZED_SLASH_DATE.fullmatch(value):
            month, day, year = (int(part) for part in value.split())
            return date(year, month, day)
    except ValueError:
        return None
    return None


def _unit(prefix: str | None, suffix: str | None) -> str | None:
    if suffix:
        return suffix.upper()
    return {"$": "USD", "€": "EUR", "£": "GBP"}.get(prefix or "")


def _render_decimal(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _headers_equivalent(left: str, right: str) -> bool:
    left_tokens = normalized_query_tokens(_normalized_header(left))
    right_tokens = normalized_query_tokens(_normalized_header(right))
    return len(left_tokens) == len(right_tokens) and all(
        tokens_equivalent(left_token, right_token)
        for left_token, right_token in zip(left_tokens, right_tokens, strict=True)
    )


def _has_duplicate_headers(table: StructuredTable) -> bool:
    normalized = [_normalized_header(header) for header in table.headers]
    return len(set(normalized)) != len(normalized)


def _normalized_header(value: str) -> str:
    return _normalized_text(value).strip()


def _normalized_text(value: str) -> str:
    return " ".join(
        match.group(0).casefold()
        for match in re.finditer(r"[^\W_]+|\d+", unicodedata.normalize("NFKC", value))
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _bounded_message(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 280 else normalized[:277].rstrip() + "..."
