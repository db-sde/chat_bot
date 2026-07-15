from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main as main_module
from config import Settings
from data.loader import SAMPLE_CATALOG_PATH
from presentation.response_builder import enrich_response
from schemas import ResponsePayload


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    patcher = pytest.MonkeyPatch()
    settings = Settings(
        catalog_url=None,
        catalog_path=SAMPLE_CATALOG_PATH,
        redis_url=None,
        openai_api_key=None,
        groq_api_key=None,
        gemini_api_key=None,
        crm_webhook_url=None,
        dead_letter_path=tmp_path_factory.mktemp("presentation") / "leads.jsonl",
        lead_prompt_after_turn=100,
        log_level="CRITICAL",
    )
    patcher.setattr(main_module, "get_settings", lambda: settings)
    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        patcher.undo()


def _final_payload(response_text: str) -> dict[str, Any]:
    for block in reversed(response_text.replace("\r\n", "\n").split("\n\n")):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        if event == "response" and data:
            return json.loads(data)
    raise AssertionError("No final SSE response event was returned")


def _chat(client: TestClient, message: str, session_id: str) -> dict[str, Any]:
    response = client.post(
        "/chat",
        json={"message": message, "session_id": session_id, "site_key": "degreebaba"},
    )
    assert response.status_code == 200
    return _final_payload(response.text)


@pytest.mark.parametrize(
    ("message", "session_id", "expected_choices"),
    [
        (
            "Manipal MBA",
            "presentation-clarify-manipal",
            [
                "Manipal University Jaipur Online",
                "Sikkim Manipal University Online",
            ],
        ),
        ("mbaa", "presentation-clarify-mbaa", ["MBA"]),
    ],
)
def test_clarification_preserves_resolver_choices_in_modern_actions(
    client: TestClient,
    message: str,
    session_id: str,
    expected_choices: list[str],
) -> None:
    payload = _chat(client, message, session_id)

    assert payload["suggested_chips"] == expected_choices
    assert [action["message"] for action in payload["quick_actions"]][
        : len(expected_choices)
    ] == expected_choices
    assert len(payload["quick_actions"]) == 3
    assert payload["quick_actions"][-1]["message"] == "Talk to a counsellor"
    assert all(len(action["label"]) <= 24 for action in payload["quick_actions"])
    if message == "mbaa":
        assert payload["quick_actions"][1]["message"] == "Browse programs"


def test_clarification_uses_all_three_choice_slots_before_counsellor() -> None:
    legacy = ResponsePayload(
        text="Choose one option",
        suggested_chips=["First", "Second", "Third", "Fourth"],
    )

    enriched = enrich_response(legacy, route="clarification")

    assert enriched.suggested_chips == ["First", "Second", "Third", "Fourth"]
    assert [action.message for action in enriched.quick_actions] == [
        "First",
        "Second",
        "Third",
    ]


def test_provider_listing_returns_three_catalog_grounded_university_cards(
    client: TestClient,
) -> None:
    payload = _chat(
        client,
        "Show universities offering Business Analytics",
        "presentation-business-analytics",
    )
    card_list = next(
        component for component in payload["components"] if component["type"] == "card_list"
    )
    catalog = client.app.state.service.catalog

    assert card_list["title"] == "Business Analytics Programs"
    assert len(card_list["items"]) == 3
    assert payload["message"] == (
        "Here are three representative published universities for Business Analytics."
    )
    assert all(item["type"] == "university_card" for item in card_list["items"])
    assert len({item["id"] for item in card_list["items"]}) == 3
    assert all(catalog.get_entity(item["id"]) is not None for item in card_list["items"])


def test_program_selection_returns_min_mid_max_catalog_cards(client: TestClient) -> None:
    payload = _chat(client, "Online MBA", "presentation-online-mba")
    card_list = next(
        component for component in payload["components"] if component["type"] == "card_list"
    )
    catalog = client.app.state.service.catalog

    assert card_list["title"] == "MBA Programs"
    assert len(card_list["items"]) == 3
    assert all(item["type"] == "program_card" for item in card_list["items"])
    assert payload["message"] == (
        "Here are three representative published program options for MBA."
    )
    assert len({item["id"] for item in card_list["items"]}) == 3
    assert all(catalog.get_entity(item["id"]) is not None for item in card_list["items"])


def test_university_picker_selection_drills_into_linked_program_cards(
    client: TestClient,
) -> None:
    payload = _chat(
        client,
        "Show programs offered at NMIMS Online",
        "presentation-university-program-cascade",
    )
    card_list = next(
        component for component in payload["components"] if component["type"] == "card_list"
    )

    assert 1 <= len(card_list["items"]) <= 3
    assert payload["message"] == (
        "Here are 2 published program options for NMIMS Online."
    )
    assert all(item["type"] == "program_card" for item in card_list["items"])
    assert {item["id"] for item in card_list["items"]} == {
        "course-nmims-bba",
        "course-nmims-mba",
    }
    assert all(item["university_name"] == "NMIMS" for item in card_list["items"])


def test_lead_cta_requires_delivered_value_not_passive_card_metadata(
    client: TestClient,
) -> None:
    overview = _chat(client, "Tell me about NMIMS MBA", "presentation-lead-overview")
    fee = _chat(client, "What is the fee for NMIMS MBA?", "presentation-lead-fee")
    criteria = _chat(client, "Am I eligible for NMIMS MBA?", "presentation-lead-criteria")
    emi = _chat(client, "What is the EMI for NMIMS MBA?", "presentation-lead-emi")

    assert not any(component["type"] == "lead_cta" for component in overview["components"])
    assert not any(component["type"] == "lead_cta" for component in criteria["components"])
    fee_cta = next(
        component for component in fee["components"] if component["type"] == "lead_cta"
    )
    emi_cta = next(
        component for component in emi["components"] if component["type"] == "lead_cta"
    )
    assert fee_cta["payload"] == {"phone_only": True, "trigger": "published_fee"}
    assert emi_cta["payload"] == {"phone_only": True, "trigger": "published_emi"}


def test_fee_topic_without_a_delivered_fee_does_not_trigger_lead_cta() -> None:
    course = {
        "id": "course-undelivered-fee",
        "_meta": {"page_type": "course"},
        "program_name": "Online MBA",
        "university_name": "Example University",
        "total_fee": "INR 1,50,000",
    }

    enriched = enrich_response(
        ResponsePayload(text="I don't have a published fee answer for that request."),
        route="factual",
        entity=course,
        catalog={course["id"]: course},
        message="What is the fee for this MBA?",
    )

    assert not any(component.type == "lead_cta" for component in enriched.components)


def test_positive_personalized_eligibility_can_trigger_lead_cta() -> None:
    course = {
        "id": "course-positive-eligibility",
        "_meta": {"page_type": "course"},
        "program_name": "Online MBA",
        "university_name": "Example University",
        "eligibility_summary": "Bachelor's degree",
    }

    enriched = enrich_response(
        ResponsePayload(text="Yes — you are eligible based on the details you shared."),
        route="factual",
        entity=course,
        catalog={course["id"]: course},
        message="Am I eligible for this MBA?",
    )

    lead_cta = next(
        component for component in enriched.components if component.type == "lead_cta"
    )
    assert lead_cta.payload == {
        "phone_only": True,
        "trigger": "published_eligibility",
    }


def test_comparison_uses_clean_catalog_title_without_unresolved_widget_warning(
    client: TestClient,
) -> None:
    payload = _chat(
        client,
        "Compare NMIMS Online MBA and Lovely Professional University Online MBA",
        "presentation-comparison-title",
    )
    card = next(
        component
        for component in payload["components"]
        if component["type"] == "comparison_card"
    )

    assert card["title"] == "NMIMS vs Lovely Professional University"
    assert "couldn't find" not in payload["message"].casefold()
    assert "not in the catalog" not in payload["message"].casefold()
    assert "NMIMS" in payload["message"]
    assert "Lovely Professional University" in payload["message"]
