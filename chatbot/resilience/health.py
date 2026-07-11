"""Per-dependency health probes used by the FastAPI health endpoint."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


async def _probe(name: str, call: Any, timeout: float = 1.0) -> tuple[str, Any]:
    try:
        value = call()
        if hasattr(value, "__await__"):
            value = await asyncio.wait_for(value, timeout=timeout)
        return name, value if isinstance(value, dict) else {"status": "ok" if value else "down"}
    except Exception as exc:
        return name, {"status": "down", "detail": type(exc).__name__}


async def dependency_health(session_store: Any, catalog: Any, llm: Any) -> dict[str, Any]:
    """Check dependencies independently; optional providers are reported explicitly."""

    async def redis_health() -> dict[str, str]:
        if getattr(session_store, "using_memory", False):
            return {"status": "degraded", "mode": "process_memory"}
        reachable = await session_store.health()
        return {"status": "ok" if reachable else "degraded", "mode": "redis"}

    async def catalog_health() -> dict[str, str]:
        url = getattr(catalog, "catalog_url", None)
        configured_path = getattr(catalog, "catalog_path", None)
        if url:
            try:
                async with httpx.AsyncClient(timeout=1.0, follow_redirects=True) as client:
                    response = await client.get(url, headers={"range": "bytes=0-0"})
                    response.raise_for_status()
                return {"status": "ok", "source": "catalog_url"}
            except Exception:
                return {"status": "degraded", "source": "catalog_url", "cache": "available"}
        if configured_path:
            readable = await asyncio.to_thread(Path(configured_path).is_file)
            return {
                "status": "ok" if readable else "degraded",
                "source": "catalog_path",
            }
        available = await catalog.health()
        return {"status": "ok" if available else "down", "source": "bundled_catalog"}

    probes = await asyncio.gather(
        _probe("redis", redis_health),
        _probe("database", catalog_health),
        _probe("llm", llm.health),
    )
    dependencies = dict(probes)
    statuses = [
        value.get("status", "ok") if isinstance(value, dict) else "ok"
        for value in dependencies.values()
    ]
    overall = (
        "ok"
        if all(status not in {"down", "error", "degraded"} for status in statuses)
        else "degraded"
    )
    return {
        "status": overall,
        "timestamp": datetime.now(UTC).isoformat(),
        "dependencies": dependencies,
    }
