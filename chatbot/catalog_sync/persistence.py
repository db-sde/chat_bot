"""Durable storage for the pages WordPress syncs into the catalog.

The live catalog is an in-memory snapshot, so without this a restart or redeploy
drops every synced page and the bot falls back to its base catalog (the bundled
sample, CATALOG_URL or CATALOG_PATH). Each synced page is stored here exactly as
the sync staged it (before relationship resolution); at startup and after a
reindex they are laid back over the base catalog and resolved again, which
reproduces what was live before the restart.

Off unless CATALOG_DATABASE_URL (or DATABASE_URL) is set. One short-lived
connection per write: syncs are rare, and a pool would hold the database awake
(on Neon, an idle compute suspends and stops billing). For the same reason the
health endpoint reports the last known state instead of querying the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

LOGGER = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chatbot_catalog_records (
    post_key TEXT PRIMARY KEY,
    page_type TEXT NOT NULL,
    post_id TEXT NOT NULL,
    record JSONB NOT NULL,
    wordpress_modified TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class CatalogStorageError(RuntimeError):
    """The catalog database could not be read or written."""


@dataclass
class StorageState:
    status: str = "off"  # off | ok | down
    records: int | None = None
    checked_at: str | None = None
    detail: str | None = None

    def payload(self) -> dict[str, Any]:
        state: dict[str, Any] = {"status": self.status}
        if self.records is not None:
            state["records"] = self.records
        if self.checked_at:
            state["checked_at"] = self.checked_at
        if self.detail:
            state["detail"] = self.detail
        return state


class CatalogPersistence:
    """Postgres table of synced WordPress records, keyed by wordpress_post_key."""

    def __init__(self, database_url: str | None, *, connect_timeout: int = 15) -> None:
        self.database_url = (database_url or "").strip() or None
        self.connect_timeout = connect_timeout
        self._schema_ready = False
        self.state = StorageState(status="ok" if self.database_url else "off")

    @property
    def enabled(self) -> bool:
        return self.database_url is not None

    async def _connect(self) -> Any:
        import psycopg  # imported lazily: only needed when storage is configured

        return await psycopg.AsyncConnection.connect(
            self.database_url, connect_timeout=self.connect_timeout, autocommit=True
        )

    def _mark(self, status: str, *, records: int | None = None, detail: str | None = None) -> None:
        self.state.status = status
        if records is not None:
            self.state.records = records
        self.state.checked_at = datetime.now(UTC).isoformat()
        self.state.detail = detail

    async def _run(self, operation: str, work: Any) -> Any:
        try:
            async with await self._connect() as conn:
                if not self._schema_ready:
                    await conn.execute(_SCHEMA)
                    self._schema_ready = True
                result = await work(conn)
        except Exception as exc:
            detail = type(exc).__name__
            self._mark("down", detail=detail)
            LOGGER.error("catalog storage %s failed: %s: %s", operation, detail, exc)
            raise CatalogStorageError(f"Catalog storage {operation} failed ({detail})") from exc
        return result

    async def load(self) -> list[dict[str, Any]]:
        """Every stored record, oldest first."""

        async def work(conn: Any) -> list[dict[str, Any]]:
            cursor = await conn.execute(
                "SELECT record FROM chatbot_catalog_records ORDER BY updated_at, post_key"
            )
            return [row[0] for row in await cursor.fetchall()]

        records = await self._run("load", work)
        self._mark("ok", records=len(records))
        return records

    async def upsert(self, record: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        post_key = str(record["wordpress_post_key"])
        page_type = str((record.get("_meta") or {}).get("page_type") or "")

        async def work(conn: Any) -> int:
            await conn.execute(
                """
                INSERT INTO chatbot_catalog_records
                    (post_key, page_type, post_id, record, wordpress_modified, updated_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (post_key) DO UPDATE SET
                    page_type = EXCLUDED.page_type,
                    post_id = EXCLUDED.post_id,
                    record = EXCLUDED.record,
                    wordpress_modified = EXCLUDED.wordpress_modified,
                    updated_at = now()
                """,
                (
                    post_key,
                    page_type,
                    str(record.get("wordpress_post_id") or ""),
                    Jsonb(record),
                    record.get("wordpress_modified"),
                ),
            )
            return await self._count(conn)

        self._mark("ok", records=await self._run("write", work))

    async def delete(self, post_key: str) -> None:
        async def work(conn: Any) -> int:
            await conn.execute(
                "DELETE FROM chatbot_catalog_records WHERE post_key = %s", (post_key,)
            )
            return await self._count(conn)

        self._mark("ok", records=await self._run("delete", work))

    @staticmethod
    async def _count(conn: Any) -> int:
        cursor = await conn.execute("SELECT COUNT(*) FROM chatbot_catalog_records")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
