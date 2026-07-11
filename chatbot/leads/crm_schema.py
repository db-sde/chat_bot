"""Versioned CRM event contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CRMLeadEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    event: Literal["lead.updated"] = "lead.updated"
    source: Literal["degreebaba_chatbot"] = "degreebaba_chatbot"
    session_id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    captured_fields: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
