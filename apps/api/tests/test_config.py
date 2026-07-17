"""Focused settings tests for deployed database connection strings."""

import pytest
from pydantic import ValidationError

from extent_api.config import Settings


def test_database_settings_normalize_platform_connection_strings() -> None:
    settings = Settings(
        database_url="postgresql://runtime-pool/extent",
        database_migration_url="postgresql://direct-session/extent",
    )

    assert settings.database_url == "postgresql+psycopg://runtime-pool/extent"
    assert settings.migration_database_url == "postgresql+psycopg://direct-session/extent"


def test_database_settings_reject_unsupported_drivers() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings(database_url="sqlite:///extent.db")
