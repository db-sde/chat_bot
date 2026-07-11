"""Serializable conversation state and focus tracking models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StateModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Focus(StateModel):
    university: str | None = None
    category: str | None = None
    specialization: str | None = None
    entity_id: str | None = None

    def clear(self) -> None:
        self.university = None
        self.category = None
        self.specialization = None
        self.entity_id = None


class PendingClarification(StateModel):
    candidates: list[str] = Field(default_factory=list)
    slot_type: Literal["university", "course", "specialization"] | None = None
    asked_at_turn: int | None = Field(default=None, ge=0)


class LeadState(StateModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    last_asked_field: Literal["name", "phone", "email"] | None = None


class ConversationState(StateModel):
    session_id: str
    focus: Focus = Field(default_factory=Focus)
    pending_clarification: PendingClarification | None = None
    lead: LeadState = Field(default_factory=LeadState)
    turn_count: int = Field(default=0, ge=0)
    history: list[dict[str, Any]] = Field(default_factory=list)
    # Full catalog envelopes already used by this session. This keeps persistence
    # self-contained when a backing catalog is refreshed between turns.
    entity_cache: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def append_history(
        self,
        role: Literal["user", "assistant", "system"],
        content: str,
        *,
        limit: int = 12,
    ) -> None:
        """Append a message and retain only the configured rolling window."""

        self.history.append({"role": role, "content": content})
        if limit > 0 and len(self.history) > limit:
            del self.history[:-limit]


SessionState = ConversationState

