"""The single finite-state authority for progressive lead capture."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Literal

from leads.crm_schema import CRMLeadEvent
from leads.webhook import CRMWebhook
from response.cta import lead_capture_cta
from schemas import CTA, ResponsePayload

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{9})(?!\d)")
# A requested phone number is validated by the shape promised in the prompt. Keep the
# stricter Indian-mobile pattern above for unsolicited numbers found in ordinary prose.
PROMPTED_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?(\d{10})(?!\d)")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,49}$")
LEAD_DEFERRAL_RE = re.compile(
    r"^\s*(?:skip|not\s+now|maybe\s+later|later|no\s+thanks?|prefer\s+not\s+to)\s*[.!]?\s*$",
    re.IGNORECASE,
)
LEAD_CHAT_ESCAPE_RE = re.compile(
    r"^\s*(?:browse|explore|continue|keep\s+exploring)(?:\s+(?:universit(?:y|ies)|courses?|programs?|speciali[sz]ations?))?\s*[.!]?\s*$",
    re.IGNORECASE,
)
LEAD_CANCEL_RE = re.compile(
    r"^\s*(?:cancel|stop|exit|skip|never\s*mind|not\s+now|maybe\s+later|"
    r"prefer\s+not\s+to|no\s+thanks?)"
    r"(?:\s+(?:the\s+)?(?:callback(?:\s+form)?|lead|request|form|flow))?\s*[.!]?\s*$",
    re.IGNORECASE,
)
LEAD_RESTART_RE = re.compile(
    r"^\s*(?:restart|reset|start\s+over|begin\s+again)"
    r"(?:\s+(?:the\s+)?(?:callback(?:\s+form)?|lead|request|form|flow|details?))?"
    r"\s*[.!]?\s*$",
    re.IGNORECASE,
)
QUESTION_WORDS = {
    "about",
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
    "know",
    "course",
    "show",
    "tell",
    "university",
    "program",
    "provide",
    "specialization",
}
FIELD_ASKS = {
    "name": "What name should our counsellor use?",
    "phone": "What phone number can our counsellor reach you on?",
    "email": "What email address should we send the details to?",
}
INVALID_FIELD_ASKS = {
    "name": (
        "That doesn't look like a valid name — could you share the name you'd like "
        "our counsellor to use?"
    ),
    "phone": "That doesn't look like a valid phone number — could you share a 10-digit number?",
    "email": (
        "That doesn't look like a valid email address — could you share an address "
        "such as name@example.com?"
    ),
}


@dataclass(frozen=True, slots=True)
class PendingLeadAnswer:
    """A non-mutating validation result for the field currently awaiting an answer."""

    field: str
    values: dict[str, str]

    @property
    def valid(self) -> bool:
        return self.field in self.values


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
    def lifecycle_command(message: str) -> Literal["cancel", "restart"] | None:
        """Return an exact lead-flow command before any contact-field parsing.

        These commands are deliberately whole-message matches. A sentence that merely
        contains a word such as ``restart`` remains ordinary chat, while a standalone
        command can never be accepted as a person's name.
        """

        if LEAD_CANCEL_RE.fullmatch(message):
            return "cancel"
        if LEAD_RESTART_RE.fullmatch(message):
            return "restart"
        return None

    @staticmethod
    def is_active(state: Any) -> bool:
        """Return the explicit lifecycle flag; missing fields alone are not activity."""

        return bool(getattr(getattr(state, "lead", None), "active", False))

    @staticmethod
    def _set_active(state: Any, active: bool) -> None:
        lead = state.lead
        if hasattr(lead, "active"):
            lead.active = active

    def start(self, state: Any) -> str | None:
        """Activate or resume explicit collection and return the next missing field."""

        self._set_active(state, True)
        field = self._next_missing(state.lead)
        state.lead.last_asked_field = field
        if field is None:
            self.complete(state)
        return field

    def complete(self, state: Any) -> None:
        """End collection while preserving the completed contact snapshot."""

        deactivate = getattr(state.lead, "deactivate", None)
        if callable(deactivate):
            deactivate()
            return
        self._set_active(state, False)
        state.lead.last_asked_field = None

    def cancel(self, state: Any) -> ResponsePayload:
        """Cancel an active flow without treating the command as submitted data."""

        self.complete(state)
        return ResponsePayload(
            text="No problem — the callback request has been cancelled.",
            suggested_chips=["Browse universities", "Browse course categories"],
            cta=None,
        )

    def restart(self, state: Any) -> ResponsePayload:
        """Clear any partial contact values and restart from the name field."""

        restart = getattr(state.lead, "restart", None)
        if callable(restart):
            restart()
        else:
            state.lead.name = None
            state.lead.phone = None
            state.lead.email = None
            self._set_active(state, True)
            state.lead.last_asked_field = "name"
        return ResponsePayload(
            text=f"Of course — let's start over. {FIELD_ASKS['name']}",
            suggested_chips=["Cancel callback request"],
            cta=CTA(**lead_capture_cta(label="Talk to a counsellor", action="lead_capture")),
        )

    def handle_lifecycle_command(
        self,
        state: Any,
        message: str,
    ) -> ResponsePayload | None:
        """Apply a cancel/restart command before callers inspect a pending answer."""

        command = self.lifecycle_command(message)
        if command == "cancel":
            return self.cancel(state) if self.is_active(state) else None
        if command == "restart":
            return self.restart(state) if self.is_active(state) else None
        return None

    @staticmethod
    def _extract(
        message: str,
        expected: str | None = None,
        *,
        allow_lowercase_name: bool = False,
        allow_name: bool = True,
    ) -> dict[str, str]:
        # Lifecycle commands always win over the permissive name shape. In
        # particular, ``cancel`` and ``restart`` must never become lead names.
        if LeadFunnel.lifecycle_command(message) is not None:
            return {}
        captured: dict[str, str] = {}
        email = EMAIL_RE.search(message)
        compact_message = re.sub(r"[()\s-]", "", message)
        phone_pattern = PROMPTED_PHONE_RE if expected == "phone" else PHONE_RE
        phone = phone_pattern.search(compact_message)
        if email:
            captured["email"] = email.group(0).lower()
        if phone:
            captured["phone"] = phone.group(1)
        if (
            expected == "name"
            and allow_name
            and not captured
            and not LEAD_DEFERRAL_RE.fullmatch(message)
        ):
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

    def inspect_pending_answer(
        self,
        state: Any,
        message: str,
        *,
        allow_lowercase_name: bool = True,
    ) -> PendingLeadAnswer | None:
        """Validate a pending field without mutating the session or firing the webhook."""

        expected = getattr(state.lead, "last_asked_field", None)
        if not expected:
            return None
        return PendingLeadAnswer(
            field=expected,
            values=self._extract(
                message,
                expected,
                allow_lowercase_name=allow_lowercase_name,
            ),
        )

    @staticmethod
    def is_deferral(message: str) -> bool:
        """Return whether a pending lead ask must yield to normal product chat."""

        return bool(
            LEAD_DEFERRAL_RE.fullmatch(message) or LEAD_CHAT_ESCAPE_RE.fullmatch(message)
        )

    def commit_pending_answer(
        self,
        state: Any,
        answer: PendingLeadAnswer,
    ) -> list[str]:
        """Commit a previously inspected valid answer and publish its CRM snapshot."""

        if not answer.valid:
            return []
        changed: list[str] = []
        for field, value in answer.values.items():
            if value and getattr(state.lead, field, None) != value:
                setattr(state.lead, field, value)
                changed.append(field)
        state.lead.last_asked_field = None
        if changed:
            self._schedule_push(state, changed)
        return changed

    @staticmethod
    def invalid_pending_response(field: str) -> ResponsePayload:
        """Build the field-specific retry that must never fall through to discovery."""

        return ResponsePayload(
            text=INVALID_FIELD_ASKS[field],
            suggested_chips=[],
            cta=CTA(**lead_capture_cta(label="Talk to a counsellor", action="lead_capture")),
        )

    def captured_reply_response(
        self,
        state: Any,
        changed: list[str],
    ) -> ResponsePayload:
        """Acknowledge an already committed standalone answer without re-extracting it."""

        field = self._next_missing(state.lead)
        if field:
            state.lead.last_asked_field = field
            saved = changed[0] if changed else "detail"
            text = f"Thanks, I've saved your {saved}. {FIELD_ASKS[field]}"
        else:
            self.complete(state)
            text = (
                "Thanks — I have your details. "
                "A DegreeBaba counsellor can contact you shortly."
            )
        return ResponsePayload(
            text=text,
            suggested_chips=[],
            cta=CTA(label="Continue exploring", action="continue_chat"),
        )

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

    def capture_phone_only(
        self,
        state: Any,
        phone: str,
        *,
        source: str | None = None,
    ) -> str:
        """Capture the widget's single-field lead form through the existing CRM path."""

        compact = re.sub(r"[()\s-]", "", str(phone or ""))
        match = PHONE_RE.fullmatch(compact)
        if match is None:
            raise ValueError("phone must be a valid 10-digit Indian mobile number")
        normalized = match.group(1)
        state.lead.phone = normalized
        self.complete(state)
        self._schedule_push(
            state,
            ["phone"],
            extra_context={"widget_source": source} if source else None,
        )
        return normalized

    def _schedule_push(
        self,
        state: Any,
        changed: list[str],
        *,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        snapshot = (state.lead.name, state.lead.phone, state.lead.email)
        if self._last_sent.get(state.session_id) == snapshot:
            return
        self._last_sent[state.session_id] = snapshot
        focus = getattr(state, "focus", None)
        context = focus.model_dump(exclude_none=True) if hasattr(focus, "model_dump") else {}
        if extra_context:
            context.update(extra_context)
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

        self.start(state)
        # The trigger phrase itself (for example "Request Callback") is not a
        # field answer. Phone/email embedded in the same turn remain safe to
        # capture, while a name is collected by the dedicated next step.
        self.capture(state, message, allow_name=False)
        field = self._next_missing(state.lead)
        if field is None:
            text = (
                "Thanks — your details are saved. "
                "A DegreeBaba counsellor can contact you shortly."
            )
            self.complete(state)
        else:
            self._set_active(state, True)
            state.lead.last_asked_field = field
            text = f"Absolutely — I can help arrange that. {FIELD_ASKS[field]}"
        return ResponsePayload(
            text=text,
            suggested_chips=["Keep exploring programs"],
            cta=CTA(**lead_capture_cta(label="Talk to a counsellor", action="lead_capture")),
        )

    def lead_reply_response(self, state: Any, message: str) -> ResponsePayload:
        changed = self.capture(state, message, allow_lowercase_name=True)
        field = self._next_missing(state.lead)
        if field:
            self._set_active(state, True)
            state.lead.last_asked_field = field
            saved = changed[0] if changed else "detail"
            text = f"Thanks, I've saved your {saved}. {FIELD_ASKS[field]}"
        else:
            self.complete(state)
            text = "Thanks — I have your details. A DegreeBaba counsellor can contact you shortly."
        return ResponsePayload(
            text=text,
            suggested_chips=["Browse programs", "Compare programs"],
            cta=CTA(label="Continue exploring", action="continue_chat"),
        )

    def augment(self, state: Any, payload: ResponsePayload, message: str) -> ResponsePayload:
        """Compatibility no-op: ordinary chat never starts or advances lead capture."""

        del state, message
        return payload

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
