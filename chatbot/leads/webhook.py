"""Non-blocking CRM webhook with bounded retry and a durable dead-letter file."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from leads.crm_schema import CRMLeadEvent

LOGGER = logging.getLogger(__name__)


class CRMWebhook:
    def __init__(self, settings: Any) -> None:
        self.url: str | None = getattr(settings, "crm_webhook_url", None)
        self.secret: str | None = getattr(settings, "crm_webhook_secret", None)
        self.timeout = float(getattr(settings, "webhook_timeout_seconds", 3.0))
        self.dead_letter_path = Path(
            getattr(settings, "dead_letter_path", "var/lead_dead_letters.jsonl")
        )
        self._write_lock = asyncio.Lock()

    async def push(self, event: CRMLeadEvent) -> None:
        """Push one lead snapshot; retries are intentionally bounded to three attempts."""

        if not self.url:
            LOGGER.info("CRM webhook is not configured; lead retained only in session")
            return

        headers = {"content-type": "application/json"}
        if self.secret:
            headers["authorization"] = f"Bearer {self.secret}"

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
                retry=retry_if_exception_type((httpx.HTTPError, TimeoutError)),
                reraise=True,
            ):
                with attempt:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await client.post(
                            self.url,
                            json=event.model_dump(mode="json"),
                            headers=headers,
                        )
                        response.raise_for_status()
        except Exception as exc:
            LOGGER.error("CRM webhook exhausted retries: %s", exc)
            try:
                await self._dead_letter(event, exc)
            except Exception:
                LOGGER.exception("CRM dead-letter write also failed")

    async def _dead_letter(self, event: CRMLeadEvent, exc: Exception) -> None:
        row = event.model_dump(mode="json")
        row["failure"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        line = json.dumps(row, ensure_ascii=False) + "\n"
        async with self._write_lock:
            await asyncio.to_thread(self._append_line, line)

    def _append_line(self, line: str) -> None:
        self.dead_letter_path.parent.mkdir(parents=True, exist_ok=True)
        with self.dead_letter_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    async def health(self) -> dict[str, str]:
        return {"status": "configured" if self.url else "not_configured"}
