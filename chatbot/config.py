"""Application configuration loaded from environment variables.

All settings have safe development defaults. API keys and external service URLs are
optional so the deterministic catalog path remains usable while dependencies are down.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the DegreeBaba chatbot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "DegreeBaba Chatbot"
    app_env: str = "development"
    log_level: str = "INFO"
    log_format: str = "text"
    log_include_pii: bool = False
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    catalog_url: str | None = None
    catalog_path: Path | None = None
    catalog_timeout_seconds: float = Field(default=5.0, gt=0)
    widget_config_path: Path | None = None
    chip_map_path: Path | None = None
    tools_content_path: Path | None = None
    widget_allowed_origins: str = "*"

    @field_validator("catalog_url", "analytics_webhook_url", mode="before")
    @classmethod
    def _blank_url_is_none(cls, value: object) -> object:
        """Treat ``CATALOG_URL=`` (blank) as unset rather than an empty string."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "catalog_path",
        "widget_config_path",
        "chip_map_path",
        "tools_content_path",
        mode="before",
    )
    @classmethod
    def _blank_path_is_none(cls, value: object) -> object:
        """Treat blank optional filesystem paths as unset.

        Without this, Pydantic coerces '' to Path('.'), which is a directory,
        causing a silent load failure or an unintended configuration lookup.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    redis_url: str | None = None
    redis_key_prefix: str = "degreebaba:session:"
    redis_timeout_seconds: float = Field(default=1.0, gt=0)
    session_ttl_seconds: int = Field(default=30 * 60, ge=1)
    crm_webhook_url: str | None = None
    crm_webhook_secret: str | None = None
    webhook_timeout_seconds: float = Field(default=5.0, gt=0)
    dead_letter_path: Path = Path("var/lead_dead_letters.jsonl")
    analytics_webhook_url: str | None = None
    analytics_webhook_secret: str | None = None
    analytics_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    analytics_dead_letter_path: Path = Path("var/analytics_dead_letters.jsonl")
    analytics_queue_size: int = Field(default=2_048, ge=16, le=100_000)
    admin_api_key: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()


settings = get_settings()
