"""Shared transport and domain schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PageType = Literal["university", "course", "specialization"]
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
    page_university_slug: str | None = Field(default=None)

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


class UniversityCard(TransportModel):
    type: Literal["university_card"] = "university_card"
    id: str | None = None
    slug: str | None = None
    name: str = Field(min_length=1)
    summary: str | None = None
    logo_url: str | None = None
    details_url: str | None = None
    highlights: list[CardFact] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)


class ProgramCard(TransportModel):
    type: Literal["program_card"] = "program_card"
    kind: Literal["course", "specialization"] = "course"
    id: str | None = None
    slug: str | None = None
    name: str = Field(min_length=1)
    university_name: str | None = None
    category: str | None = None
    summary: str | None = None
    duration: str | None = None
    fee: str | None = None
    eligibility: str | None = None
    mode: str | None = None
    specializations: list[str] = Field(default_factory=list)
    career_outcomes: list[str] = Field(default_factory=list)
    highlights: list[CardFact] = Field(default_factory=list)
    details_url: str | None = None


class ComparisonItem(TransportModel):
    id: str | None = None
    name: str = Field(min_length=1)
    subtitle: str | None = None
    facts: list[CardFact] = Field(default_factory=list)


class ComparisonCard(TransportModel):
    type: Literal["comparison_card"] = "comparison_card"
    title: str = "Comparison"
    items: list[ComparisonItem] = Field(min_length=2, max_length=3)


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


class QuickActionsComponent(TransportModel):
    type: Literal["quick_actions"] = "quick_actions"
    actions: list[QuickAction] = Field(min_length=1, max_length=6)


ResponseComponent = Annotated[
    UniversityCard
    | ProgramCard
    | ComparisonCard
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
