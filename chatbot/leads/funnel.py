"""The single finite-state authority for progressive lead capture."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from leads.crm_schema import CRMLeadEvent
from leads.webhook import CRMWebhook
from schemas import CTA, ResponsePayload

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{9})(?!\d)")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,49}$")
QUESTION_WORDS = {
    "about",
    "amity",
    "analytics",
    "browse",
    "compare",
    "duration",
    "eligibility",
    "what",
    "which",
    "where",
    "when",
    "why",
    "how",
    "fee",
    "fees",
    "finance",
    "ignou",
    "jain",
    "know",
    "lpu",
    "manipal",
    "mba",
    "mca",
    "nmims",
    "course",
    "show",
    "tell",
    "university",
    "program",
    "provide",
}
FIELD_ASKS = {
    "name": "What name should our counsellor use?",
    "phone": "What phone number can our counsellor reach you on?",
    "email": "What email address should we send the details to?",
}


class LeadFunnel:
    """Capture one field at a time and publish each new snapshot asynchronously."""

    def __init__(self, webhook: CRMWebhook, settings: Any) -> None:
        self.webhook = webhook
        self.start_after_turn = int(getattr(settings, "lead_prompt_after_turn", 3))
        self.prompt_interval = int(getattr(settings, "lead_prompt_interval", 2))
        self._last_sent: dict[str, tuple[str | None, str | None, str | None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _next_missing(lead: Any) -> str | None:
        for field in ("name", "phone", "email"):
            if not getattr(lead, field, None):
                return field
        return None

    @staticmethod
    def _extract(
        message: str,
        expected: str | None = None,
        *,
        allow_lowercase_name: bool = False,
        allow_name: bool = True,
    ) -> dict[str, str]:
        captured: dict[str, str] = {}
        email = EMAIL_RE.search(message)
        phone = PHONE_RE.search(re.sub(r"[()\s-]", "", message))
        if email:
            captured["email"] = email.group(0).lower()
        if phone:
            captured["phone"] = phone.group(1)
        if expected == "name" and allow_name and not captured:
            explicit_name_prefix = bool(
                re.match(r"^(?:i(?:'m| am)|my name is|this is)\s+", message.strip(), flags=re.I)
            )
            value = re.sub(
                r"^(?:i(?:'m| am)|my name is|this is)\s+",
                "",
                message.strip(),
                flags=re.I,
            )
            words = {word.lower() for word in re.findall(r"[A-Za-z]+", value)}
            name_words = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?", value)
            word_count = len(name_words)
            has_name_casing = all(
                word[:1].isupper() or word.isupper() for word in name_words
            )
            looks_like_name = (
                NAME_RE.fullmatch(value)
                and 1 <= word_count <= 4
                and (has_name_casing or allow_lowercase_name)
                and not words.intersection(QUESTION_WORDS)
                and "?" not in message
            )
            if looks_like_name or (
                explicit_name_prefix and NAME_RE.fullmatch(value) and 1 <= word_count <= 5
            ):
                captured["name"] = " ".join(part.capitalize() for part in value.split())
        return captured

    def capture(
        self,
        state: Any,
        message: str,
        *,
        allow_lowercase_name: bool = False,
        allow_name: bool = True,
    ) -> list[str]:
        """Capture explicit contact data or the one field most recently requested."""

        expected = getattr(state.lead, "last_asked_field", None)
        found = self._extract(
            message,
            expected,
            allow_lowercase_name=allow_lowercase_name,
            allow_name=allow_name,
        )
        changed: list[str] = []
        for field, value in found.items():
            if value and getattr(state.lead, field, None) != value:
                setattr(state.lead, field, value)
                changed.append(field)
        if changed:
            state.lead.last_asked_field = None
            self._schedule_push(state, changed)
        return changed

    def is_standalone_lead_reply(
        self,
        state: Any,
        message: str,
        *,
        allow_lowercase_name: bool = False,
    ) -> bool:
        """Identify a direct answer to the previous single-field ask."""

        expected = getattr(state.lead, "last_asked_field", None)
        return bool(
            expected
            and self._extract(
                message,
                expected,
                allow_lowercase_name=allow_lowercase_name,
            )
        )

    def _schedule_push(self, state: Any, changed: list[str]) -> None:
        snapshot = (state.lead.name, state.lead.phone, state.lead.email)
        if self._last_sent.get(state.session_id) == snapshot:
            return
        self._last_sent[state.session_id] = snapshot
        focus = getattr(state, "focus", None)
        context = focus.model_dump(exclude_none=True) if hasattr(focus, "model_dump") else {}
        event = CRMLeadEvent(
            session_id=state.session_id,
            name=state.lead.name,
            phone=state.lead.phone,
            email=state.lead.email,
            captured_fields=changed,
            context=context,
        )
        task = asyncio.create_task(self.webhook.push(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def handle_callback(self, state: Any, message: str) -> ResponsePayload:
        """Short-circuit an explicit human-contact request into the funnel."""

        self.capture(state, message)
        field = self._next_missing(state.lead)
        if field is None:
            text = (
                "Thanks — your details are saved. "
                "A DegreeBaba counsellor can contact you shortly."
            )
            state.lead.last_asked_field = None
        else:
            state.lead.last_asked_field = field
            text = f"Absolutely — I can help arrange that. {FIELD_ASKS[field]}"
        return ResponsePayload(
            text=text,
            suggested_chips=["Keep exploring programs"],
            cta=CTA(label="Talk to a counsellor", action="lead_capture"),
        )

    def lead_reply_response(self, state: Any, message: str) -> ResponsePayload:
        changed = self.capture(state, message, allow_lowercase_name=True)
        field = self._next_missing(state.lead)
        if field:
            state.lead.last_asked_field = field
            saved = changed[0] if changed else "detail"
            text = f"Thanks, I've saved your {saved}. {FIELD_ASKS[field]}"
        else:
            text = "Thanks — I have your details. A DegreeBaba counsellor can contact you shortly."
        return ResponsePayload(
            text=text,
            suggested_chips=["Explore MBA", "Compare programs"],
            cta=CTA(label="Continue exploring", action="continue_chat"),
        )

    def augment(self, state: Any, payload: ResponsePayload, message: str) -> ResponsePayload:
        """Optionally add one non-blocking ask after the product answer."""

        self.capture(state, message, allow_name=False)
        if self._next_missing(state.lead) is None:
            return payload
        if state.turn_count < self.start_after_turn:
            return payload
        if state.turn_count % max(self.prompt_interval, 1) != 0:
            return payload

        field = self._next_missing(state.lead)
        if field is None:
            return payload
        state.lead.last_asked_field = field
        return payload.model_copy(
            update={
                "text": (
                    f"{payload.text}\n\nIf you'd like personalised help, "
                    f"{FIELD_ASKS[field].lower()}"
                ),
                "cta": payload.cta
                or CTA(label="Talk to a counsellor", action="lead_capture"),
            }
        )

    async def close(self, *, timeout: float = 8.0) -> None:
        """Drain in-flight CRM tasks during graceful application shutdown."""

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
