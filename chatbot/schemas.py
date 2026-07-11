"""Shared transport and domain schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PageType = Literal["university", "course", "specialization"]
SlotType = Literal["university", "course", "specialization"]
Intent = Literal["factual", "comparison", "advisory", "discovery", "chitchat"]
Confidence = Literal["HIGH", "MEDIUM"]


class TransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(TransportModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class CTA(TransportModel):
    label: str
    action: str = "start_lead_capture"
    url: str | None = None
    payload: dict[str, Any] | None = None


class ResponsePayload(TransportModel):
    text: str
    suggested_chips: list[str] = Field(default_factory=list)
    cta: CTA | None = None


class ChatResponse(ResponsePayload):
    session_id: str | None = None


class HealthResponse(TransportModel):
    status: Literal["ok", "degraded"]
    dependencies: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None


class ReindexResponse(TransportModel):
    status: Literal["ok"] = "ok"
    entity_count: int = Field(ge=0)


# Older callers used this name; keeping it avoids needless coupling between layers.
Response = ResponsePayload
