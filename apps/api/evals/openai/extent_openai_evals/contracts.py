"""Dependency-free contracts shared by the eval runner, adapter, and grader."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Literal

MetricName = Literal[
    "answer_accuracy",
    "citation_integrity",
    "pass_rate",
    "policy_compliance",
    "uncertainty_handling",
]

_ALLOWED_IDEAL_KEYS = frozenset(
    {
        "citation_mode",
        "citation_quote_includes",
        "claim_relations_exact",
        "claim_text_includes",
        "claim_values_exact",
        "claim_values_include",
        "coverage_gap_reasons",
        "generation_status",
        "max_claims",
        "message_includes",
        "min_claims",
        "passage_mode",
        "policy_version",
        "required_sources",
        "status",
    }
)
_ALLOWED_MODES = frozenset({"forbidden", "optional", "required"})
_COMPLETE_DATA_POLICIES = frozenset(
    {
        "exhaustive-extraction-policy-v1",
        "exhaustive-premium-policy-v1",
        "structured-analysis-policy-v1",
    }
)
_NO_EVIDENCE_POLICIES = frozenset({"clarification-policy-v1", "source-state-policy-v1"})
_SUPPORTED_STATUSES = frozenset({"changed", "evidence_supported"})
_SOURCE_BLOCK_LIMIT = 1_800


@dataclass(frozen=True)
class CitationSourceBlock:
    """One independently reconstructed ingestion block used for locator checks."""

    line_start_one_based: int
    text: str


SourceCorpus = dict[str, tuple[CitationSourceBlock, ...]]


class CasebookError(ValueError):
    """Raised when an eval casebook is malformed or unsafe to load."""


class SourceCorpusError(ValueError):
    """Raised when independent citation-source validation cannot be configured."""


def load_casebook(path: Path) -> list[dict[str, Any]]:
    """Load and validate a bounded JSONL casebook."""

    if not path.is_file():
        raise CasebookError(f"casebook does not exist: {path}")
    if path.stat().st_size > 2_000_000:
        raise CasebookError("casebook exceeds the 2 MB evaluation limit")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            candidate = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise CasebookError(f"line {line_number} is not valid JSON") from error
        if not isinstance(candidate, dict):
            raise CasebookError(f"line {line_number} must contain one JSON object")
        validate_case(candidate, line_number=line_number)
        case_id = candidate["case_id"]
        if case_id in seen:
            raise CasebookError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        cases.append(candidate)
    if not cases:
        raise CasebookError("casebook must contain at least one case")
    if len(cases) > 200:
        raise CasebookError("casebook exceeds the 200-case evaluation limit")
    return cases


def load_source_corpus(root: Path) -> SourceCorpus:
    """Load a bounded plain-text/CSV corpus using ingestion-equivalent normalization."""

    if not root.is_dir():
        raise SourceCorpusError(f"citation source root does not exist: {root}")
    files = sorted(path for path in root.iterdir() if path.is_file())
    if not files or len(files) > 200:
        raise SourceCorpusError("citation source root must contain between 1 and 200 files")
    total_bytes = 0
    corpus: SourceCorpus = {}
    for path in files:
        if path.is_symlink():
            raise SourceCorpusError(f"citation source cannot be a symlink: {path.name}")
        if path.name in corpus:
            raise SourceCorpusError(f"duplicate citation source name: {path.name}")
        size = path.stat().st_size
        total_bytes += size
        if size > 5_000_000 or total_bytes > 20_000_000:
            raise SourceCorpusError("citation source corpus exceeds its evaluation size limit")
        try:
            decoded = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            raise SourceCorpusError(
                f"citation source is not UTF-8 text: {path.name}"
            ) from error
        suffix = path.suffix.casefold()
        if suffix == ".csv":
            normalized, has_table = _normalize_csv_source(decoded, source_name=path.name)
            ranges = (
                _bounded_line_blocks(normalized, _SOURCE_BLOCK_LIMIT)
                if has_table
                else _bounded_text_blocks(normalized, _SOURCE_BLOCK_LIMIT)
            )
        elif suffix in {".md", ".markdown", ".text", ".txt"}:
            normalized = _normalize_plain_source(decoded)
            ranges = _bounded_text_blocks(normalized, _SOURCE_BLOCK_LIMIT)
        else:
            raise SourceCorpusError(
                f"citation source validation does not support {path.name}; "
                "use UTF-8 text, Markdown, or CSV"
            )
        if not normalized:
            raise SourceCorpusError(f"citation source contains no text: {path.name}")
        corpus[path.name] = tuple(
            CitationSourceBlock(
                line_start_one_based=1 + normalized.count("\n", 0, start),
                text=text,
            )
            for start, _, text in ranges
        )
    return corpus


def question_from_prompt(value: object) -> str:
    """Extract exactly the standalone user question accepted by the live adapter."""

    formatter = getattr(value, "to_formatted_prompt", None)
    if callable(formatter):
        value = formatter()
    if isinstance(value, str):
        question = value.strip()
    elif (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
        and value[0].get("role") == "user"
        and isinstance(value[0].get("content"), str)
    ):
        question = value[0]["content"].strip()
    else:
        raise ValueError("prompt must contain exactly one user question")
    if not 3 <= len(question) <= 2_000:
        raise ValueError("question must contain 3 to 2,000 non-whitespace characters")
    return question


def validate_case(case: dict[str, Any], *, line_number: int | None = None) -> None:
    """Validate one OpenAI Evals sample without importing the framework."""

    prefix = f"line {line_number}: " if line_number is not None else ""
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id or len(case_id) > 100:
        raise CasebookError(f"{prefix}case_id must be a non-empty string under 101 chars")
    try:
        question_from_prompt(case.get("input"))
    except ValueError as error:
        raise CasebookError(
            f"{prefix}input must contain exactly one 3-to-2,000 character user question"
        ) from error
    ideal = case.get("ideal")
    if not isinstance(ideal, dict):
        raise CasebookError(f"{prefix}ideal must be an object")
    unknown = set(ideal) - _ALLOWED_IDEAL_KEYS
    if unknown:
        raise CasebookError(f"{prefix}unknown ideal keys: {sorted(unknown)!r}")
    for key in ("status", "policy_version", "generation_status"):
        if key not in ideal:
            raise CasebookError(f"{prefix}ideal.{key} is required")
        if not _string_or_string_list(ideal[key]):
            raise CasebookError(f"{prefix}ideal.{key} must be a string or string list")
    for key in (
        "claim_relations_exact",
        "claim_text_includes",
        "claim_values_exact",
        "claim_values_include",
        "citation_quote_includes",
        "coverage_gap_reasons",
        "message_includes",
        "required_sources",
    ):
        value = ideal.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CasebookError(f"{prefix}ideal.{key} must be a string list")
    for key in ("min_claims", "max_claims"):
        value = ideal.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise CasebookError(f"{prefix}ideal.{key} must be a non-negative integer")
    minimum = ideal.get("min_claims", 0)
    maximum = ideal.get("max_claims")
    if isinstance(maximum, int) and minimum > maximum:
        raise CasebookError(f"{prefix}ideal.min_claims cannot exceed ideal.max_claims")
    for key in ("citation_mode", "passage_mode"):
        value = ideal.get(key, "optional")
        if value not in _ALLOWED_MODES:
            raise CasebookError(f"{prefix}ideal.{key} has an unsupported mode")


def canonicalize_response(
    payload: object, *, expected_question: str | None = None
) -> dict[str, Any]:
    """Remove volatile identifiers while retaining claims and their evidence."""

    if not isinstance(payload, dict):
        raise ValueError("Extent response must be a JSON object")
    if expected_question is not None:
        response_question = _required_string(payload, "question").strip()
        if response_question != expected_question:
            raise ValueError("Extent response question does not match the request")
    claims = _required_list(payload, "claims")
    passages = _required_list(payload, "passages")
    gaps = _required_list(payload, "coverageGapReasons", "coverage_gap_reasons")
    if not all(isinstance(item, str) for item in gaps):
        raise ValueError("coverage gap reasons must be strings")
    return {
        "claims": [_canonical_claim(item) for item in claims],
        "coverage_gap_reasons": sorted(gaps),
        "generation_status": _required_string(payload, "generationStatus", "generation_status"),
        "message": _required_string(payload, "message"),
        "passages": [_canonical_citation(item) for item in passages],
        "policy_version": _required_string(payload, "policyVersion", "policy_version"),
        "status": _required_string(payload, "status"),
    }


def score_completion(
    completion: dict[str, Any],
    ideal: dict[str, Any],
    *,
    source_corpus: SourceCorpus | None = None,
) -> dict[MetricName, bool]:
    """Score one canonical publication against deterministic expectations."""

    claims = completion.get("claims")
    passages = completion.get("passages")
    if not isinstance(claims, list) or not isinstance(passages, list):
        return _all_failed()

    expected_statuses = _expected_strings(ideal, "status")
    expected_policies = _expected_strings(ideal, "policy_version")
    expected_generations = _expected_strings(ideal, "generation_status")
    status_matches = _matches_expected(completion.get("status"), expected_statuses)
    generation_matches = _matches_expected(
        completion.get("generation_status"), expected_generations
    )
    claim_count_matches = len(claims) >= ideal.get("min_claims", 0) and (
        ideal.get("max_claims") is None or len(claims) <= ideal["max_claims"]
    )
    raw_values = [claim.get("value") for claim in claims if isinstance(claim, dict)]
    values = [value for value in raw_values if isinstance(value, str)]
    exact_values = ideal.get("claim_values_exact")
    values_exact = exact_values is None or (
        len(values) == len(raw_values) and Counter(values) == Counter(exact_values)
    )
    values_include = _counter_contains(values, ideal.get("claim_values_include", []))
    combined_claim_text = "\n".join(
        str(claim.get("text", "")) for claim in claims if isinstance(claim, dict)
    ).casefold()
    claim_text_matches = all(
        fragment.casefold() in combined_claim_text
        for fragment in ideal.get("claim_text_includes", [])
    )
    message = completion.get("message")
    message_matches = isinstance(message, str) and all(
        fragment.casefold() in message.casefold()
        for fragment in ideal.get("message_includes", [])
    )
    gaps = completion.get("coverage_gap_reasons")
    gaps_match = "coverage_gap_reasons" not in ideal or (
        isinstance(gaps, list) and Counter(gaps) == Counter(ideal["coverage_gap_reasons"])
    )
    actual_relations = [claim.get("relation") for claim in claims if isinstance(claim, dict)]
    relations_match = "claim_relations_exact" not in ideal or Counter(
        actual_relations
    ) == Counter(ideal["claim_relations_exact"])

    answer_accuracy = all(
        (
            status_matches,
            generation_matches,
            claim_count_matches,
            values_exact,
            values_include,
            claim_text_matches,
            message_matches,
            gaps_match,
            relations_match,
        )
    )
    policy_compliance = _matches_expected(
        completion.get("policy_version"), expected_policies
    ) and _policy_shape_is_valid(completion)
    citation_integrity = _evidence_is_valid(completion, ideal, source_corpus=source_corpus)
    uncertainty_handling = status_matches and _uncertainty_shape_is_valid(completion)
    pass_rate = all(
        (answer_accuracy, citation_integrity, policy_compliance, uncertainty_handling)
    )
    return {
        "answer_accuracy": answer_accuracy,
        "citation_integrity": citation_integrity,
        "pass_rate": pass_rate,
        "policy_compliance": policy_compliance,
        "uncertainty_handling": uncertainty_handling,
    }


def _canonical_claim(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("each claim must be an object")
    citations = _required_list(value, "citations")
    raw_value = _optional_string(value, "value")
    return {
        "citations": [_canonical_citation(item) for item in citations],
        "relation": _required_string(value, "relation"),
        "text": _required_string(value, "text"),
        "value": raw_value,
    }


def _canonical_citation(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("each evidence passage must be an object")
    return {
        "end_exclusive_in_block": _required_integer(
            value, "endExclusiveInBlock", "end_exclusive_in_block"
        ),
        "exact_quote": _required_string(value, "exactQuote", "exact_quote"),
        "line_start_one_based": _optional_integer(
            value, "lineStartOneBased", "line_start_one_based"
        ),
        "normalized_value": _optional_string(value, "normalizedValue", "normalized_value"),
        "origin_kind": _required_string(value, "originKind", "origin_kind"),
        "page_index_zero_based": _optional_integer(
            value, "pageIndexZeroBased", "page_index_zero_based"
        ),
        "raw_value": _optional_string(value, "rawValue", "raw_value"),
        "role": _optional_string(value, "role"),
        "source_name": _required_string(value, "sourceName", "source_name"),
        "start_in_block": _required_integer(value, "startInBlock", "start_in_block"),
    }


def _policy_shape_is_valid(completion: dict[str, Any]) -> bool:
    claims = completion["claims"]
    passages = completion["passages"]
    policy = completion.get("policy_version")
    generation = completion.get("generation_status")
    status = completion.get("status")
    if policy in _NO_EVIDENCE_POLICIES:
        return (
            generation == "completed"
            and status == "insufficient"
            and not claims
            and not passages
        )
    if policy in _COMPLETE_DATA_POLICIES:
        return (
            generation == "completed"
            and not passages
            and status in {"coverage_limited", "evidence_supported", "insufficient"}
            and all(
                isinstance(claim, dict)
                and claim.get("relation") == "fact"
                and isinstance(claim.get("value"), str)
                for claim in claims
            )
        )
    if policy == "publication-policy-v1":
        return len(claims) <= 3
    if policy == "retrieval-policy-v1":
        return not claims and generation in {"failed", "not_configured"}
    return False


def _evidence_is_valid(
    completion: dict[str, Any],
    ideal: dict[str, Any],
    *,
    source_corpus: SourceCorpus | None,
) -> bool:
    claims = completion["claims"]
    passages = completion["passages"]
    claim_citations = [
        citation
        for claim in claims
        if isinstance(claim, dict)
        for citation in claim.get("citations", [])
    ]
    all_evidence = [*claim_citations, *passages]
    if not all(_citation_is_valid(citation) for citation in all_evidence):
        return False
    if source_corpus is not None and not all(
        _citation_matches_source(citation, source_corpus) for citation in all_evidence
    ):
        return False
    combined_quotes = "\n".join(
        str(citation.get("exact_quote", ""))
        for citation in all_evidence
        if isinstance(citation, dict)
    ).casefold()
    if any(
        fragment.casefold() not in combined_quotes
        for fragment in ideal.get("citation_quote_includes", [])
    ):
        return False
    if any(
        not isinstance(claim, dict)
        or not isinstance(claim.get("citations"), list)
        or not claim["citations"]
        for claim in claims
    ):
        return False
    citation_mode = ideal.get("citation_mode", "optional")
    if citation_mode == "required" and (
        not claims
        or any(not isinstance(claim, dict) or not claim.get("citations") for claim in claims)
    ):
        return False
    if citation_mode == "forbidden" and claim_citations:
        return False
    passage_mode = ideal.get("passage_mode", "optional")
    if passage_mode == "required" and not passages:
        return False
    if passage_mode == "forbidden" and passages:
        return False
    if completion.get("policy_version") in {
        "publication-policy-v1",
        "exhaustive-extraction-policy-v1",
        "exhaustive-premium-policy-v1",
    } and any(not _claim_has_value_support(claim) for claim in claims):
        return False
    sources = {
        citation.get("source_name") for citation in all_evidence if isinstance(citation, dict)
    }
    return set(ideal.get("required_sources", [])) <= sources


def _citation_is_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    quote = value.get("exact_quote")
    start = value.get("start_in_block")
    end = value.get("end_exclusive_in_block")
    origin = value.get("origin_kind")
    if (
        not isinstance(quote, str)
        or not quote
        or not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 0
        or end <= start
        or end - start != len(quote)
    ):
        return False
    if origin == "pdf_page":
        page_index = value.get("page_index_zero_based")
        return (
            isinstance(page_index, int)
            and not isinstance(page_index, bool)
            and page_index >= 0
            and value.get("line_start_one_based") is None
        )
    if origin == "text_lines":
        line_start = value.get("line_start_one_based")
        return (
            isinstance(line_start, int)
            and not isinstance(line_start, bool)
            and line_start > 0
            and value.get("page_index_zero_based") is None
        )
    return False


def _citation_matches_source(value: object, source_corpus: SourceCorpus) -> bool:
    if not isinstance(value, dict):
        return False
    source_name = value.get("source_name")
    quote = value.get("exact_quote")
    line_start = value.get("line_start_one_based")
    start = value.get("start_in_block")
    end = value.get("end_exclusive_in_block")
    if (
        not isinstance(source_name, str)
        or not isinstance(quote, str)
        or not isinstance(line_start, int)
        or isinstance(line_start, bool)
        or not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
    ):
        return False
    blocks = source_corpus.get(source_name)
    if blocks is None:
        return False
    return any(
        0 <= start < end <= len(block.text)
        and block.text[start:end] == quote
        and block.line_start_one_based + block.text.count("\n", 0, start) == line_start
        for block in blocks
    )


def _claim_has_value_support(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    claim_value = value.get("value")
    citations = value.get("citations")
    if claim_value is None:
        return True
    if not isinstance(claim_value, str) or not isinstance(citations, list):
        return False
    expected = claim_value.casefold()
    return any(
        isinstance(citation, dict)
        and any(
            expected in candidate.casefold()
            for candidate in (
                citation.get("exact_quote"),
                citation.get("normalized_value"),
                citation.get("raw_value"),
            )
            if isinstance(candidate, str)
        )
        for citation in citations
    )


def _normalize_csv_source(decoded: str, *, source_name: str) -> tuple[str, bool]:
    try:
        rows = csv.reader(StringIO(decoded, newline=""), dialect="excel", strict=True)
        cell_rows = [tuple(_normalize_structured_cell(cell) for cell in row) for row in rows]
    except csv.Error as error:
        raise SourceCorpusError(f"citation source is not valid CSV: {source_name}") from error
    cell_rows = [row for row in cell_rows if any(cell for cell in row)]
    normalized = "\n".join("\t".join(row) for row in cell_rows)
    has_table = len(cell_rows) >= 2 and len(cell_rows[0]) >= 2
    return normalized, has_table


def _normalize_structured_cell(value: str) -> str:
    return re.sub(r"[\t\r\n ]+", " ", value.replace("\x00", "")).strip()


def _normalize_plain_source(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _bounded_text_blocks(value: str, limit: int) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(value):
        end = min(cursor + limit, len(value))
        if end < len(value):
            search_floor = cursor + limit // 2
            boundary = max(
                value.rfind("\n\n", search_floor, end),
                value.rfind("\n", search_floor, end),
                value.rfind(" ", search_floor, end),
            )
            if boundary > cursor:
                end = boundary
        raw = value[cursor:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = cursor + leading
        trimmed_end = cursor + trailing
        if trimmed_end > start:
            blocks.append((start, trimmed_end, value[start:trimmed_end]))
        cursor = end
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
    return blocks


def _bounded_line_blocks(value: str, limit: int) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    cursor = 0
    while cursor < len(value):
        preferred_end = min(cursor + limit, len(value))
        if preferred_end == len(value):
            end = preferred_end
        else:
            end = value.rfind("\n", cursor, preferred_end + 1)
            if end <= cursor:
                following_line_end = value.find("\n", preferred_end)
                end = len(value) if following_line_end < 0 else following_line_end
        raw = value[cursor:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = cursor + leading
        trimmed_end = cursor + trailing
        if trimmed_end > start:
            blocks.append((start, trimmed_end, value[start:trimmed_end]))
        cursor = end
        while cursor < len(value) and value[cursor] == "\n":
            cursor += 1
    return blocks


def _uncertainty_shape_is_valid(completion: dict[str, Any]) -> bool:
    status = completion.get("status")
    claims = completion["claims"]
    passages = completion["passages"]
    message = completion.get("message")
    if not isinstance(message, str) or not message.strip():
        return False
    if status in _SUPPORTED_STATUSES:
        return bool(claims)
    if status == "insufficient":
        return not claims
    if status == "evidence_retrieved":
        return not claims and bool(passages)
    if status == "coverage_limited":
        return bool(claims) or bool(completion.get("coverage_gap_reasons"))
    if status == "conflict":
        return any(
            isinstance(claim, dict) and claim.get("relation") == "conflict" for claim in claims
        )
    return False


def _required_list(mapping: dict[str, Any], *keys: str) -> list[object]:
    value = _lookup(mapping, *keys)
    if not isinstance(value, list):
        raise ValueError(f"{keys[0]} must be a list")
    return value


def _required_string(mapping: dict[str, Any], *keys: str) -> str:
    value = _lookup(mapping, *keys)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{keys[0]} must be a non-empty string")
    return value


def _optional_string(mapping: dict[str, Any], *keys: str) -> str | None:
    value = _lookup(mapping, *keys)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{keys[0]} must be null or a non-empty string")
    return value


def _required_integer(mapping: dict[str, Any], *keys: str) -> int:
    value = _lookup(mapping, *keys)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be an integer")
    return value


def _optional_integer(mapping: dict[str, Any], *keys: str) -> int | None:
    value = _lookup(mapping, *keys)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{keys[0]} must be null or an integer")
    return value


def _lookup(mapping: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise ValueError(f"response is missing {keys[0]}")


def _string_or_string_list(value: object) -> bool:
    return isinstance(value, str) or (
        isinstance(value, list) and bool(value) and all(isinstance(item, str) for item in value)
    )


def _expected_strings(ideal: dict[str, Any], key: str) -> tuple[str, ...]:
    value = ideal.get(key)
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _matches_expected(value: object, expected: tuple[str, ...]) -> bool:
    return not expected or value in expected


def _counter_contains(actual: list[str], required: list[str]) -> bool:
    actual_counts = Counter(actual)
    return all(actual_counts[value] >= count for value, count in Counter(required).items())


def _all_failed() -> dict[MetricName, bool]:
    return {
        "answer_accuracy": False,
        "citation_integrity": False,
        "pass_rate": False,
        "policy_compliance": False,
        "uncertainty_handling": False,
    }
