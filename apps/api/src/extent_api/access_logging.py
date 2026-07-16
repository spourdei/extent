"""Redact OAuth callback query parameters before Uvicorn formats access logs."""

from __future__ import annotations

import logging
from typing import Any

_CALLBACK_PATH = "/api/v1/auth/google/callback"


class OAuthCallbackQueryFilter(logging.Filter):
    """Keep request metadata while removing short-lived codes and state values."""

    def filter(self, record: logging.LogRecord) -> bool:
        arguments: Any = record.args
        if not isinstance(arguments, tuple) or len(arguments) < 5:
            return True
        full_path = arguments[2]
        if isinstance(full_path, str) and full_path.startswith(f"{_CALLBACK_PATH}?"):
            redacted = list(arguments)
            redacted[2] = f"{_CALLBACK_PATH}?[redacted]"
            record.args = tuple(redacted)
        return True


def install_oauth_access_log_redaction() -> None:
    """Install once after Uvicorn configures its dedicated access handlers."""

    for handler in logging.getLogger("uvicorn.access").handlers:
        if not any(isinstance(item, OAuthCallbackQueryFilter) for item in handler.filters):
            handler.addFilter(OAuthCallbackQueryFilter())
