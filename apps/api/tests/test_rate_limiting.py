"""Focused proof for atomic authenticated question admission."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from redis import Redis
from redis.exceptions import RedisError

from extent_api.rate_limiting import (
    QueryRateExceeded,
    QueryRateLimitUnavailable,
    RedisQueryRateLimiter,
)

NOW = datetime(2026, 7, 17, 14, 0, tzinfo=UTC)
USER_ID = UUID("10000000-0000-4000-8000-000000000001")


def test_atomic_counter_admits_through_the_configured_limit() -> None:
    connection = MagicMock(spec=Redis)
    connection.eval.return_value = 12
    limiter = RedisQueryRateLimiter(connection, requests_per_minute=12)

    limiter.consume(now=NOW, user_id=USER_ID)

    arguments = connection.eval.call_args.args
    assert arguments[1:] == (
        1,
        f"extent:question-rate:{int(NOW.timestamp()) // 60}:{USER_ID}",
        120,
    )


def test_counter_rejects_above_the_limit_with_a_bounded_retry_delay() -> None:
    connection = MagicMock(spec=Redis)
    connection.eval.return_value = 13
    limiter = RedisQueryRateLimiter(connection, requests_per_minute=12)

    with pytest.raises(QueryRateExceeded) as error:
        limiter.consume(now=NOW, user_id=USER_ID)

    assert error.value.retry_after_seconds == 60


@pytest.mark.parametrize("response", [None, True, 0, "1"])
def test_invalid_redis_counter_response_fails_closed(response: object) -> None:
    connection = MagicMock(spec=Redis)
    connection.eval.return_value = response
    limiter = RedisQueryRateLimiter(connection, requests_per_minute=12)

    with pytest.raises(QueryRateLimitUnavailable):
        limiter.consume(now=NOW, user_id=USER_ID)


def test_redis_failure_does_not_bypass_question_admission() -> None:
    connection = MagicMock(spec=Redis)
    connection.eval.side_effect = RedisError("unavailable")
    limiter = RedisQueryRateLimiter(connection, requests_per_minute=12)

    with pytest.raises(QueryRateLimitUnavailable):
        limiter.consume(now=NOW, user_id=USER_ID)


def test_rate_limit_time_must_be_timezone_aware() -> None:
    limiter = RedisQueryRateLimiter(MagicMock(spec=Redis), requests_per_minute=12)

    with pytest.raises(ValueError, match="UTC offset"):
        limiter.consume(now=datetime(2026, 7, 17, 14, 0), user_id=USER_ID)
