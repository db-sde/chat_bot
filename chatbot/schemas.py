"""Shared transport and domain schemas."""

from __future__ import annotations

import re

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PageType = Literal["pillar", "university", "course", "specialization"]


class TransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardFact(TransportModel):
    """One catalog-backed label/value pair rendered inside a rich card."""

    label: str = Field(min_length=1)
    value: str = Field(min_length=1)


class CardReview(TransportModel):
    text: str = Field(min_length=1)
    reviewer_name: str | None = None
    reviewer_label: str | None = None
    rating: float | None = None
    theme: str | None = None


class CardFAQ(TransportModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class CardDetails(TransportModel):
    """Progressively disclosed, catalog-backed content for an entity card."""

    description: str | None = None
    accreditations: list[str] = Field(default_factory=list)
    admission_steps: str | None = None
    reviews: list[CardReview] = Field(default_factory=list)
    faqs: list[CardFAQ] = Field(default_factory=list)
    average_rating: float | None = None
    review_count: int | None = Field(default=None, ge=0)


class UniversityCard(TransportModel):
    type: Literal["university_card"] = "university_card"
    id: str | None = None
    slug: str | None = None
    name: str = Field(min_length=1)
    summary: str | None = None
    logo_url: str | None = None
    details_url: str | None = None
    established_year: str | None = None
    starting_fee: str | None = None
    program_count: int | None = Field(default=None, ge=0)
    learning_mode: str | None = None
    naac_grade: str | None = None
    ugc_status: str | None = None
    average_rating: float | None = None
    review_count: int | None = Field(default=None, ge=0)
    highlights: list[CardFact] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    details: CardDetails | None = None


class ProgramCard(TransportModel):
    type: Literal["program_card"] = "program_card"
    kind: Literal["course", "specialization"] = "course"
    id: str | None = None
    slug: str | None = None
    name: str = Field(min_length=1)
    university_name: str | None = None
    category: str | None = None
    discipline: str | None = None
    summary: str | None = None
    duration: str | None = None
    fee: str | None = None
    eligibility: str | None = None
    mode: str | None = None
    naac_grade: str | None = None
    ugc_status: str | None = None
    average_rating: float | None = None
    review_count: int | None = Field(default=None, ge=0)
    specialization_count: int | None = Field(default=None, ge=0)
    emi: str | None = None
    career_outcome: str | None = None
    average_salary: str | None = None
    specializations: list[str] = Field(default_factory=list)
    career_outcomes: list[str] = Field(default_factory=list)
    highlights: list[CardFact] = Field(default_factory=list)
    details_url: str | None = None
    details: CardDetails | None = None


class ComparisonItem(TransportModel):
    id: str | None = None
    name: str = Field(min_length=1)
    subtitle: str | None = None
    facts: list[CardFact] = Field(default_factory=list)


class ComparisonCard(TransportModel):
    type: Literal["comparison_card"] = "comparison_card"
    title: str = "Comparison"
    items: list[ComparisonItem] = Field(min_length=2, max_length=3)
    verdict: str | None = None


class QuickAction(TransportModel):
    label: str = Field(min_length=1)
    message: str = Field(min_length=1)
    action: Literal["guided_command"] = "guided_command"
    chip_id: str | None = None
    chip_handler: str | None = None
    # §2 chip taxonomy: the widget renders nav_set / list_set / content_card
    # differently, so the resolved type travels with every action.
    chip_type: Literal["nav_set", "list_set", "content_card"] = "nav_set"
    rows_visible: int | None = Field(default=None, ge=1, le=20)
    # §10 demoted chips render dimmed with a check instead of disappearing.
    seen: bool = False
    tool: Literal["roi", "career_quiz", "scholarship"] | None = None
    surface: str | None = None
    funnel_stage: Literal["top", "mid", "bottom"] | None = None
    config_version: str | None = None
    content_version: str | None = None
    interaction_count: int | None = Field(default=None, ge=0)
    correlation_id: str | None = None
    lead_tags: dict[str, Any] | None = None


class ResponseContext(TransportModel):
    """Read-only projection of the existing session focus for widget display."""

    university: str | None = None
    course: str | None = None
    specialization: str | None = None
    entity_id: str | None = None
    label: str | None = None


class CatalogOption(TransportModel):
    id: str
    slug: str
    page_type: PageType
    name: str
    university_name: str | None = None
    category: str | None = None
    meta: str | None = None


class CatalogOptionsResponse(TransportModel):
    kind: Literal["university", "program", "specialization"]
    options: list[CatalogOption] = Field(default_factory=list)
    items: list[CatalogOption] = Field(default_factory=list)
    popular: list[CatalogOption] = Field(default_factory=list)


class FinderRequest(TransportModel):
    program: str | None = None
    area: str | None = None
    approval: str | None = None
    budget: str | float | int | None = None


class FinderResponse(TransportModel):
    results: list[ProgramCard] = Field(default_factory=list, max_length=3)
    matched_count: int = Field(ge=0)
    filters: dict[str, Any] = Field(default_factory=dict)


class ContextClearRequest(TransportModel):
    session_id: str = Field(min_length=1, max_length=200)
    # "all" clears focus and resets navigation to the homepage. "flow" abandons
    # only an active tool, leaving the page context the user is on intact.
    # "chips" resets the active entity's consumed chips (§9 Main menu) without
    # losing the entity, its breadcrumb, or the rail.
    scope: Literal["all", "flow", "chips", "main_menu"] = "all"


class ContextClearResponse(TransportModel):
    session_id: str
    context: ResponseContext = Field(default_factory=ResponseContext)


class WidgetLeadRequest(TransportModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=2, max_length=50)
    phone: str = Field(min_length=10, max_length=24)
    # §5.2 client-generated; a duplicate id returns the cached response.
    request_id: str | None = Field(default=None, min_length=1, max_length=100)
    source: str | None = Field(default=None, max_length=100)
    chip_id: str | None = Field(default=None, max_length=100)
    chip_surface: str | None = Field(default=None, max_length=100)
    chip_config_version: str | None = Field(default=None, max_length=80)
    chip_correlation_id: str | None = Field(default=None, max_length=200)


class WidgetLeadResponse(TransportModel):
    success: Literal[True] = True
    session_id: str
    message: str
    response: dict[str, Any] | None = None
    # §4 true when the form was skipped because a lead already exists this session.
    already_captured: bool = False


class GuidedChipRequest(TransportModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    page_type: str = Field(default="homepage", min_length=1, max_length=40)
    surface: str | None = Field(default=None, max_length=100)
    entity_id: str | None = Field(default=None, max_length=200)
    completed_chip_id: str | None = Field(default=None, max_length=100)
    config_version: str | None = Field(default=None, max_length=80)
    correlation_id: str | None = Field(default=None, max_length=200)
    card_type: Literal["university", "course", "specialization"] | None = None
    answer_state: str | None = Field(default=None, max_length=100)


class GuidedToolRequest(TransportModel):
    """One server-issued command for the guided ActiveFlow engine."""

    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    command: str = Field(min_length=1, max_length=500)
    page_type: str = Field(default="homepage", min_length=1, max_length=40)
    entity_id: str | None = Field(default=None, max_length=200)
    chip_id: str | None = Field(default=None, max_length=100)
    chip_surface: str | None = Field(default=None, max_length=100)
    chip_config_version: str | None = Field(default=None, max_length=80)
    # §5.2 client-generated; a duplicate id returns the cached response.
    request_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("command")
    @classmethod
    def command_must_be_a_tool_token(cls, value: str) -> str:
        token = value.strip()
        if token in {
            "tool:roi",
            "tool:career_quiz",
            "tool:scholarship",
            "tool:continue",
        } or re.fullmatch(r"tool:answer:[^:]+:.+", token, flags=re.IGNORECASE):
            return token
        raise ValueError("command must be a supported guided tool token")


class WidgetAnalyticsRequest(TransportModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    event: Literal[
        "chip_shown",
        "chip_tapped",
        "card_shown",
        "cascade_step",
        "apply_clicked",
        "counsellor_clicked",
        # §13 chip-map analytics additions.
        "list_overflow_opened",
        "chip_pool_exhausted",
        # Delta §8 new events.
        "lead_form_shown",
        "lead_form_submitted",
        "lead_form_validation_failed",
        "compare_opponent_selected",
        "duplicate_request_suppressed",
    ]
    surface: str = Field(min_length=1, max_length=100)
    funnel_stage: Literal["top", "mid", "bottom"]
    interaction_count: int = Field(default=0, ge=0)
    entity: dict[str, str | None] = Field(default_factory=dict)
    config_version: str = Field(min_length=1, max_length=80)
    content_version: str = Field(default="not_applicable", min_length=1, max_length=80)
    chip_id: str | None = Field(default=None, max_length=100)
    chip_handler: str | None = Field(default=None, max_length=100)
    chips: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    correlation_id: str | None = Field(default=None, max_length=200)
    lead_tags: dict[str, Any] | None = None
    # Delta §8: small free-form dimensions — the validation `field`, the
    # compared entity ids. One extensible channel, not a parallel event system.
    attributes: dict[str, Any] | None = None


class PageContextResponse(TransportModel):
    page_type: PageType | None = None
    entity_id: str | None = None
    slug: str | None = None
    context: ResponseContext = Field(default_factory=ResponseContext)


class ResponsePayload(TransportModel):
    text: str
    message: str | None = None
    quick_actions: list[QuickAction] = Field(default_factory=list)
    context: ResponseContext = Field(default_factory=ResponseContext)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def default_message_from_legacy_text(self) -> ResponsePayload:
        """Keep old constructors valid while allowing presentation copy to differ."""

        if self.message is None:
            self.message = self.text
        return self


class HealthResponse(TransportModel):
    status: Literal["ok", "degraded"]
    dependencies: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None
    catalog_source: str | None = None


class ReindexResponse(TransportModel):
    status: Literal["ok"] = "ok"
    entity_count: int = Field(ge=0)


# Older callers used this name; keeping it avoids needless coupling between layers.
Response = ResponsePayload
