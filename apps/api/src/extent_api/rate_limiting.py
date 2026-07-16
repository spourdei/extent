"""Atomic Redis admission for bounded authenticated question traffic."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError

_WINDOW_SECONDS = 60
_COUNTER_TTL_SECONDS = _WINDOW_SECONDS * 2
_INCREMENT_WITH_EXPIRY = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class QueryRateExceeded(RuntimeError):
    def __init__(self, *, retry_after_seconds: int) -> None:
        if not 1 <= retry_after_seconds <= _WINDOW_SECONDS:
            raise ValueError("retry_after_seconds must be between 1 and 60")
        super().__init__("question rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class QueryRateLimitUnavailable(RuntimeError):
    pass


class QueryRateLimiter(Protocol):
    def consume(self, *, now: datetime, user_id: UUID) -> None: ...


class RedisQueryRateLimiter:
    """Consume one permit from a per-user fixed UTC minute window."""

    def __init__(self, connection: Redis, *, requests_per_minute: int) -> None:
        if not 1 <= requests_per_minute <= 120:
            raise ValueError("requests_per_minute must be between 1 and 120")
        self._connection = connection
        self._requests_per_minute = requests_per_minute

    def consume(self, *, now: datetime, user_id: UUID) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("rate-limit time must include a UTC offset")
        epoch_seconds = int(now.timestamp())
        window = epoch_seconds // _WINDOW_SECONDS
        key = f"extent:question-rate:{window}:{user_id}"
        try:
            count = self._connection.eval(
                _INCREMENT_WITH_EXPIRY,
                1,
                key,
                _COUNTER_TTL_SECONDS,
            )
        except RedisError as error:
            raise QueryRateLimitUnavailable("question rate limiter is unavailable") from error
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise QueryRateLimitUnavailable("question rate limiter returned an invalid count")
        if count > self._requests_per_minute:
            raise QueryRateExceeded(
                retry_after_seconds=_WINDOW_SECONDS - (epoch_seconds % _WINDOW_SECONDS)
            )
