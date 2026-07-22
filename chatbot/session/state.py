"""Serializable state for guided navigation, leads, and ActiveFlow tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StateModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Focus(StateModel):
    university_concept: str | None = None
    course_concept: str | None = None
    specialization_concept: str | None = None
    university: str | None = None
    category: str | None = None
    specialization: str | None = None
    entity_id: str | None = None

    def clear(self) -> None:
        self.university_concept = None
        self.course_concept = None
        self.specialization_concept = None
        self.university = None
        self.category = None
        self.specialization = None
        self.entity_id = None

class LeadState(StateModel):
    name: str | None = None
    phone: str | None = None
    conversion_recorded: bool = False


class NavigationStep(StrEnum):
    """Authoritative guided-widget position.

    The values are transport-safe strings so the same state can be persisted in
    Redis and mirrored by the dependency-free widget without another mapping.
    """

    HOMEPAGE = "homepage"
    UNIVERSITY_PICKER = "university_picker"
    UNIVERSITY_CARD = "university_card"
    COURSE_PICKER = "course_picker"
    COURSE_CARD = "course_card"
    SPECIALIZATION_PICKER = "specialization_picker"
    SPECIALIZATION_CARD = "specialization_card"
    FEES = "fees"
    ELIGIBILITY = "eligibility"
    CAREERS = "careers"
    APPROVALS = "approvals"
    REVIEWS = "reviews"
    SYLLABUS = "syllabus"
    ADMISSIONS = "admissions"
    VALIDITY = "validity"
    COMPARISON = "comparison"
    TOOL = "tool"
    LEAD_CAPTURE = "lead_capture"


class NavigationState(StateModel):
    """Single source of truth for funnel depth, context, and completed chips."""

    step: NavigationStep = NavigationStep.HOMEPAGE
    page_type: str = "homepage"
    surface: str = "page:home"
    current_node: str = "page:home"
    entity_id: str | None = None
    university_id: str | None = None
    course_id: str | None = None
    specialization_id: str | None = None
    interaction_count: int = Field(default=0, ge=0)
    completed_actions: list[str] = Field(default_factory=list)
    config_version: str = ""

    def mark_completed(self, chip_id: str | None) -> bool:
        value = " ".join(str(chip_id or "").split())
        if not value or value in self.completed_actions:
            return False
        self.completed_actions.append(value)
        return True


class ActiveFlow(StateModel):
    """Persisted multi-step guided tool state."""

    tool: Literal["roi", "career_quiz", "scholarship"]
    step: str
    answers: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    version: str = ""


class ConversationState(StateModel):
    session_id: str
    focus: Focus = Field(default_factory=Focus)
    lead: LeadState = Field(default_factory=LeadState)
    navigation: NavigationState = Field(default_factory=NavigationState)
    active_flow: ActiveFlow | None = None
    tool_attempts: dict[str, int] = Field(default_factory=dict)
    # Full catalog envelopes already used by this session. This keeps persistence
    # self-contained when a backing catalog is refreshed between turns.
    entity_cache: dict[str, dict[str, Any]] = Field(default_factory=dict)

SessionState = ConversationState


__all__ = [
    "ActiveFlow",
    "ConversationState",
    "Focus",
    "LeadState",
    "NavigationState",
    "NavigationStep",
    "SessionState",
]
