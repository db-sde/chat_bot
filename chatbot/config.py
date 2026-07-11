"""Application configuration loaded from environment variables.

All settings have safe development defaults. API keys and external service URLs are
optional so the deterministic catalog path remains usable while dependencies are down.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    catalog_url: str | None = None
    catalog_path: Path | None = None
    catalog_timeout_seconds: float = Field(default=5.0, gt=0)

    redis_url: str | None = None
    redis_key_prefix: str = "degreebaba:session:"
    redis_timeout_seconds: float = Field(default=1.0, gt=0)
    session_ttl_seconds: int = Field(default=30 * 60, ge=1)
    history_limit: int = Field(default=12, ge=1, le=100)
    session_history_limit: int = Field(default=12, ge=1, le=100)

    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-8b-instant"
    groq_intent_model: str = "llama-3.1-8b-instant"
    groq_synthesis_model: str = "llama-3.3-70b-versatile"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_synthesis_model: str = "gpt-4.1-mini"
    intent_timeout_seconds: float = Field(default=2.5, gt=0)
    synthesis_timeout_seconds: float = Field(default=5.0, gt=0)
    llm_failure_threshold: int = Field(default=3, ge=1)
    llm_failure_window_seconds: int = Field(default=60, ge=1)
    llm_cooldown_seconds: int = Field(default=60, ge=1)
    llm_intent_timeout_seconds: float = Field(default=2.5, gt=0)
    llm_synthesis_timeout_seconds: float = Field(default=5.0, gt=0)
    llm_circuit_failure_threshold: int = Field(default=3, ge=1)
    llm_circuit_cooldown_seconds: float = Field(default=30.0, gt=0)

    crm_webhook_url: str | None = None
    crm_webhook_secret: str | None = None
    webhook_timeout_seconds: float = Field(default=5.0, gt=0)
    lead_nudge_after_turns: int = Field(default=3, ge=0)
    dead_letter_path: Path = Path("var/lead_dead_letters.jsonl")
    lead_prompt_after_turn: int = Field(default=3, ge=0)
    lead_prompt_interval: int = Field(default=2, ge=1)

    admin_api_key: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()


settings = get_settings()
