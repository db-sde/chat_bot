"""Contract coverage for the WordPress Catalog V3 webhook boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import main as main_module
from catalog_sync import SyncPayload
from config import Settings
from data.loader import SAMPLE_CATALOG_PATH


@pytest.fixture()
def sync_client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        catalog_url=None,
        catalog_path=SAMPLE_CATALOG_PATH,
        redis_url=None,
        crm_webhook_url=None,
        dead_letter_path=tmp_path / "lead-dead-letters.jsonl",
        catalog_webhook_secret="sync-test-secret",
        log_level="CRITICAL",
    )
    original = main_module.get_settings
    main_module.get_settings = lambda: settings
    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        main_module.get_settings = original


def _payload(post_id: int, post_type: str = "course", **overrides):
    payload = {
        "post_id": post_id,
        "post_type": post_type,
        "status": "publish",
        "slug": f"wp-{post_type}-{post_id}",
        "modified": "2026-07-31T10:15:00+00:00",
        "acf": {
            "program_name": "Online MBA",
            "total_fee": "₹1.58L",
            "emi_amount": "₹6,600 per month",
            "duration": "2 years",
            "naac_grade": "naac a++",
        },
    }
    payload.update(overrides)
    return payload


def _post(client: TestClient, payload: dict, secret: str = "sync-test-secret"):
    return client.post("/api/catalog/sync", json=payload, headers={"X-Webhook-Secret": secret})


def test_sync_requires_configured_secret_and_valid_payload(sync_client: TestClient) -> None:
    payload = _payload(101)
    assert _post(sync_client, payload, "wrong").status_code == 401
    assert _post(sync_client, {"post_id": 101}).status_code == 422
    payload["modified"] = "not-a-timestamp"
    assert _post(sync_client, payload).status_code == 422


def test_publish_normalizes_and_upserts_idempotently(sync_client: TestClient) -> None:
    payload = _payload(101)
    first = _post(sync_client, payload)
    assert first.status_code == 200
    body = first.json()
    assert body["action"] == "created"
    assert body["catalog_version"] > 0

    entity = sync_client.app.state.service.catalog.get_entity("wp-course-101")
    assert entity is not None
    assert entity.total_fee == "INR 158,000"
    assert entity.total_fee_numeric == 158000
    assert entity.fee_numeric == 158000
    assert entity.emi_amount == "From INR 6,600 per month"
    assert entity.emi_numeric == 6600
    assert entity.duration == "2 Years"
    assert entity.naac_grade == "A++"

    indian_number = _payload(104)
    indian_number["acf"]["total_fee"] = "₹1,18,000"
    assert _post(sync_client, indian_number).status_code == 200
    assert (
        sync_client.app.state.service.catalog.get_entity("wp-course-104").total_fee_numeric
        == 118000
    )

    version_before_repeat = sync_client.app.state.service.catalog.version
    repeated = _post(sync_client, payload).json()
    assert repeated["action"] == "unchanged"
    assert repeated["catalog_version"] == version_before_repeat

    payload["acf"]["total_fee"] = "₹1.75L"
    updated = _post(sync_client, payload).json()
    assert updated["action"] == "updated"
    assert updated["catalog_version"] > body["catalog_version"]
    assert (
        sync_client.app.state.service.catalog.get_entity("wp-course-101").total_fee_numeric
        == 175000
    )


@pytest.mark.parametrize("status", ["trash", "draft", "pending"])
def test_unpublished_statuses_delete_from_live_catalog(
    sync_client: TestClient, status: str
) -> None:
    payload = _payload(102)
    assert _post(sync_client, payload).status_code == 200
    payload["status"] = status
    response = _post(sync_client, payload)
    assert response.status_code == 200
    assert response.json()["action"] == "deleted"
    assert sync_client.app.state.service.catalog.get_entity("wp-course-102") is None


def test_relationships_resolve_later_without_rejecting_child(sync_client: TestClient) -> None:
    course = _payload(202, acf={"program_name": "Online MCA", "linked_university": 201})
    initial = _post(sync_client, course).json()
    assert initial["unresolved_relationships"] == ["university"]

    university = _payload(
        201,
        "university",
        acf={"university_full_name": "Example University", "starting_fee": "₹80,000"},
    )
    assert _post(sync_client, university).status_code == 200
    course_entity = sync_client.app.state.service.catalog.get_entity("wp-course-202")
    assert course_entity.linked_university == "wp-university-201"
    assert course_entity.university_name == "Example University"

    specialization = _payload(
        203,
        "specialization",
        acf={
            "specialization_name": "Data Analytics",
            "linked_university": 201,
            "linked_course": 202,
        },
    )
    assert _post(sync_client, specialization).status_code == 200
    spec_entity = sync_client.app.state.service.catalog.get_entity("wp-specialization-203")
    assert spec_entity.linked_university == "wp-university-201"
    assert spec_entity.linked_course == "wp-course-202"


def test_concurrent_webhooks_commit_complete_snapshots(sync_client: TestClient) -> None:
    service = sync_client.app.state.service.catalog_sync

    async def send(post_id: int) -> None:
        await service.sync(SyncPayload.model_validate(_payload(post_id)))

    async def run() -> None:
        await asyncio.gather(send(301), send(302))

    asyncio.run(run())
    catalog = sync_client.app.state.service.catalog
    assert catalog.get_entity("wp-course-301") is not None
    assert catalog.get_entity("wp-course-302") is not None
    assert catalog.last_updated is not None
