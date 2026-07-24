"""Phone-first lead capture used by guided conversion cards and tools."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any

from leads.crm_schema import CRMLeadEvent
from leads.webhook import CRMWebhook

PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{9})(?!\d)")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,49}$")
# §3.2 obvious placeholders: all-identical digits, or a strict ascending/
# descending run. Soft-blocked with a re-prompt, not a hard rejection.
_SEQUENTIAL = ("0123456789", "9876543210")


def _looks_fake(digits: str) -> bool:
    if len(set(digits)) == 1:
        return True
    return any(digits in run for run in _SEQUENTIAL)


class LeadFunnel:
    """Validate one guided lead form and publish it asynchronously."""

    def __init__(self, webhook: CRMWebhook, settings: Any) -> None:
        del settings
        self.webhook = webhook
        self._last_sent: dict[str, tuple[str | None, str | None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def capture_phone_only(
        self,
        state: Any,
        phone: str,
        *,
        name: str | None = None,
        require_name: bool = False,
        source: str | None = None,
        extra_context: Mapping[str, Any] | None = None,
    ) -> str:
        compact = re.sub(r"[()\s-]", "", str(phone or ""))
        match = PHONE_RE.fullmatch(compact)
        if match is None:
            raise ValueError("phone must be a valid 10-digit Indian mobile number")
        normalized_name: str | None = None
        if name is not None:
            candidate = " ".join(str(name).split())
            if NAME_RE.fullmatch(candidate) is None or not 1 <= len(candidate.split()) <= 5:
                raise ValueError("name must contain 2-50 letters")
            normalized_name = " ".join(part.capitalize() for part in candidate.split())
        if require_name and not (normalized_name or state.lead.name):
            raise ValueError("name is required to reveal the tool result")
        changed = ["phone"]
        if normalized_name and normalized_name != state.lead.name:
            state.lead.name = normalized_name
            changed.insert(0, "name")
        state.lead.phone = match.group(1)
        context = dict(extra_context or {})
        if source:
            context["widget_source"] = source
        self._schedule_push(state, changed, context or None)
        return state.lead.phone

    def submit(
        self,
        state: Any,
        *,
        name: str,
        phone: str,
        source: str | None = None,
        extra_context: Mapping[str, Any] | None = None,
    ) -> str:
        """§3.4 single-payload entry point for the inline form.

        Reuses capture_phone_only's normalisation, dedupe, CRM envelope, webhook
        dispatch, retry and dead-letter path unchanged; only adds the placeholder
        soft-block and the §4 captured_at stamp.
        """

        compact = re.sub(r"[()\s-]", "", str(phone or ""))
        match = PHONE_RE.fullmatch(compact)
        if match is not None and _looks_fake(match.group(1)):
            raise ValueError("that number looks like a placeholder — please re-enter your mobile")
        captured = self.capture_phone_only(
            state,
            phone,
            name=name,
            require_name=True,
            source=source,
            extra_context=extra_context,
        )
        if state.lead.captured_at is None:
            from datetime import datetime, timezone

            state.lead.captured_at = datetime.now(timezone.utc).isoformat()
        return captured

    def _schedule_push(
        self,
        state: Any,
        changed: list[str],
        extra_context: dict[str, Any] | None,
    ) -> None:
        snapshot = (state.lead.name, state.lead.phone)
        if self._last_sent.get(state.session_id) == snapshot:
            return
        self._last_sent[state.session_id] = snapshot
        context = state.focus.model_dump(exclude_none=True)
        if extra_context:
            context.update(extra_context)
        event = CRMLeadEvent(
            session_id=state.session_id,
            name=state.lead.name,
            phone=state.lead.phone,
            captured_fields=changed,
            context=context,
        )
        task = asyncio.create_task(self.webhook.push(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self, *, timeout: float = 8.0) -> None:
        if not self._tasks:
            return
        tasks = tuple(self._tasks)
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout)
        except TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
