"""Focused tests for deterministic complete-set and structured analysis."""

from uuid import UUID

from extent_api.database.query_repository import RetrievedBlock
from extent_api.query_models import EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT
from extent_api.services.exhaustive_extraction import (
    ExhaustiveRequest,
    ExhaustiveRequestNeedsClarification,
    extract_values,
    parse_exhaustive_request,
)
from extent_api.services.query_planning import plan_query
from extent_api.services.structured_analysis import analyze_structured_question

RUN_ID = UUID("30000000-0000-4000-8000-000000000001")


def _block(
    text: str,
    *,
    index: int = 1,
    line_start: int = 1,
    name: str = "records.csv",
) -> RetrievedBlock:
    return RetrievedBlock(
        block_id=UUID(int=index),
        drive_file_id=f"drive-{index}",
        line_start_one_based=line_start,
        origin_kind="text_lines",
        page_index_zero_based=None,
        path=("Evidence", name),
        printed_page_label=None,
        source_name=name,
        source_file_id=UUID(int=10_000 + index),
        text=text,
        pipeline_version="csv-record-v1",
    )


def _request(question: str) -> ExhaustiveRequest:
    decision = parse_exhaustive_request(question)
    assert isinstance(decision, ExhaustiveRequest)
    return decision


def _analyze(question: str, blocks: list[RetrievedBlock]):
    return analyze_structured_question(
        blocks,
        idempotency_key="question-1",
        plan=plan_query(question),
        question=question,
        run_id=RUN_ID,
    )


def test_planner_keeps_scalar_questions_direct_and_routes_set_wide_work() -> None:
    assert plan_query("What is the total limit?").mode == "direct"
    assert plan_query("Count all records by status").requires_complete_data
    assert plan_query("Does every record have an owner?").requires_complete_data
    breakdown = plan_query("Break down commitments by state and owner")
    assert breakdown.mode == "structured"
    assert set(breakdown.intents) >= {"aggregate", "group"}


def test_structured_aggregation_scans_all_rows_and_keeps_units() -> None:
    result = _analyze(
        "Total amount by region across all records",
        [
            _block(
                "Record\tRegion\tAmount\n"
                "A-1\tNorth\t$10.25\nA-2\tNorth\t$4.75\nA-3\tSouth\t$7.50"
            )
        ],
    )

    assert result.complete
    assert result.examined_rows == 3
    assert [claim.value for claim in result.claims] == ["15 USD", "7.5 USD"]
    assert len(result.audits) == 3


def test_malformed_structured_row_prevents_a_complete_claim() -> None:
    result = _analyze(
        "Does every record have a value?",
        [_block("Record\tValue\nA-1\t1\nmalformed\nA-2\t2")],
    )

    assert not result.complete
    assert result.malformed_rows == 1
    assert result.claims == ()
    assert "cannot be verified" in result.message


def test_complete_set_parser_requires_one_explicit_field_command() -> None:
    parsed = parse_exhaustive_request("List every project owner")
    ambiguous = parse_exhaustive_request("List every owner and status")
    ordinary = parse_exhaustive_request("What is the total budget?")

    assert isinstance(parsed, ExhaustiveRequest)
    assert parsed.normalized_target == "project owner"
    assert isinstance(ambiguous, ExhaustiveRequestNeedsClarification)
    assert ordinary is None


def test_complete_set_table_preserves_values_and_exact_row_context() -> None:
    text = (
        "Project | Owner | Status\n"
        "--- | --- | ---\n"
        "Atlas | Alice Chen | Active\n"
        "Borealis | Bob Singh | Paused"
    )
    result = extract_values(
        [_block(text, line_start=20)],
        idempotency_key="question-1",
        request=_request("List all project owners"),
        run_id=RUN_ID,
    )

    assert result.ambiguous_count == 0
    assert [claim.value for claim in result.claims] == ["Alice Chen", "Bob Singh"]
    assert result.claims[0].citations[0].exact_quote.endswith("Atlas | Alice Chen | Active")


def test_ambiguous_undivided_grid_abstains_instead_of_guessing() -> None:
    result = extract_values(
        [_block("Owner | Status\nAlice Chen | Active")],
        idempotency_key="question-1",
        request=_request("List every owner"),
        run_id=RUN_ID,
    )

    assert result.claims == ()
    assert result.ambiguous_count == 1


def test_complete_set_overflow_returns_no_truncated_claim_list() -> None:
    lines = [
        f"Invoice number: INV-{index:04d}"
        for index in range(1, EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT + 2)
    ]
    result = extract_values(
        [_block("\n".join(lines))],
        idempotency_key="question-1",
        request=_request("List every invoice number"),
        run_id=RUN_ID,
    )

    assert result.overflowed
    assert result.unique_count == EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT + 1
    assert result.claims == ()
