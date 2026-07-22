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
