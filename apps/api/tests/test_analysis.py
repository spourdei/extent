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


def test_planner_recognizes_grouped_counts_and_explicit_ordering() -> None:
    grouped = plan_query(
        "For each location, show the number of activities and total net amount."
    )
    assert grouped.mode == "structured"
    assert set(grouped.intents) >= {"aggregate", "group"}

    ordered = plan_query(
        "List commitments due on or after August 1, 2026, ordered by due date."
    )
    assert ordered.mode == "structured"
    assert set(ordered.intents) >= {"filter", "list", "order"}
    assert "group" not in ordered.intents


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


def test_grouped_breakdown_executes_count_and_multiple_sums() -> None:
    result = _analyze(
        "Break down the activity records by tax rate, including row count, net "
        "amount, and gross amount.",
        [
            _block(
                "Activity_ID\tTax_Rate\tNet_Amount\tGross_Amount\n"
                "A-1\t0.05\t100\t105\nA-2\t0.05\t50\t52.5\n"
                "A-3\t0.13\t200\t226"
            )
        ],
    )

    assert result.complete
    assert result.examined_rows == 3
    assert {claim.text for claim in result.claims} == {
        "Count for Tax_Rate 0.05 is 2.",
        "Sum Net_Amount for Tax_Rate 0.05 is 150.",
        "Sum Gross_Amount for Tax_Rate 0.05 is 157.5.",
        "Count for Tax_Rate 0.13 is 1.",
        "Sum Net_Amount for Tax_Rate 0.13 is 200.",
        "Sum Gross_Amount for Tax_Rate 0.13 is 226.",
    }


def test_for_each_executes_grouped_count_and_sum() -> None:
    result = _analyze(
        "For each location, show the number of activities and total net amount.",
        [
            _block(
                "Activity_ID\tLocation\tNet_Amount\n"
                "A-1\tNorth\t10\nA-2\tNorth\t15\nA-3\tSouth\t7"
            )
        ],
    )

    assert result.complete
    assert {claim.text for claim in result.claims} == {
        "Count for Location North is 2.",
        "Sum Net_Amount for Location North is 25.",
        "Count for Location South is 1.",
        "Sum Net_Amount for Location South is 7.",
    }


def test_natural_date_filter_and_explicit_sort_are_both_executed() -> None:
    result = _analyze(
        "List commitments due on or after August 1, 2026, ordered by due date.",
        [
            _block(
                "Commitment_ID\tStart_Date\tDue_Date\n"
                "C-3\t2026-07-01\t2026-09-10\n"
                "C-0\t2026-06-01\t2026-07-31\n"
                "C-1\t2026-07-05\t2026-08-01\n"
                "C-2\t2026-07-08\t2026-08-15"
            )
        ],
    )

    assert result.complete
    assert result.examined_rows == 4
    assert result.matched_rows == 3
    assert [claim.citations[0].exact_quote.split("\t")[0] for claim in result.claims] == [
        "C-1",
        "C-2",
        "C-3",
    ]


def test_requested_filter_fails_closed_when_value_cannot_be_typed() -> None:
    result = _analyze(
        "List commitments due on or after someday",
        [_block("Commitment_ID\tDue_Date\nC-1\t2026-08-01")],
    )

    assert result.status == "unsupported"
    assert result.claims == ()
    assert "incompatible" in result.message


def test_count_filter_columns_are_not_inferred_as_sum_metrics() -> None:
    result = _analyze(
        "Count all records where actual units are below planned units",
        [_block("Record_ID\tPlanned_Units\tActual_Units\nR-1\t10\t8\nR-2\t5\t5\nR-3\t4\t2")],
    )

    assert result.complete
    assert [claim.text for claim in result.claims] == ["Count is 2."]


def test_same_field_range_executes_both_bounds() -> None:
    result = _analyze(
        "List records where score is at least 10 and score is at most 20",
        [_block("Record_ID\tScore\nR-1\t9\nR-2\t10\nR-3\t20\nR-4\t25")],
    )

    assert result.complete
    assert result.matched_rows == 2
    assert [claim.citations[0].exact_quote.split("\t")[0] for claim in result.claims] == [
        "R-2",
        "R-3",
    ]


def test_compound_date_and_text_filters_are_both_required() -> None:
    result = _analyze(
        "List records due on or after August 1, 2026 with status Open",
        [
            _block(
                "Record_ID\tDue_Date\tStatus\n"
                "R-1\t2026-08-01\tOpen\nR-2\t2026-08-02\tClosed\n"
                "R-3\t2026-07-31\tOpen"
            )
        ],
    )

    assert result.complete
    assert result.matched_rows == 1
    assert result.claims[0].citations[0].exact_quote.startswith("R-1\t")


def test_multiple_metric_operations_bind_to_adjacent_fields() -> None:
    result = _analyze(
        "For each region show average score and total cost",
        [
            _block(
                "Record_ID\tRegion\tScore\tCost\n"
                "R-1\tNorth\t10\t5\nR-2\tNorth\t20\t7\nR-3\tSouth\t6\t4"
            )
        ],
    )

    assert result.complete
    assert {claim.text for claim in result.claims} == {
        "Average Score for Region North is 15.",
        "Sum Cost for Region North is 12.",
        "Average Score for Region South is 6.",
        "Sum Cost for Region South is 4.",
    }


def test_group_phrase_stops_before_requested_metrics_without_comma() -> None:
    result = _analyze(
        "For each location show the number of activities and total net amount",
        [
            _block(
                "Activity_ID\tLocation\tNet_Amount\n"
                "A-1\tNorth\t10\nA-2\tNorth\t15\nA-3\tSouth\t7"
            )
        ],
    )

    assert result.complete
    assert len(result.claims) == 4
    assert all("Net_Amount" not in claim.text.split(" for ")[-1] for claim in result.claims)


def test_missing_requested_projection_fails_closed() -> None:
    result = _analyze(
        "List record ID and risk score for every record",
        [_block("Record_ID\tStatus\nR-1\tOpen\nR-2\tClosed")],
    )

    assert result.status == "unsupported"
    assert result.claims == ()
    assert "output field" in result.message
