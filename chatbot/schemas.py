"""Shared transport and domain schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PageType = Literal["pillar", "university", "course", "specialization"]
SlotType = Literal["university", "course", "specialization"]
Intent = Literal[
    "factual",
    "comparison",
    "advisory",
    "discovery",
    "chitchat",
    "unrelated",
]
Confidence = Literal["HIGH", "MEDIUM"]


class TransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(TransportModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    site_key: str | None = Field(default=None)
    page_type: PageType | None = None
    page_entity_slug: str | None = Field(default=None)
    page_university_slug: str | None = Field(default=None)
    chip_id: str | None = Field(default=None, max_length=100)
    chip_surface: str | None = Field(default=None, max_length=100)
    chip_config_version: str | None = Field(default=None, max_length=80)
    chip_correlation_id: str | None = Field(default=None, max_length=200)

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


class CardListComponent(TransportModel):
    type: Literal["card_list"] = "card_list"
    title: str | None = None
    items: list[UniversityCard | ProgramCard] = Field(min_length=1, max_length=3)


class LeadCTAComponent(TransportModel):
    type: Literal["lead_cta"] = "lead_cta"
    label: str = Field(min_length=1)
    action: str = "start_lead_capture"
    url: str | None = None
    payload: dict[str, Any] | None = None


class QuickAction(TransportModel):
    label: str = Field(min_length=1)
    message: str = Field(min_length=1)
    action: Literal["send_message"] = "send_message"
    chip_id: str | None = None
    chip_handler: str | None = None
    tool: Literal["roi", "career_quiz", "scholarship"] | None = None
    surface: str | None = None
    funnel_stage: Literal["top", "mid", "bottom"] | None = None
    config_version: str | None = None
    content_version: str | None = None
    interaction_count: int | None = Field(default=None, ge=0)
    correlation_id: str | None = None
    lead_tags: dict[str, Any] | None = None


class QuickActionsComponent(TransportModel):
    type: Literal["quick_actions"] = "quick_actions"
    actions: list[QuickAction] = Field(min_length=1, max_length=6)


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


class ContextClearResponse(TransportModel):
    session_id: str
    context: ResponseContext = Field(default_factory=ResponseContext)


class WidgetLeadRequest(TransportModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=2, max_length=50)
    phone: str = Field(min_length=10, max_length=24)
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


class WidgetAnalyticsRequest(TransportModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    event: Literal[
        "chip_shown",
        "chip_tapped",
        "card_shown",
        "cascade_step",
        "apply_clicked",
        "counsellor_clicked",
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


class PageContextResponse(TransportModel):
    page_type: PageType | None = None
    entity_id: str | None = None
    slug: str | None = None
    context: ResponseContext = Field(default_factory=ResponseContext)


ResponseComponent = Annotated[
    UniversityCard
    | ProgramCard
    | ComparisonCard
    | CardListComponent
    | LeadCTAComponent
    | QuickActionsComponent,
    Field(discriminator="type"),
]


class ResponsePayload(TransportModel):
    text: str
    message: str | None = None
    suggested_chips: list[str] = Field(default_factory=list)
    cta: CTA | None = None
    components: list[ResponseComponent] = Field(default_factory=list)
    quick_actions: list[QuickAction] = Field(default_factory=list)
    context: ResponseContext = Field(default_factory=ResponseContext)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def default_message_from_legacy_text(self) -> ResponsePayload:
        """Keep old constructors valid while allowing presentation copy to differ."""

        if self.message is None:
            self.message = self.text
        return self


class ChatResponse(ResponsePayload):
    session_id: str | None = None


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
