"""Application settings, loaded from ``JOBSIGNAL_*`` env vars or a local ``.env`` file."""

from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOBSIGNAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///jobsignal.db"
    log_level: LogLevel = "INFO"
    # API: a key is REQUIRED to bind beyond localhost; never logged or echoed.
    api_key: SecretStr | None = None
    api_cors_origins: str = ""  # comma-separated origins; empty = CORS off
    # Dashboard: where the read-only API lives (http/https only)
    api_url: str = "http://127.0.0.1:8000"

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("api_url")
    @classmethod
    def _require_http_api_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.lower().startswith(("http://", "https://")) or value[-3:] == "://":
            raise ValueError("api_url must be an http:// or https:// URL")
        return value

    @field_validator("database_url")
    @classmethod
    def _require_database_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("database_url must not be blank")
        return value.strip()


def get_settings() -> Settings:
    """Build settings fresh from the current environment."""
    return Settings()
