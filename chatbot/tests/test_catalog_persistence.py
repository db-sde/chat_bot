"""Synced WordPress pages survive restarts, redeploys and reindexes.

The database tests need a throwaway Postgres: set CHATBOT_TEST_DATABASE_URL (its
chatbot_catalog_records table is dropped and recreated). Without it they are
skipped; the tests that need no database always run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import main as main_module
from config import Settings
from data.loader import SAMPLE_CATALOG_PATH

TEST_DATABASE_URL = os.environ.get("CHATBOT_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DATABASE_URL, reason="CHATBOT_TEST_DATABASE_URL not set")
UNREACHABLE = "postgresql://nobody@127.0.0.1:9/none?connect_timeout=1"
SECRET = "persist-test-secret"


def _settings(tmp_path, database_url: str | None) -> Settings:
    return Settings(
        catalog_url=None,
        catalog_path=SAMPLE_CATALOG_PATH,
        redis_url=None,
        crm_webhook_url=None,
        dead_letter_path=tmp_path / "lead-dead-letters.jsonl",
        catalog_webhook_secret=SECRET,
        admin_api_key="admin-test-key",
        log_level="CRITICAL",
        CATALOG_DATABASE_URL=database_url,
    )


@contextmanager
def _running(settings: Settings) -> Iterator[TestClient]:
    """One process lifetime of the chatbot: leaving the block is a restart."""

    original = main_module.get_settings
    main_module.get_settings = lambda: settings
    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        main_module.get_settings = original


def _post(client: TestClient, post_id: int, post_type: str, acf: dict, status: str = "publish"):
    payload = {
        "post_id": post_id,
        "post_type": post_type,
        "status": status,
        "slug": f"{post_type}-{post_id}",
        "modified": "2026-11-23T10:00:00Z",
        "acf": acf,
    }
    return client.post("/api/catalog/sync", json=payload, headers={"X-Webhook-Secret": SECRET})


def _entity(client: TestClient, entity_id: str):
    return client.app.state.service.catalog.get_entity(entity_id)


def _storage(client: TestClient) -> dict:
    return client.get("/health").json()["dependencies"]["catalog_storage"]


@pytest.fixture()
def database_url() -> str:
    import psycopg

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS chatbot_catalog_records")
    return TEST_DATABASE_URL


UNIVERSITY = {"university_full_name": "Example University Online", "starting_fee": "₹80,000"}
COURSE = {"program_name": "Online MBA", "total_fee": "₹1.58L", "linked_university": 501}


@needs_db
def test_synced_pages_survive_a_restart_with_their_links(tmp_path, database_url) -> None:
    settings = _settings(tmp_path, database_url)
    with _running(settings) as client:
        base_count = len(client.app.state.service.catalog)
        assert _post(client, 502, "course", COURSE).status_code == 200  # parent not there yet
        assert _post(client, 501, "university", UNIVERSITY).status_code == 200
        storage = _storage(client)
        assert (storage["status"], storage["records"]) == ("ok", 2)

    with _running(settings) as client:  # restarted: memory is empty, storage is not
        assert len(client.app.state.service.catalog) == base_count + 2
        course = _entity(client, "wp-course-502")
        assert course is not None
        assert course.linked_university == "wp-university-501"
        assert course.university_name == "Example University Online"
        assert course.total_fee == "INR 158,000"
        assert _storage(client)["records"] == 2
        assert client.get("/health").json()["status"] in {"ok", "degraded"}


@needs_db
def test_an_update_and_an_unpublish_are_what_survives(tmp_path, database_url) -> None:
    settings = _settings(tmp_path, database_url)
    with _running(settings) as client:
        _post(client, 501, "university", UNIVERSITY)
        _post(client, 502, "course", COURSE)
        _post(client, 502, "course", {**COURSE, "total_fee": "₹2L"})
        removed = _post(client, 501, "university", UNIVERSITY, status="trash")
        assert removed.json()["action"] == "deleted"

    with _running(settings) as client:
        assert _entity(client, "wp-university-501") is None
        course = _entity(client, "wp-course-502")
        assert course.total_fee == "INR 200,000"
        assert course.linked_university is None, "its university was taken down"
        assert _storage(client)["records"] == 1


@needs_db
def test_a_reindex_keeps_the_synced_pages(tmp_path, database_url) -> None:
    # A copy: a reindex refuses a configured path that resolves to the bundled sample itself.
    catalog_copy = tmp_path / "catalog.json"
    catalog_copy.write_text(SAMPLE_CATALOG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    settings = _settings(tmp_path, database_url).model_copy(update={"catalog_path": catalog_copy})
    with _running(settings) as client:
        _post(client, 501, "university", UNIVERSITY)
        response = client.post("/admin/reindex", headers={"Authorization": "Bearer admin-test-key"})
        assert response.status_code == 200
        assert _entity(client, "wp-university-501") is not None
        assert client.app.state.service.catalog_sync.catalog is client.app.state.service.catalog


@needs_db
def test_storage_down_at_startup_is_restored_before_the_next_sync(tmp_path, database_url) -> None:
    with _running(_settings(tmp_path, database_url)) as client:
        _post(client, 501, "university", UNIVERSITY)

    settings = _settings(tmp_path, UNREACHABLE)
    with _running(settings) as client:  # starts on the base catalog
        assert _entity(client, "wp-university-501") is None
        assert _storage(client)["status"] == "down"
        persistence = client.app.state.service.catalog_sync.persistence
        persistence.database_url = database_url  # the database comes back
        assert _post(client, 502, "course", COURSE).status_code == 200
        assert _entity(client, "wp-university-501") is not None, "restored first, not dropped"
        assert _entity(client, "wp-course-502").linked_university == "wp-university-501"


def test_a_sync_is_refused_when_storage_is_down_so_the_sender_retries(tmp_path) -> None:
    with _running(_settings(tmp_path, UNREACHABLE)) as client:
        before = client.app.state.service.catalog.version
        response = _post(client, 501, "university", UNIVERSITY)
        assert response.status_code == 503
        assert response.json()["detail"] == "Catalog storage unavailable"
        assert _entity(client, "wp-university-501") is None, "not live unless stored"
        assert client.app.state.service.catalog.version == before
        assert _storage(client)["status"] == "down"
        assert client.get("/health").json()["status"] == "degraded"


def test_without_a_database_the_catalog_works_as_before(tmp_path) -> None:
    with _running(_settings(tmp_path, None)) as client:
        assert _storage(client) == {"status": "off"}
        assert _post(client, 501, "university", UNIVERSITY).status_code == 200
        assert _entity(client, "wp-university-501") is not None


def test_a_sync_leaves_the_base_catalogs_own_links_alone(tmp_path) -> None:
    with _running(_settings(tmp_path, None)) as client:
        catalog = client.app.state.service.catalog
        linked = {
            record["id"]: record["linked_university"]
            for record in catalog.export_records()
            if (record.get("_meta") or {}).get("page_type") == "course"
            and record.get("linked_university")
        }
        assert linked, "the sample catalog links its courses to universities"
        assert _post(client, 501, "university", UNIVERSITY).status_code == 200
        after = {
            record["id"]: record.get("linked_university")
            for record in client.app.state.service.catalog.export_records()
            if record["id"] in linked
        }
        assert after == linked
