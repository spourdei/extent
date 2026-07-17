"""Tests for the durable-to-public source-state boundary."""

import pytest
from pydantic import ValidationError

from extent_api.source_states import (
    PUBLISHED_RUN_STATUSES,
    derive_terminal_run_status,
    parse_internal_source_status,
    project_source_status,
)


def test_published_run_statuses_are_a_closed_vocabulary() -> None:
    assert {"ready", "partial", "failed"} == PUBLISHED_RUN_STATUSES


@pytest.mark.parametrize(
    ("internal", "public"),
    [
        ("discovered", "queued"),
        ("admitted", "queued"),
        ("downloading", "parsing"),
        ("parsed", "parsing"),
        ("embedding", "parsing"),
        ("ready", "ready"),
        ("retryable_failed", "failed"),
        ("terminal_failed", "failed"),
        ("unsupported", "unsupported"),
        ("capped", "capped"),
    ],
)
def test_each_internal_source_state_has_one_public_projection(
    internal: str, public: str
) -> None:
    assert project_source_status(parse_internal_source_status(internal)) == public


def test_unknown_persisted_source_state_fails_validation() -> None:
    with pytest.raises(ValidationError):
        parse_internal_source_status("failed")


@pytest.mark.parametrize(
    ("statuses", "has_coverage_gaps", "expected"),
    [
        ([], False, "failed"),
        (["terminal_failed"], True, "failed"),
        (["ready"], False, "ready"),
        (["ready"], True, "partial"),
        (["ready", "unsupported"], True, "partial"),
    ],
)
def test_terminal_status_is_derived_from_resolved_sources(
    statuses: list[str], has_coverage_gaps: bool, expected: str
) -> None:
    parsed = [parse_internal_source_status(status) for status in statuses]

    assert derive_terminal_run_status(parsed, has_coverage_gaps=has_coverage_gaps) == expected


@pytest.mark.parametrize("status", ["admitted", "downloading", "embedding"])
def test_unresolved_sources_cannot_publish_a_terminal_run(status: str) -> None:
    with pytest.raises(ValueError, match="resolved source manifest"):
        derive_terminal_run_status(
            [parse_internal_source_status(status)], has_coverage_gaps=False
        )
