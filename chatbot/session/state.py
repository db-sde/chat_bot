"""Serializable state for guided navigation, leads, and ActiveFlow tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar, Literal

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


class EntityRef(StateModel):
    """One catalog entity the session has focused on."""

    type: str = ""
    id: str = ""
    label: str = ""

    @property
    def key(self) -> str:
        return f"{self.type}:{self.id}" if self.id else ""


class SessionContext(StateModel):
    """§11.5 the session owns context; the landing page only seeds it.

    `consumed` is keyed **per entity**, never per session: exhausting one
    university's pool must leave the next one's pool full, otherwise the
    dead-end bug simply reappears one level deeper.
    """

    active: EntityRef | None = None
    stack: list[EntityRef] = Field(default_factory=list)      # breadcrumb (§11.4)
    visited: list[EntityRef] = Field(default_factory=list)    # rail, cap 5 (§11.3)
    consumed: dict[str, list[str]] = Field(default_factory=dict)

    VISITED_CAP: ClassVar[int] = 5

    def consumed_for(self, key: str) -> frozenset[str]:
        return frozenset(self.consumed.get(key, ()))

    def consume(self, key: str, chip_id: str) -> None:
        if not key or not chip_id:
            return
        used = self.consumed.setdefault(key, [])
        if chip_id not in used:
            used.append(chip_id)

    def enter(self, entity: EntityRef) -> None:
        """Switch the active entity, maintaining breadcrumb and rail."""

        if not entity.key:
            return
        self.active = entity
        # The breadcrumb is a path: re-entering an ancestor truncates back to it.
        existing = next(
            (i for i, item in enumerate(self.stack) if item.key == entity.key), None
        )
        if existing is not None:
            del self.stack[existing + 1 :]
        else:
            self.stack.append(entity)
        self.visited = [item for item in self.visited if item.key != entity.key]
        self.visited.insert(0, entity)
        del self.visited[self.VISITED_CAP :]
        # A newly seen entity starts with a full, unconsumed pool.
        self.consumed.setdefault(entity.key, [])

    def reset(self) -> None:
        self.active = None
        self.stack.clear()
        self.visited.clear()
        self.consumed.clear()


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
    session_context: SessionContext = Field(default_factory=SessionContext)

SessionState = ConversationState


__all__ = [
    "ActiveFlow",
    "ConversationState",
    "EntityRef",
    "SessionContext",
    "Focus",
    "LeadState",
    "NavigationState",
    "NavigationStep",
    "SessionState",
]
