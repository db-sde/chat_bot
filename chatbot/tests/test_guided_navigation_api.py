from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import main as main_module
from config import Settings
from data.loader import SAMPLE_CATALOG_PATH


@pytest.fixture(scope="module")
def guide_client(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[TestClient]:
    temporary = tmp_path_factory.mktemp("guided-navigation")
    settings = Settings(
        catalog_url=None,
        catalog_path=SAMPLE_CATALOG_PATH,
        redis_url=None,
        openai_api_key=None,
        groq_api_key=None,
        gemini_api_key=None,
        crm_webhook_url=None,
        dead_letter_path=temporary / "lead-dead-letters.jsonl",
        lead_prompt_after_turn=100,
        log_level="CRITICAL",
    )
    original = main_module.get_settings
    main_module.get_settings = lambda: settings
    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        main_module.get_settings = original


def test_homepage_context_has_no_catalog_entity(guide_client: TestClient) -> None:
    response = guide_client.get("/api/widget/guide/context", params={"page_type": "homepage"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["context"] == {
        "page_type": "homepage",
        "university": None,
        "course": None,
        "specialization": None,
        "entity_id": None,
        "label": None,
    }
    assert payload["entity"] is None
    assert all(not value["available"] for value in payload["info"].values())


@pytest.mark.parametrize(
    ("params", "entity_id", "label"),
    [
        (
            {"page_type": "university", "university": "nmims"},
            "uni-nmims",
            "NMIMS",
        ),
        (
            {"page_type": "course", "university": "nmims", "course": "mba"},
            "course-nmims-mba",
            "NMIMS • Online MBA",
        ),
        (
            {
                "page_type": "specialization",
                "university": "nmims",
                "course": "mba",
                "specialization": "business-analytics",
            },
            "spec-nmims-mba-analytics",
            "NMIMS • Online MBA • Business Analytics",
        ),
    ],
)
def test_simulator_shorthands_resolve_exact_catalog_relationships(
    guide_client: TestClient,
    params: dict[str, str],
    entity_id: str,
    label: str,
) -> None:
    response = guide_client.get("/api/widget/guide/context", params=params)

    assert response.status_code == 200
    payload = response.json()
    assert payload["context"]["entity_id"] == entity_id
    assert payload["context"]["label"] == label
    assert payload["entity"]["id"] == entity_id
    assert payload["entity"]["type"] in {"university_card", "program_card"}


def test_entity_id_context_derives_all_parent_labels(guide_client: TestClient) -> None:
    response = guide_client.get(
        "/api/widget/guide/context",
        params={"entity_id": "spec-nmims-mba-analytics"},
    )

    assert response.status_code == 200
    assert response.json()["context"] == {
        "page_type": "specialization",
        "university": "NMIMS",
        "course": "Online MBA",
        "specialization": "Business Analytics",
        "entity_id": "spec-nmims-mba-analytics",
        "label": "NMIMS • Online MBA • Business Analytics",
    }


def test_information_projection_never_fabricates_absent_publisher_data(
    guide_client: TestClient,
) -> None:
    response = guide_client.get(
        "/api/widget/guide/context",
        params={"entity_id": "spec-nmims-mba-analytics"},
    )

    info = response.json()["info"]
    assert info["fees"] == {
        "available": True,
        "total_fee": "INR 2,16,000",
        "semester_fee": "INR 54,500 per semester",
        "emi": "From INR 9,000 per month",
        "plans": [
            {
                "name": "Semester Fee",
                "amount": "INR 54,500",
                "total": "INR 2,16,000",
            }
        ],
    }
    assert info["eligibility"]["summary"] == "Bachelor's degree in any discipline"
    assert info["eligibility"]["requirements"] == []
    assert info["career"] == {
        "available": False,
        "average_salary": None,
        "job_roles": [],
        "recruiters": [],
    }
    assert info["syllabus"] == {"available": False, "semesters": []}
    assert info["reviews"] == {
        "available": False,
        "rating": None,
        "breakdown": [],
        "testimonials": [],
    }
    assert info["accreditations"] == {
        "available": True,
        "items": ["UGC Entitled", "NAAC grade A+"],
    }


def test_related_records_follow_catalog_links(guide_client: TestClient) -> None:
    course = guide_client.get(
        "/api/widget/guide/context",
        params={"page_type": "course", "university": "nmims", "course": "mba"},
    ).json()
    specialization_ids = {item["id"] for item in course["related"]["specializations"]}

    assert specialization_ids == {
        "spec-nmims-mba-analytics",
        "spec-nmims-mba-marketing",
    }
    assert course["related"]["universities"][0]["id"] == "uni-nmims"
    assert all(
        item["category"] == "mba" for item in course["related"]["alternatives"]
    )


def test_catalog_picker_endpoints_are_searchable_and_grounded(
    guide_client: TestClient,
) -> None:
    universities = guide_client.get(
        "/api/widget/guide/catalog/universities", params={"q": "nmims"}
    )
    programs = guide_client.get("/api/widget/guide/catalog/programs")
    courses = guide_client.get(
        "/api/widget/guide/catalog/courses",
        params={"university": "nmims", "course": "mba"},
    )
    specializations = guide_client.get(
        "/api/widget/guide/catalog/specializations",
        params={"university": "nmims", "course": "mba", "q": "analytics"},
    )

    assert universities.status_code == 200
    assert [item["id"] for item in universities.json()["items"]] == ["uni-nmims"]
    university = universities.json()["items"][0]
    assert university["name"] == "NMIMS Online"
    assert university["naac_grade"] == "A+"
    assert university["ugc_status"] == "UGC Entitled"
    assert university["program_count"] == 2

    assert programs.status_code == 200
    program_items = programs.json()["items"]
    assert [item["name"] for item in program_items[:4]] == ["MBA", "MCA", "BBA", "MSc"]
    assert all(item["provider_count"] > 0 for item in program_items)

    assert courses.status_code == 200
    assert [item["id"] for item in courses.json()["items"]] == ["course-nmims-mba"]
    assert courses.json()["items"][0]["type"] == "program_card"

    assert specializations.status_code == 200
    assert [item["id"] for item in specializations.json()["items"]] == [
        "spec-nmims-mba-analytics"
    ]


def test_compare_reuses_existing_comparison_card(guide_client: TestClient) -> None:
    response = guide_client.post(
        "/api/widget/guide/compare",
        json={"entity_ids": ["course-lpu-mba", "course-nmims-mba"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "comparison_card"
    assert payload["title"] == "Compare catalog options"
    assert [item["id"] for item in payload["items"]] == [
        "course-lpu-mba",
        "course-nmims-mba",
    ]
    assert payload["verdict"]
    labels = {fact["label"] for fact in payload["items"][0]["facts"]}
    assert {"Fees", "Duration", "Eligibility", "Specializations", "UGC status"} <= labels


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"entity_ids": ["course-lpu-mba"]},
        {"entity_ids": ["course-lpu-mba"] * 2},
        {"entity_ids": ["course-lpu-mba", 7]},
        ["course-lpu-mba", "course-nmims-mba"],
    ],
)
def test_compare_rejects_invalid_operand_shapes(
    guide_client: TestClient,
    body: object,
) -> None:
    response = guide_client.post("/api/widget/guide/compare", json=body)

    assert response.status_code == 400


def test_compare_returns_not_found_for_unknown_exact_id(guide_client: TestClient) -> None:
    response = guide_client.post(
        "/api/widget/guide/compare",
        json={"entity_ids": ["course-lpu-mba", "not-a-catalog-id"]},
    )

    assert response.status_code == 404


def test_context_validation_reports_invalid_and_unknown_inputs(guide_client: TestClient) -> None:
    invalid = guide_client.get(
        "/api/widget/guide/context", params={"page_type": "landing-page"}
    )
    unknown = guide_client.get(
        "/api/widget/guide/context",
        params={"page_type": "university", "university": "missing-university"},
    )
    unknown_parent = guide_client.get(
        "/api/widget/guide/context",
        params={
            "page_type": "course",
            "university": "missing-university",
            "course": "mba",
        },
    )

    assert invalid.status_code == 400
    assert unknown.status_code == 404
    assert unknown_parent.status_code == 404


def test_guide_routes_do_not_enter_existing_chat_pipeline(guide_client: TestClient) -> None:
    process_turn = AsyncMock(side_effect=AssertionError("chat pipeline must not run"))
    service = guide_client.app.state.service
    original = service.process_turn
    service.process_turn = process_turn
    try:
        context = guide_client.get(
            "/api/widget/guide/context",
            params={"page_type": "course", "university": "nmims", "course": "mba"},
        )
        catalog = guide_client.get("/api/widget/guide/catalog/programs")
        comparison = guide_client.post(
            "/api/widget/guide/compare",
            json={"entity_ids": ["course-lpu-mba", "course-nmims-mba"]},
        )
    finally:
        service.process_turn = original

    assert context.status_code == catalog.status_code == comparison.status_code == 200
    process_turn.assert_not_awaited()


def test_prototype_assets_have_isolated_stable_routes(guide_client: TestClient) -> None:
    page = guide_client.get("/widget/prototype")
    index = guide_client.get("/widget/prototype/index.html")
    stylesheet = guide_client.get("/widget/prototype/prototype.css")
    script = guide_client.get("/widget/prototype/prototype.js")

    assert {
        page.status_code,
        index.status_code,
        stylesheet.status_code,
        script.status_code,
    } == {200}
    assert [response.status_code for response in page.history] == [307]
    assert str(page.url).endswith("/widget/prototype/")
    assert "text/html" in page.headers["content-type"]
    assert "text/css" in stylesheet.headers["content-type"]
    assert "application/javascript" in script.headers["content-type"]
