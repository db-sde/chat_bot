from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import Settings
from funnel import ChipEngine, ChipMapStore
from main import ChatbotService, TurnResult
from presentation import enrich_response
from presentation.cards import build_program_card, build_university_card
from response.builder import build_response
from schemas import (
    CardListComponent,
    ChatRequest,
    ComparisonCard,
    LeadCTAComponent,
    ProgramCard,
    QuickAction,
    QuickActionsComponent,
    ResponsePayload,
    UniversityCard,
)
from session.state import ConversationState, Focus
from session.store import MemorySessionStore


def _university(entity_id: str, name: str, fee: str) -> dict:
    return {
        "id": entity_id,
        "slug": entity_id,
        "_meta": {"page_type": "university"},
        "university_name": name,
        "university_full_name": name,
        "hero_description": f"Published overview for {name}.",
        "starting_fee": fee,
        "mode_of_learning": "Online",
        "naac_grade": "A+",
        "ugc_approved": "UGC Entitled",
        "programs_table": [
            {
                "program_name": "Online MBA",
                "program_fee": fee,
                "program_eligibility": "Bachelor's degree",
            }
        ],
    }


def _course(entity_id: str = "alpha-mba") -> dict:
    return {
        "id": entity_id,
        "slug": entity_id,
        "_meta": {"page_type": "course"},
        "program_name": "Online MBA",
        "university_name": "Alpha University",
        "hero_description": "An industry-aligned online management program.",
        "duration": "2 Years",
        "mode": "Online",
        "total_fee": "INR 1,50,000",
        "eligibility_summary": "Bachelor's degree",
        "ugc_status": "UGC Entitled",
        "placement_content": "Resume reviews and interview preparation.",
        "job_profiles": [{"job_title": "Marketing Manager", "avg_salary": "INR 8 LPA"}],
    }


def test_legacy_transport_fields_remain_valid_and_message_can_differ() -> None:
    request = ChatRequest(
        message=" Tell me about MBA ",
        session_id="session",
        site_key="degreebaba",
        page_university_slug="alpha",
        future_widget_field="ignored",
    )
    payload = ResponsePayload(text="Legacy text", message="Advisor presentation")

    assert request.message == "Tell me about MBA"
    assert request.site_key == "degreebaba"
    assert request.page_university_slug == "alpha"
    assert payload.text == "Legacy text"
    assert payload.message == "Advisor presentation"
    assert payload.suggested_chips == []
    assert payload.cta is None
    assert payload.components == []


def test_message_defaults_from_text_and_enrichment_repairs_model_copy() -> None:
    original = ResponsePayload(text="First legacy response")
    copied = original.model_copy(update={"text": "Updated legacy response"})

    assert copied.message == "First legacy response"
    enriched = enrich_response(copied)
    assert enriched.text == "Updated legacy response"
    assert enriched.message == "Updated legacy response"


def test_canonical_builder_mirrors_legacy_actions_as_typed_components() -> None:
    payload = build_response(
        "Published answer",
        suggested_chips=["Fees", "Eligibility", "fees"],
        cta={
            "label": "Talk to a counsellor",
            "action": "start_lead_capture",
            "payload": {"source": "chat"},
        },
    )

    assert payload.text == payload.message == "Published answer"
    assert payload.suggested_chips == ["Fees", "Eligibility"]
    quick_actions = next(
        component
        for component in payload.components
        if isinstance(component, QuickActionsComponent)
    )
    lead_cta = next(
        component for component in payload.components if isinstance(component, LeadCTAComponent)
    )
    assert [action.message for action in quick_actions.actions] == ["Fees", "Eligibility"]
    assert lead_cta.label == "Talk to a counsellor"
    assert lead_cta.payload == {"source": "chat"}


def test_university_and_program_cards_only_include_published_values() -> None:
    university = _university("alpha", "Alpha University", "INR 1,50,000")
    university_card = build_university_card(university)
    program_card = build_program_card(_course())

    assert isinstance(university_card, UniversityCard)
    assert university_card.name == "Alpha University"
    assert university_card.programs == ["Online MBA"]
    university_facts = {fact.label: fact.value for fact in university_card.highlights}
    assert university_facts["Starting fee"] == "INR 1,50,000"
    assert university_facts["NAAC grade"] == "A+"
    assert university_card.logo_url is None
    assert university_card.details_url is None

    assert isinstance(program_card, ProgramCard)
    assert program_card.kind == "course"
    assert program_card.name == "Online MBA"
    assert program_card.university_name == "Alpha University"
    assert program_card.duration == "2 Years"
    assert program_card.fee == "INR 1,50,000"
    assert program_card.eligibility == "Bachelor's degree"
    assert program_card.specializations == []
    assert program_card.career_outcomes == ["Marketing Manager (INR 8 LPA)"]


def test_enrichment_uses_focus_without_mutating_state_or_legacy_text() -> None:
    course = _course()
    catalog = {course["id"]: course}
    state = ConversationState(
        session_id="rich-response",
        focus=Focus(entity_id=course["id"], category="mba"),
    )
    before = state.model_dump()
    payload = ResponsePayload(text="Online MBA\n\nDuration: 2 Years")

    enriched = enrich_response(payload, state=state, route="factual", catalog=catalog)

    assert enriched.text == payload.text
    assert enriched.message != enriched.text
    assert "Online MBA" in (enriched.message or "")
    assert "Duration: 2 Years" not in (enriched.message or "")
    assert isinstance(enriched.components[0], ProgramCard)
    assert state.model_dump() == before


def test_specialization_uses_distinct_program_shape_and_advisor_copy() -> None:
    specialization = {
        "id": "alpha-finance",
        "_meta": {"page_type": "specialization"},
        "category": "mba",
        "specialization_name": "Finance",
        "university_name": "Alpha University",
        "about_content": "A published specialization focused on financial decision-making.",
        "other_specs": [{"other_spec_name": "Marketing"}],
        "job_profiles": [{"job_title": "Financial Analyst"}],
    }
    payload = ResponsePayload(text="Finance\n\nRaw fields: legacy transport")

    enriched = enrich_response(
        payload,
        route="specialization",
        entity=specialization,
        catalog={"alpha-finance": specialization},
    )

    card = next(
        component for component in enriched.components if isinstance(component, ProgramCard)
    )
    assert card.kind == "specialization"
    assert card.name == "Finance"
    assert card.category == "mba"
    assert card.specializations == ["Marketing"]
    assert "MBA specialization at Alpha University" in (enriched.message or "")
    assert "Raw fields" not in (enriched.message or "")


def test_tool_reveal_materializes_catalog_program_cards_and_action_trace() -> None:
    first = _course("course-first")
    second = _course("course-second")
    university = _university("university-only", "University Only", "INR 1,00,000")
    catalog = {
        "course-first": first,
        "course-second": second,
        "university-only": university,
    }
    state = ConversationState(session_id="tool-render", turn_count=2)
    state.navigation.page_type = "course"
    state.navigation.interaction_count = 4
    payload = ResponsePayload(
        text="Your complete career result is ready.",
        quick_actions=[QuickAction(label="Apply now", message="Apply now")],
        metadata={
            "tool_flow": {
                "tool": "career_quiz",
                "step": "reveal",
                "version": "tool-content-v7",
                "cta_program_ids": [
                    "course-second",
                    "missing",
                    "university-only",
                    "course-first",
                    "course-second",
                ],
            }
        },
    )

    enriched = enrich_response(
        payload,
        state=state,
        catalog=catalog,
        chip_engine=ChipEngine(ChipMapStore(auto_reload=False)),
    )

    card_list = next(
        component for component in enriched.components if isinstance(component, CardListComponent)
    )
    assert card_list.title == "Recommended programs"
    assert [card.id for card in card_list.items] == ["course-second", "course-first"]
    assert all(isinstance(card, ProgramCard) for card in card_list.items)
    assert enriched.message == "Your complete career result is ready."
    assert enriched.quick_actions
    assert all(action.interaction_count == 4 for action in enriched.quick_actions)
    assert all(action.correlation_id == "sess_render:turn_4" for action in enriched.quick_actions)
    assert all(action.content_version == "tool-content-v7" for action in enriched.quick_actions)


def test_structured_comparison_operands_win_over_parseable_text() -> None:
    alpha = _university("alpha", "Alpha University", "INR 1,50,000")
    beta = _university("beta", "Beta University", "INR 1,70,000")
    payload = ResponsePayload(
        text=(
            "University Comparison\n\nPublished Details:\n"
            "• Ghost University: published starting fee INR 1.\n"
            "• Phantom University: published starting fee INR 2."
        )
    )

    enriched = enrich_response(
        payload,
        route="comparison",
        catalog={"alpha": alpha, "beta": beta},
        operands=["alpha", "beta"],
    )

    card = next(
        component for component in enriched.components if isinstance(component, ComparisonCard)
    )
    assert [item.name for item in card.items] == ["Alpha University", "Beta University"]
    assert all("Ghost" not in item.name and "Phantom" not in item.name for item in card.items)
    assert "Ghost" not in (enriched.message or "")


def test_comparison_text_is_parsed_only_when_no_structured_operands_exist() -> None:
    payload = ResponsePayload(
        text=(
            "University Comparison\n\nPublished Details:\n"
            "• Alpha University: published starting fee INR 1,50,000; NAAC A+.\n"
            "• Beta University: published starting fee INR 1,70,000; NAAC A."
        )
    )

    fallback = enrich_response(payload, route="comparison")
    fallback_card = next(
        component for component in fallback.components if isinstance(component, ComparisonCard)
    )
    assert [item.name for item in fallback_card.items] == [
        "Alpha University",
        "Beta University",
    ]
    assert fallback_card.items[0].facts[0].value == "INR 1,50,000"

    unresolved_structured = enrich_response(
        payload,
        route="comparison",
        catalog={},
        operands=["missing-alpha", "missing-beta"],
    )
    assert not any(
        isinstance(component, ComparisonCard) for component in unresolved_structured.components
    )


@pytest.mark.asyncio
async def test_service_plumbs_resolved_operands_past_ambiguous_comparison_text() -> None:
    alpha = _university("alpha", "Alpha University", "INR 1,50,000")
    beta = _university("beta", "Beta University", "INR 1,70,000")
    state = ConversationState(session_id="presentation-plumbing")
    raw_result = TurnResult(
        session_id=state.session_id,
        state=state,
        payload=ResponsePayload(
            text=(
                "University Comparison\n\nPublished Details:\n"
                "• Ambiguous first option: published starting fee INR 1.\n"
                "• Ambiguous second option: published starting fee INR 2."
            )
        ),
        route="comparison",
        presentation_operands=("alpha", "beta"),
    )
    service = ChatbotService.__new__(ChatbotService)
    service.catalog = {"alpha": alpha, "beta": beta}

    async def resolved_turn(_: ChatRequest) -> TurnResult:
        return raw_result

    service._process_turn = resolved_turn  # type: ignore[method-assign]
    result = await service.process_turn(ChatRequest(message="compare those options"))

    card = next(
        component
        for component in result.payload.components
        if isinstance(component, ComparisonCard)
    )
    assert [item.name for item in card.items] == ["Alpha University", "Beta University"]
    assert "Ambiguous" not in (result.payload.message or "")


@pytest.mark.asyncio
async def test_real_pipeline_carries_concrete_ids_into_comparison_card() -> None:
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        session_store=MemorySessionStore(),
    )
    try:
        result = await service.process_turn(
            ChatRequest(
                message="Which is better, LPU or NMIMS?",
                session_id="structured-comparison-card",
            )
        )
    finally:
        await service.close()

    card = next(
        component
        for component in result.payload.components
        if isinstance(component, ComparisonCard)
    )
    assert result.presentation_operands == ("uni-lpu", "uni-nmims")
    assert [item.id for item in card.items] == ["uni-lpu", "uni-nmims"]


@pytest.mark.asyncio
async def test_real_program_message_polishes_catalog_grammar_without_changing_text() -> None:
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        session_store=MemorySessionStore(),
    )
    try:
        result = await service.process_turn(
            ChatRequest(message="Tell me about NMIMS MBA", session_id="polished-program")
        )
    finally:
        await service.close()

    assert "A 2 years online mba" in result.payload.text
    assert "A 2-year online MBA" in (result.payload.message or "")
    assert "published Online MBA offering from NMIMS" in (result.payload.message or "")
    assert "Would you like to review the published fees" in (result.payload.message or "")


def test_component_union_rejects_unknown_component_types() -> None:
    with pytest.raises(ValidationError):
        ResponsePayload(text="Answer", components=[{"type": "invented_card"}])
