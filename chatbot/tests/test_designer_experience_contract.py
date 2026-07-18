from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main as main_module
from config import Settings
from data.loader import SAMPLE_CATALOG_PATH, CatalogStore
from presentation.cards import (
    build_comparison_card,
    build_program_card,
    build_university_card,
)
from presentation.experience import (
    catalog_options,
    context_from_state,
    finder_results,
    quick_actions_for_response,
)
from response.cards import entity_fee, entity_university, parse_money
from schemas import ResponsePayload
from session.state import ConversationState, Focus
from taxonomy.index_builder import normalize_category


@pytest.fixture(scope="module")
def catalog() -> CatalogStore:
    payload = json.loads(SAMPLE_CATALOG_PATH.read_text(encoding="utf-8"))
    return CatalogStore(records=payload["entities"])


@pytest.fixture
def experience_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        catalog_url=None,
        catalog_path=SAMPLE_CATALOG_PATH,
        redis_url=None,
        openai_api_key=None,
        groq_api_key=None,
        gemini_api_key=None,
        crm_webhook_url=None,
        dead_letter_path=tmp_path / "designer-lead-dead-letters.jsonl",
        lead_prompt_after_turn=100,
        log_level="CRITICAL",
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    with TestClient(main_module.app) as client:
        yield client


def _final_sse_payload(response_text: str) -> dict[str, Any]:
    for block in reversed(response_text.replace("\r\n", "\n").split("\n\n")):
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        if event == "response" and data:
            return json.loads(data)
    raise AssertionError("No final response event was returned")


def _entity_id(entity: Any) -> str:
    return str(entity.id)


def _published_status(entity: Any, catalog: CatalogStore) -> str:
    status = str(getattr(entity, "ugc_status", None) or "")
    linked_id = getattr(entity, "linked_university", None)
    linked = catalog.get_entity(linked_id) if linked_id else None
    return status or str(getattr(linked, "ugc_approved", None) or "")


def test_response_payload_keeps_legacy_contract_and_adds_empty_experience_defaults() -> None:
    payload = ResponsePayload(
        text="Legacy answer",
        suggested_chips=["Fees", "Eligibility"],
        cta={"label": "Talk to a counsellor"},
    )

    assert payload.text == "Legacy answer"
    assert payload.message == "Legacy answer"
    assert payload.suggested_chips == ["Fees", "Eligibility"]
    assert payload.cta is not None
    assert payload.cta.label == "Talk to a counsellor"
    assert payload.components == []
    assert payload.quick_actions == []
    assert payload.context.model_dump() == {
        "university": None,
        "course": None,
        "specialization": None,
        "entity_id": None,
        "label": None,
    }
    assert payload.metadata == {}


def test_bundled_university_card_uses_real_fields_and_progressive_details(
    catalog: CatalogStore,
) -> None:
    entity = catalog.get_entity("uni-lpu")
    assert entity is not None

    card = build_university_card(entity, catalog)

    assert card.id == entity.id
    assert card.slug == entity.slug
    assert card.name == entity.university_full_name
    assert card.summary == entity.hero_description
    assert card.established_year == str(entity.established_year)
    assert card.starting_fee == entity.starting_fee
    assert card.learning_mode == entity.mode_of_learning
    assert card.naac_grade == entity.naac_grade
    assert card.ugc_status == entity.ugc_approved
    expected_programs = [
        catalog.get_entity(program_id).program_name for program_id in entity.program_ids
    ]
    assert card.programs == expected_programs
    assert card.program_count == len(entity.program_ids)
    assert card.logo_url is None
    assert card.details_url is None
    assert card.details is not None
    assert card.details.description == entity.hero_description
    assert [faq.model_dump() for faq in card.details.faqs] == [
        faq.model_dump() for faq in entity.faqs
    ]
    assert len(card.details.reviews) == entity.review_count
    assert card.details.average_rating == entity.average_rating
    assert card.details.admission_steps is None


def test_bundled_course_and_specialization_cards_inherit_only_catalog_relationships(
    catalog: CatalogStore,
) -> None:
    course = catalog.get_entity("course-lpu-mca")
    specialization = catalog.get_entity("spec-lpu-mca-cloud-computing")
    assert course is not None and specialization is not None

    course_card = build_program_card(course, catalog)
    specialization_card = build_program_card(specialization, catalog)

    assert course_card.kind == "course"
    assert course_card.name == course.program_name
    assert course_card.university_name == course.university_name
    assert course_card.duration == course.duration
    assert course_card.fee == course.total_fee
    assert course_card.eligibility == course.eligibility_summary
    assert course_card.mode == course.mode
    assert course_card.naac_grade == course.naac_grade
    assert course_card.ugc_status == course.ugc_status
    assert course_card.emi == course.emi_amount
    assert course_card.career_outcome == course.career_outcomes[0]
    assert course_card.average_salary == course.job_profiles[0].avg_salary
    assert course_card.details is not None
    assert course_card.details.description == course.hero_description
    assert len(course_card.details.reviews) == course.review_count
    assert course_card.details.admission_steps is not None

    profile = specialization.job_profiles[0]
    assert specialization_card.kind == "specialization"
    assert specialization_card.name == specialization.specialization_name
    assert specialization_card.university_name == specialization.university_name
    assert specialization_card.duration == specialization.duration
    assert specialization_card.fee == specialization.total_fee
    assert specialization_card.eligibility == specialization.eligibility_summary
    assert specialization_card.mode == specialization.mode
    assert specialization_card.career_outcome == profile.job_title
    assert specialization_card.average_salary == profile.avg_salary
    # These values are absent on the specialization and come only from its real
    # linked course/university, never from presentation defaults.
    assert specialization_card.naac_grade == course.naac_grade
    assert specialization_card.ugc_status == course.ugc_status
    assert specialization_card.emi == course.emi_amount
    assert specialization_card.details is not None
    assert specialization_card.details.description == specialization.hero_description
    assert specialization_card.details.reviews == []
    assert specialization_card.details.faqs == []
    assert specialization_card.details.admission_steps is None


def test_comparison_rows_have_fixed_order_and_verdict_uses_only_published_fee(
    catalog: CatalogStore,
) -> None:
    card = build_comparison_card(
        ["course-lpu-mca", "course-nmims-mca"],
        catalog,
    )

    assert card is not None
    expected_rows = [
        "Fees",
        "Duration",
        "Mode",
        "NAAC grade",
        "UGC status",
        "Specializations",
        "EMI",
        "Eligibility",
    ]
    assert [[fact.label for fact in item.facts] for item in card.items] == [
        expected_rows,
        expected_rows,
    ]
    assert card.items[0].facts[0].value == catalog.get_entity(
        "course-lpu-mca"
    ).total_fee
    assert card.items[1].facts[0].value == catalog.get_entity(
        "course-nmims-mca"
    ).total_fee
    assert card.verdict is not None
    assert "Lovely Professional University" in card.verdict
    assert "lowest published fee" in card.verdict
    assert not any(
        claim in card.verdict.casefold()
        for claim in ("best", "better", "brand", "quality", "career")
    )


@pytest.mark.parametrize(
    ("message", "route", "excluded_label"),
    [
        ("What is the NMIMS MCA fee?", "factual", "Show fees & EMI"),
        ("Compare LPU and NMIMS", "comparison", "Compare my options"),
    ],
)
def test_quick_actions_are_exactly_three_compact_and_do_not_repeat_answered_topic(
    catalog: CatalogStore,
    message: str,
    route: str,
    excluded_label: str,
) -> None:
    entity = catalog.get_entity("course-nmims-mca")
    assert entity is not None

    actions = quick_actions_for_response(entity=entity, message=message, route=route)

    assert len(actions) == 3
    assert len({action.label.casefold() for action in actions}) == 3
    assert all(len(action.label) <= 24 for action in actions)
    assert excluded_label not in {action.label for action in actions}
    assert [action.label for action in actions].count("Talk to a counsellor") == 1
    assert actions[-1].label == "Talk to a counsellor"


def test_overview_followup_can_send_a_verbatim_catalog_faq_with_a_compact_label(
    catalog: CatalogStore,
) -> None:
    entity = catalog.get_entity("uni-lpu")
    assert entity is not None and entity.faqs
    published_question = entity.faqs[0].question
    assert published_question is not None and len(published_question) > 24

    actions = quick_actions_for_response(
        entity=entity,
        message="Tell me about LPU",
        route="factual",
    )

    faq_action = next(action for action in actions if action.message == published_question)
    assert len(faq_action.label) <= 24
    assert faq_action.label.endswith("…")
    assert actions[-1].label == "Talk to a counsellor"


def test_context_projects_the_real_mca_label(catalog: CatalogStore) -> None:
    state = ConversationState(
        session_id="designer-context",
        focus=Focus(entity_id="course-nmims-mca", category="mca"),
    )

    context = context_from_state(state, catalog)

    assert context.university == "NMIMS Global Access"
    assert context.course == "MCA"
    assert context.specialization is None
    assert context.entity_id == "course-nmims-mca"
    assert context.label == "NMIMS Global Access · MCA"


def test_catalog_options_dedupe_without_inventing_popularity(
    catalog: CatalogStore,
) -> None:
    _university_options, popular_universities = catalog_options(catalog, "university")
    program_options, _ = catalog_options(catalog, "program")
    specialization_options, popular_specializations = catalog_options(
        catalog,
        "specialization",
    )

    program_categories = [normalize_category(option.category) for option in program_options]
    specialization_disciplines = [
        option.name.casefold() for option in specialization_options
    ]
    assert len(program_categories) == len(set(program_categories))
    assert len(specialization_disciplines) == len(set(specialization_disciplines))
    # The bundled catalog publishes no traffic/popularity field. An empty
    # section is honest; catalog order must never be presented as "Popular".
    assert popular_universities == []
    assert popular_specializations == []


def test_catalog_options_use_only_explicit_popularity_or_traffic_rank() -> None:
    records = {
        "ordinary": {
            "_meta": {"page_type": "university"},
            "id": "ordinary",
            "slug": "ordinary",
            "university_full_name": "Ordinary University",
            "popular": "false",
        },
        "ranked-two": {
            "_meta": {"page_type": "university"},
            "id": "ranked-two",
            "slug": "ranked-two",
            "university_full_name": "Ranked Two University",
            "traffic_rank": 2,
        },
        "ranked-one": {
            "_meta": {"page_type": "university"},
            "id": "ranked-one",
            "slug": "ranked-one",
            "university_full_name": "Ranked One University",
            "popularity_rank": "1",
        },
        "explicit": {
            "_meta": {"page_type": "university"},
            "id": "explicit",
            "slug": "explicit",
            "university_full_name": "Explicitly Popular University",
            "is_popular": True,
        },
    }

    _, popular = catalog_options(records, "university")

    assert [option.id for option in popular] == [
        "ranked-one",
        "ranked-two",
        "explicit",
    ]


def test_finder_returns_priced_cheapest_middle_and_premium_mba_options(
    catalog: CatalogStore,
) -> None:
    results, matched_count = finder_results(catalog, program="mba")
    matching = [
        entity
        for entity in catalog.list_entities("course")
        if str(entity.program_name or "").casefold() == "mba"
    ]
    priced = sorted(
        (entity for entity in matching if parse_money(entity_fee(entity)) is not None),
        key=lambda entity: (
            parse_money(entity_fee(entity)),
            entity_university(entity).casefold(),
            str(entity.program_name or "").casefold(),
        ),
    )
    expected = [priced[0], priced[(len(priced) - 1) // 2], priced[-1]]

    assert matched_count == len(matching)
    assert len(results) == 3
    assert all(parse_money(result.fee) is not None for result in results)
    assert [result.id for result in results] == [_entity_id(entity) for entity in expected]


def test_finder_does_not_collapse_unsupported_executive_mba_into_mba(
    catalog: CatalogStore,
) -> None:
    results, matched_count = finder_results(catalog, program="Online Executive MBA")

    assert matched_count == 0
    assert results == []


def test_finder_applies_approval_and_budget_without_relaxing_filters(
    catalog: CatalogStore,
) -> None:
    results, matched_count = finder_results(
        catalog,
        program="bba",
        approval="UGC-DEB",
        budget="1-2L",
    )
    matching = [
        entity
        for entity in catalog.list_entities("course")
        if normalize_category(entity.program_name or entity.category) == "bba"
        and "ugc" in _published_status(entity, catalog).casefold()
        and (fee := parse_money(entity_fee(entity))) is not None
        and 100_000 <= fee <= 200_000
    ]

    assert matched_count == len(matching)
    assert matched_count >= 3
    assert len(results) == 3
    assert all(100_000 <= parse_money(result.fee) <= 200_000 for result in results)
    assert all(
        "ugc" in _published_status(catalog.get_entity(result.id), catalog).casefold()
        for result in results
    )


def test_widget_page_context_and_catalog_endpoints_expose_deduplicated_real_data(
    experience_client: TestClient,
) -> None:
    page = experience_client.get(
        "/api/widget/page-context",
        params={"page_type": "course", "page_entity_slug": "nmims-mca"},
    )
    specialization_page = experience_client.get(
        "/api/widget/page-context",
        params={
            "page_type": "specialization",
            "page_entity_slug": "nmims-mca-cloud-computing",
        },
    )
    universities = experience_client.get("/api/widget/catalog/university")
    programs = experience_client.get("/api/widget/catalog/program")
    specializations = experience_client.get("/api/widget/catalog/specialization")

    assert page.status_code == 200
    assert page.json() == {
        "page_type": "course",
        "entity_id": "course-nmims-mca",
        "slug": "nmims-mca",
        "context": {
            "university": "NMIMS Global Access",
            "course": "MCA",
            "specialization": None,
            "entity_id": "course-nmims-mca",
            "label": "NMIMS Global Access · MCA",
        },
    }
    assert universities.status_code == 200
    assert programs.status_code == 200
    assert specializations.status_code == 200
    assert specialization_page.status_code == 200
    assert specialization_page.json()["context"] == {
        "university": "NMIMS Global Access",
        "course": "MCA",
        "specialization": "Cloud Computing",
        "entity_id": "spec-nmims-mca-cloud-computing",
        "label": "NMIMS Global Access · MCA · Cloud Computing",
    }

    university_payload = universities.json()
    program_payload = programs.json()
    specialization_payload = specializations.json()
    assert university_payload["popular"] == []
    assert specialization_payload["popular"] == []
    assert len({item["category"] for item in program_payload["options"]}) == len(
        program_payload["options"]
    )
    assert len(
        {item["name"].casefold() for item in specialization_payload["options"]}
    ) == len(specialization_payload["options"])


def test_widget_finder_endpoint_returns_three_honestly_filtered_cards(
    experience_client: TestClient,
) -> None:
    response = experience_client.post(
        "/api/widget/finder",
        json={"program": "bba", "approval": "UGC-DEB", "budget": "1-2L"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched_count"] >= 3
    assert payload["filters"] == {
        "program": "bba",
        "approval": "UGC-DEB",
        "budget": "1-2L",
    }
    assert len(payload["results"]) == 3
    assert all(100_000 <= parse_money(result["fee"]) <= 200_000 for result in payload["results"])
    assert all("ugc" in result["ugc_status"].casefold() for result in payload["results"])


def test_widget_finder_endpoint_returns_honest_empty_for_unsupported_program(
    experience_client: TestClient,
) -> None:
    response = experience_client.post(
        "/api/widget/finder",
        json={"program": "Online Executive MBA"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [],
        "matched_count": 0,
        "filters": {"program": "Online Executive MBA"},
    }


def test_widget_context_clear_is_persisted_for_the_next_turn(
    experience_client: TestClient,
) -> None:
    session_id = "designer-context-clear-contract"
    focused = experience_client.post(
        "/chat",
        json={
            "message": "Tell me about NMIMS MCA",
            "session_id": session_id,
            "site_key": "degreebaba",
        },
    )
    assert focused.status_code == 200
    assert _final_sse_payload(focused.text)["context"]["label"] == "NMIMS Global Access · MCA"

    cleared = experience_client.post(
        "/api/widget/context/clear",
        json={"session_id": session_id},
    )
    assert cleared.status_code == 200
    assert cleared.json()["context"]["label"] is None

    next_turn = experience_client.post(
        "/chat",
        json={
            "message": "Hi",
            "session_id": session_id,
            "site_key": "degreebaba",
        },
    )
    assert next_turn.status_code == 200
    assert _final_sse_payload(next_turn.text)["context"]["label"] is None


def test_widget_phone_only_lead_endpoint_validates_and_accepts_one_field(
    experience_client: TestClient,
) -> None:
    invalid = experience_client.post(
        "/api/widget/lead",
        json={
            "session_id": "designer-invalid-phone",
            "phone": "1234567890",
            "source": "comparison_verdict",
        },
    )
    valid = experience_client.post(
        "/api/widget/lead",
        json={
            "session_id": "designer-valid-phone",
            "phone": "98765 43210",
            "source": "comparison_verdict",
        },
    )

    assert invalid.status_code == 422
    assert "valid 10-digit Indian mobile number" in invalid.json()["detail"]
    assert valid.status_code == 200
    assert valid.json() == {
        "success": True,
        "session_id": "designer-valid-phone",
        "message": "Thanks — a DegreeBaba counsellor can contact you shortly.",
    }
