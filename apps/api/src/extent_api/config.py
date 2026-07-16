"""Runtime settings loaded only at the API process boundary."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from extent_api.security import CredentialKeyring

_EXACT_HOST = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)

# Resolve the developer dotenv from the repository, not from the process CWD.
# Environment variables retain pydantic-settings' higher precedence, so deployed
# processes remain environment-driven even when a checkout happens to contain a
# local dotenv file.
REPOSITORY_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


def _normalize_http_origin(value: str, *, field_name: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field_name} must contain http(s) origins without paths")
    return normalized


def _normalize_exact_host(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if not _EXACT_HOST.fullmatch(normalized):
        raise ValueError("allowed_hosts must contain exact DNS hostnames or IPv4 addresses")
    return normalized


class Settings(BaseSettings):
    """Non-secret defaults; deployed secrets are supplied through the environment."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        env_prefix="EXTENT_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    allowed_origins: str = Field(default="http://localhost:3000", min_length=1)
    api_title: str = "Extent API"
    database_url: str = Field(
        default="postgresql+psycopg://extent:extent@127.0.0.1:5432/extent",
        min_length=1,
        repr=False,
    )
    database_migration_url: str | None = Field(default=None, min_length=1, repr=False)
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", min_length=1, repr=False)
    queue_name: str = Field(default="extent", min_length=1, max_length=64)
    public_web_origin: str = "http://localhost:3000"
    google_client_id: SecretStr | None = Field(default=None, repr=False)
    google_client_secret: SecretStr | None = Field(default=None, repr=False)
    credential_encryption_keys: SecretStr | None = Field(default=None, repr=False)
    model_api_key: SecretStr | None = Field(default=None, repr=False)
    model_base_url: str = "https://api.openai.com/v1"
    model_name: str = Field(default="gpt-5-mini", min_length=1, max_length=160)
    embedding_api_key: SecretStr | None = Field(default=None, repr=False)
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = Field(default="text-embedding-3-large", min_length=1, max_length=160)
    model_timeout_seconds: int = Field(default=120, ge=10, le=180)
    ocr_executable: str = Field(default="tesseract", min_length=1, max_length=1_024)
    query_requests_per_minute: int = Field(default=12, ge=1, le=120)
    oauth_attempt_ttl_seconds: int = Field(default=600, ge=300, le=900)
    session_ttl_seconds: int = Field(default=604_800, ge=3_600, le=2_592_000)
    session_cookie_name: str = Field(
        default="extent_session", pattern=r"^[a-z][a-z0-9_]{2,63}$"
    )

    def __init__(self, **values: Any) -> None:
        # `_env_file` is a BaseSettings construction option rather than a model
        # field. Keeping it overridable lets tests use a synthetic dotenv and
        # guarantees no test needs to inspect the repository's real one.
        values.setdefault("_env_file", REPOSITORY_ENV_FILE)
        super().__init__(**values)

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def require_psycopg_postgres(cls, value: str | None) -> str | None:
        """Reject database URLs that bypass the supported Postgres driver."""

        if value is not None and not value.startswith("postgresql+psycopg://"):
            raise ValueError("database URLs must use postgresql+psycopg")
        return value

    @field_validator("redis_url")
    @classmethod
    def require_redis_url(cls, value: str) -> str:
        """Accept only Redis URLs supported by Render Key Value and local Compose."""

        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use redis:// or rediss://")
        return value

    @field_validator("public_web_origin")
    @classmethod
    def normalize_public_web_origin(cls, value: str) -> str:
        return _normalize_http_origin(value, field_name="public_web_origin")

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_allowed_hosts(cls, value: str) -> str:
        hosts = [_normalize_exact_host(host) for host in value.split(",") if host.strip()]
        if not hosts:
            raise ValueError("allowed_hosts must contain at least one host")
        if len(hosts) > 10:
            raise ValueError("allowed_hosts cannot contain more than ten hosts")
        if len(set(hosts)) != len(hosts):
            raise ValueError("allowed_hosts cannot contain duplicate hosts")
        return ",".join(hosts)

    @field_validator("allowed_origins")
    @classmethod
    def normalize_allowed_origins(cls, value: str) -> str:
        origins = [
            _normalize_http_origin(origin, field_name="allowed_origins")
            for origin in value.split(",")
            if origin.strip()
        ]
        if not origins:
            raise ValueError("allowed_origins must contain at least one origin")
        if len(origins) > 10:
            raise ValueError("allowed_origins cannot contain more than ten origins")
        if len(set(origins)) != len(origins):
            raise ValueError("allowed_origins cannot contain duplicate origins")
        return ",".join(origins)

    @field_validator(
        "google_client_id",
        "google_client_secret",
        "credential_encryption_keys",
        "model_api_key",
        "embedding_api_key",
    )
    @classmethod
    def reject_empty_secrets(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("configured secrets cannot be empty")
        return value

    @field_validator("ocr_executable")
    @classmethod
    def normalize_ocr_executable(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("ocr_executable cannot be empty")
        return normalized

    @field_validator("credential_encryption_keys")
    @classmethod
    def validate_credential_keyring(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            CredentialKeyring.from_config(value.get_secret_value())
        return value

    @field_validator("model_base_url", "embedding_base_url")
    @classmethod
    def require_https_provider_base_url(cls, value: str) -> str:
        parsed = urlsplit(value.rstrip("/"))
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("provider base URLs must use HTTPS without credentials")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_origin_capacity(self) -> "Settings":
        if len(self.cors_origins) > 10:
            raise ValueError("configured CORS origins exceed the ten-origin boundary")
        return self

    def require_runtime_capabilities(self) -> None:
        if self.environment != "production":
            return
        if not self.public_web_origin.startswith("https://"):
            raise ValueError("production public_web_origin must use https")
        if self.cors_origins != [self.public_web_origin]:
            raise ValueError("production allowed_origins must equal public_web_origin")
        if any(host in {"localhost", "127.0.0.1", "testserver"} for host in self.trusted_hosts):
            raise ValueError("production allowed_hosts cannot contain local or test hosts")
        missing = [
            name
            for name, value in (
                ("google_client_id", self.google_client_id),
                ("google_client_secret", self.google_client_secret),
                ("credential_encryption_keys", self.credential_encryption_keys),
                ("model_api_key", self.model_api_key),
                ("embedding_api_key", self.embedding_api_key),
            )
            if value is None
        ]
        if missing:
            raise ValueError(f"production requires {', '.join(missing)}")
        for field_name, url in (
            ("database_url", self.database_url),
            ("redis_url", self.redis_url),
        ):
            if urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError(f"production {field_name} cannot use a loopback host")

    @property
    def migration_database_url(self) -> str:
        """Prefer a direct release connection for migration DDL when supplied."""

        return self.database_migration_url or self.database_url

    @property
    def cors_origins(self) -> list[str]:
        """Return a bounded, normalized origin list for local direct-API development."""

        origins = self.allowed_origins.split(",")
        if self.public_web_origin not in origins:
            origins.append(self.public_web_origin)
        return origins

    @property
    def trusted_hosts(self) -> list[str]:
        """Return exact Host-header values admitted by the ASGI edge."""

        return self.allowed_hosts.split(",")

    @property
    def google_oauth_configured(self) -> bool:
        return all(
            value is not None
            for value in (
                self.google_client_id,
                self.google_client_secret,
                self.credential_encryption_keys,
            )
        )

    @property
    def model_api_configured(self) -> bool:
        return self.model_api_key is not None

    @property
    def embedding_api_configured(self) -> bool:
        return self.embedding_api_key is not None

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.public_web_origin}/api/backend/v1/auth/google/callback"

    @property
    def connect_url(self) -> str:
        return f"{self.public_web_origin}/connect"

    @property
    def session_cookie_secure(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
