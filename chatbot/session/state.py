"""Serializable conversation state and focus tracking models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


__all__ = [
    "ConversationState",
    "Focus",
    "FocusSlot",
    "FocusSource",
    "LeadState",
    "PendingClarification",
    "SessionState",
    "hydrate_focus_concepts",
]
