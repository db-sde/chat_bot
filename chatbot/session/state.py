"""Serializable conversation state and focus tracking models."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StateModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


FocusSource = Literal["explicit", "context", "inferred"]
FocusSlot = Literal["university", "course", "specialization", "attribute"]


class Focus(StateModel):
    # Concept-first fields. These are additive while persisted sessions and the
    # existing handlers migrate away from the legacy ID-backed fields below.
    university_concept: str | None = None
    course_concept: str | None = None
    specialization_concept: str | None = None
    attribute: str | None = None
    source: FocusSource | None = None
    sources: dict[FocusSlot, FocusSource] = Field(
        default_factory=dict,
        exclude_if=lambda value: not value,
    )
    unknown_entities: list[str] = Field(
        default_factory=list,
        exclude_if=lambda value: not value,
    )

    # Backward-compatible persisted fields. ``university`` and ``entity_id`` may
    # contain catalog IDs in existing Redis sessions, while ``category`` and
    # ``specialization`` already behave like concepts in the current pipeline.
    university: str | None = None
    category: str | None = None
    specialization: str | None = None
    entity_id: str | None = None

    def clear(self) -> None:
        self.university_concept = None
        self.course_concept = None
        self.specialization_concept = None
        self.attribute = None
        self.source = None
        self.sources.clear()
        self.unknown_entities.clear()
        self.university = None
        self.category = None
        self.specialization = None
        self.entity_id = None


def _metadata_value(metadata: object, name: str) -> Any:
    if isinstance(metadata, Mapping):
        return metadata.get(name)
    return getattr(metadata, name, None)


def _clean_concept(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def hydrate_focus_concepts(focus: Focus, indexes: object) -> Focus:
    """Populate missing concept fields from one legacy focus, idempotently.

    State deserialization cannot translate an ID such as ``uni-nmims`` without
    the active taxonomy. Callers therefore pass the current index object after a
    session is loaded. Existing concept values and provenance always win, so
    repeated calls are safe and catalog refreshes cannot rewrite a resolved turn.
    """

    metadata_by_id = getattr(indexes, "entity_metadata", None)
    if not isinstance(metadata_by_id, Mapping):
        metadata_by_id = {}

    entity_metadata = metadata_by_id.get(focus.entity_id or "", {})
    university_metadata = metadata_by_id.get(focus.university or "", {})
    hydrated_slots: list[FocusSlot] = []

    if focus.university_concept is None:
        university = (
            _metadata_value(university_metadata, "university_name")
            or _metadata_value(university_metadata, "canonical_name")
            or _metadata_value(entity_metadata, "university_name")
        )
        # Some compatibility tests and external sessions already store a
        # university concept rather than an index ID in the legacy field.
        if university is None and focus.university and focus.university not in metadata_by_id:
            university = focus.university
        focus.university_concept = _clean_concept(university)
        if focus.university_concept is not None:
            hydrated_slots.append("university")

    if focus.course_concept is None:
        course = focus.category or _metadata_value(entity_metadata, "category")
        focus.course_concept = _clean_concept(course)
        if focus.course_concept is not None:
            hydrated_slots.append("course")

    if focus.specialization_concept is None:
        specialization = (
            focus.specialization
            or _metadata_value(entity_metadata, "specialization_name")
            or _metadata_value(entity_metadata, "spec_name")
        )
        focus.specialization_concept = _clean_concept(specialization)
        if focus.specialization_concept is not None:
            hydrated_slots.append("specialization")

    for slot in hydrated_slots:
        focus.sources.setdefault(slot, "context")
    if hydrated_slots and focus.source is None:
        focus.source = "context"
    return focus


class PendingClarification(StateModel):
    candidates: list[str] = Field(default_factory=list)
    slot_type: Literal["university", "course", "specialization"] | None = None
    asked_at_turn: int | None = Field(default=None, ge=0)
    # A comparison may contain one ambiguous operand plus already-resolved
    # operands. Preserve that bounded plan so selecting the ambiguous meaning
    # resumes the comparison instead of degrading to a factual overview.
    resume_intent: Literal["comparison"] | None = None
    comparison_universities: list[str] = Field(default_factory=list)
    comparison_categories: list[str] = Field(default_factory=list)
    comparison_entity_ids: list[str] = Field(default_factory=list)
    comparison_common_category: str | None = None
    comparison_specializations: list[list[str]] = Field(default_factory=list)


class LeadState(StateModel):
    # ``active`` is the flow lifecycle authority. ``last_asked_field`` remains
    # for wire/session compatibility, but ordinary chat must never infer an
    # active lead flow from missing contact fields alone.
    active: bool = False
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    last_asked_field: Literal["name", "phone", "email"] | None = None
    conversion_recorded: bool = False

    @model_validator(mode="after")
    def hydrate_legacy_activity(self) -> LeadState:
        """Resume older persisted funnels that only stored a pending field."""

        if self.last_asked_field is not None:
            self.active = True
        return self

    def deactivate(self) -> None:
        self.active = False
        self.last_asked_field = None

    def restart(self) -> None:
        self.active = True
        self.name = None
        self.phone = None
        self.email = None
        self.last_asked_field = "name"


AdvisorField = Literal[
    "current_education",
    "work_experience",
    "career_goal",
    "budget",
    "preferred_specialization",
]


class AdvisorState(StateModel):
    """Profile collected only inside the opt-in guided recommendation flow."""

    active: bool = False
    category: str | None = None
    current_education: str | None = None
    work_experience: str | None = None
    career_goal: str | None = None
    budget: float | None = Field(default=None, ge=0)
    preferred_specialization: str | None = None
    last_asked_field: AdvisorField | None = None

    def clear(self) -> None:
        self.active = False
        self.category = None
        self.current_education = None
        self.work_experience = None
        self.career_goal = None
        self.budget = None
        self.preferred_specialization = None
        self.last_asked_field = None


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
    """Persisted multi-turn tool state; absent means the ordinary chat pipeline."""

    tool: Literal["roi", "career_quiz", "scholarship"]
    step: str
    answers: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    version: str = ""


class ConversationState(StateModel):
    session_id: str
    focus: Focus = Field(default_factory=Focus)
    pending_clarification: PendingClarification | None = None
    lead: LeadState = Field(default_factory=LeadState)
    advisor: AdvisorState = Field(default_factory=AdvisorState)
    navigation: NavigationState = Field(default_factory=NavigationState)
    active_flow: ActiveFlow | None = None
    tool_attempts: dict[str, int] = Field(default_factory=dict)
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


__all__ = [
    "ActiveFlow",
    "AdvisorField",
    "AdvisorState",
    "ConversationState",
    "Focus",
    "FocusSlot",
    "FocusSource",
    "LeadState",
    "NavigationState",
    "NavigationStep",
    "PendingClarification",
    "SessionState",
    "hydrate_focus_concepts",
]
