from __future__ import annotations

from collections.abc import Iterator
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
    assert payload["info"]["validity"]["available"] is True
    assert all(
        not value["available"]
        for key, value in payload["info"].items()
        if key != "validity"
    )


@pytest.mark.parametrize(
    ("params", "entity_id", "label"),
    [
        (
            {"page_type": "university", "university": "nmims"},
            "uni-nmims",
            "NMIMS Global Access",
        ),
        (
            {"page_type": "course", "university": "nmims", "course": "mca"},
            "course-nmims-mca",
            "NMIMS Global Access • MCA",
        ),
        (
            {
                "page_type": "specialization",
                "university": "nmims",
                "course": "mca",
                "specialization": "cloud-computing",
            },
            "spec-nmims-mca-cloud-computing",
            "NMIMS Global Access • MCA • Cloud Computing",
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
        params={"entity_id": "spec-nmims-mca-cloud-computing"},
    )

    assert response.status_code == 200
    assert response.json()["context"] == {
        "page_type": "specialization",
        "university": "NMIMS Global Access",
        "course": "MCA",
        "specialization": "Cloud Computing",
        "entity_id": "spec-nmims-mca-cloud-computing",
        "label": "NMIMS Global Access • MCA • Cloud Computing",
    }


def test_information_projection_never_fabricates_absent_publisher_data(
    guide_client: TestClient,
) -> None:
    response = guide_client.get(
        "/api/widget/guide/context",
        params={"entity_id": "spec-nmims-mca-cloud-computing"},
    )

    info = response.json()["info"]
    assert info["fees"] == {
        "available": True,
        "total_fee": "INR 161,023",
        "semester_fee": "INR 79,000.0 per semester",
        "emi": "From INR 6,600 per month",
        "plans": [],
        "fee_numeric": 161023,
        "fee_metadata": {
            "currency": "INR",
            "fee_type": "total",
            "billing_cycle": "total",
        },
    }
    assert info["eligibility"]["summary"] == "Bachelor's degree in any discipline"
    assert info["eligibility"]["requirements"] == [
        "Bachelor's degree in any discipline",
        "Minimum 50% aggregate marks",
    ]
    assert info["career"] == {
        "available": True,
        "average_salary": "INR 4.0 LPA",
        "job_roles": ["Business Analyst"],
        "recruiters": [],
    }
    assert info["syllabus"] == {"available": False, "semesters": []}
    assert info["reviews"] == {
        "available": False,
        "rating": None,
        "breakdown": [],
        "testimonials": [],
        "review_count": None,
    }
    assert info["accreditations"] == {
        "available": True,
        "items": [
            "UGC Entitled",
            "NAAC — Accredited (NAAC grade A+)",
            "NIRF — Ranked",
            "UGC — Entitled",
            "AICTE — Approved",
        ],
    }
    assert info["admissions"] == {
        "available": True,
        "steps": [
            "Fill the online application form",
            "Upload required academic documents",
            "Pay the registration fee",
            "Receive counselor verification call",
            "Complete fee payment for the first semester",
            "Get enrollment confirmation and LMS access",
        ],
        "fee_note": None,
    }


def test_fee_projection_returns_published_backend_plans(
    guide_client: TestClient,
) -> None:
    response = guide_client.get(
        "/api/widget/guide/context",
        params={"entity_id": "course-nmims-bca"},
    )

    assert response.status_code == 200
    fees = response.json()["info"]["fees"]
    assert fees["total_fee"] == "INR 66,000"
    assert fees["semester_fee"] == "INR 33,000.0 per semester"
    assert fees["emi"] == "From INR 2,800 per month"
    assert fees["plans"] == [
        {
            "name": "Pay in full",
            "amount": "INR 66,000",
            "total": "INR 66,000",
            "note": "One-time payment",
        },
        {
            "name": "Semester-wise",
            "amount": "INR 33,000",
            "total": "INR 66,000",
            "note": "Available payment option",
        },
        {
            "name": "Monthly EMI",
            "amount": "From INR 2,800 per month",
            "total": None,
            "note": "Easy EMI option",
        },
    ]

    mca_response = guide_client.get(
        "/api/widget/guide/context",
        params={"entity_id": "course-nmims-mca"},
    )
    assert mca_response.status_code == 200
    mca_fees = mca_response.json()["info"]["fees"]
    assert mca_fees["total_fee"] == "INR 158,000"
    assert mca_fees["semester_fee"] == "INR 79,000.0 per semester"
    assert mca_fees["emi"] == "From INR 6,600 per month"
    assert mca_fees["plans"] == [
        {
            "name": "Pay in full",
            "amount": "INR 158,000",
            "total": "INR 158,000",
            "note": "One-time payment",
        },
        {
            "name": "Semester-wise",
            "amount": "INR 79,000",
            "total": "INR 158,000",
            "note": "Available payment option",
        },
        {
            "name": "Monthly EMI",
            "amount": "From INR 6,600 per month",
            "total": None,
            "note": "Easy EMI option",
        },
    ]


def test_related_records_follow_catalog_links(guide_client: TestClient) -> None:
    course = guide_client.get(
        "/api/widget/guide/context",
        params={"page_type": "course", "university": "nmims", "course": "mca"},
    ).json()
    specialization_ids = {item["id"] for item in course["related"]["specializations"]}

    assert specialization_ids == {
        "spec-nmims-mca-cloud-computing",
    }
    assert course["related"]["universities"][0]["id"] == "uni-nmims"
    assert all(
        item["category"] == "MCA" for item in course["related"]["alternatives"]
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
        params={"university": "nmims", "course": "mca"},
    )
    specializations = guide_client.get(
        "/api/widget/guide/catalog/specializations",
        params={"university": "nmims", "course": "mca", "q": "cloud"},
    )

    assert universities.status_code == 200
    assert [item["id"] for item in universities.json()["items"]] == ["uni-nmims"]
    university = universities.json()["items"][0]
    assert university["name"] == "NMIMS Global Access"
    assert university["naac_grade"] == "A+"
    assert university["ugc_status"] == "UGC Entitled"
    assert university["program_count"] == 4

    assert programs.status_code == 200
    program_items = programs.json()["items"]
    assert {"MBA", "MCA", "BBA", "MSc AI & ML"}.issubset(
        {item["name"] for item in program_items}
    )
    assert all(item["provider_count"] > 0 for item in program_items)

    assert courses.status_code == 200
    assert [item["id"] for item in courses.json()["items"]] == ["course-nmims-mca"]
    assert courses.json()["items"][0]["type"] == "program_card"

    assert specializations.status_code == 200
    assert [item["id"] for item in specializations.json()["items"]] == [
        "spec-nmims-mca-cloud-computing"
    ]


def test_compare_reuses_existing_comparison_card(guide_client: TestClient) -> None:
    response = guide_client.post(
        "/api/widget/guide/compare",
        json={"entity_ids": ["course-lpu-mca", "course-nmims-mca"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "comparison_card"
    assert payload["title"] == "Compare catalog options"
    assert [item["id"] for item in payload["items"]] == [
        "course-lpu-mca",
        "course-nmims-mca",
    ]
    assert payload["verdict"]
    labels = {fact["label"] for fact in payload["items"][0]["facts"]}
    assert {"Fees", "Duration", "Eligibility", "Specializations", "UGC status"} <= labels


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"entity_ids": ["course-lpu-mca"]},
        {"entity_ids": ["course-lpu-mca"] * 2},
        {"entity_ids": ["course-lpu-mca", 7]},
        ["course-lpu-mca", "course-nmims-mca"],
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
        json={"entity_ids": ["course-lpu-mca", "not-a-catalog-id"]},
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
            "course": "mca",
        },
    )

    assert invalid.status_code == 400
    assert unknown.status_code == 404
    assert unknown_parent.status_code == 404


def test_application_exposes_no_free_text_chat_route(guide_client: TestClient) -> None:
    removed_path = "/" + "chat"
    assert all(route.path != removed_path for route in guide_client.app.routes)


def test_guided_tool_endpoint_accepts_only_activeflow_tokens(
    guide_client: TestClient,
) -> None:
    context = guide_client.get(
        "/api/widget/guide/context",
        params={"page_type": "course", "entity_id": "course-nmims-mca"},
    ).json()
    session_id = context["session_id"]

    started = guide_client.post(
        "/api/widget/guide/tool",
        json={
            "session_id": session_id,
            "command": "tool:roi",
            "page_type": "course",
            "entity_id": "course-nmims-mca",
        },
    )
    assert started.status_code == 200
    payload = started.json()["response"]
    assert payload["metadata"]["tool_flow"]["tool"] == "roi"
    answer = next(
        action["message"]
        for action in payload["quick_actions"]
        if action["message"].startswith("tool:answer:")
    )

    advanced = guide_client.post(
        "/api/widget/guide/tool",
        json={"session_id": session_id, "command": answer, "page_type": "course"},
    )
    assert advanced.status_code == 200
    assert advanced.json()["response"]["metadata"]["tool_flow"]["tool"] == "roi"

    rejected = guide_client.post(
        "/api/widget/guide/tool",
        json={"session_id": session_id, "command": "Tell me about NMIMS"},
    )
    assert rejected.status_code == 422
