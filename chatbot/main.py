"""FastAPI lifecycle for the DegreeBaba conversational catalog service."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

import logging_setup
from config import Settings, get_settings
from data.accessor import safe_get
from data.loader import SAMPLE_CATALOG_PATH, CatalogStore
from leads.funnel import LeadFunnel
from leads.webhook import CRMWebhook
from llm.client import LLMClient, LLMUnavailable
from llm.prompts import grounded_answer_prompt
from nlu.callback_detector import is_callback_request
from nlu.intent import Intent, classify_intent
from nlu.mention_extractor import extract_mentions
from resilience.health import dependency_health
from resolver.clarifier import clarify
from resolver.focus_updater import update_focus
from resolver.pending_clarification import resolve_pending_clarification
from resolver.reference_resolver import resolve_reference
from response.builder import build_response
from response.templates import topic_from_message
from routing.fallback_handler import handle_fallback
from routing.knowledge_handler import handle_knowledge, knowledge_topic
from routing.router import Router, select_route
from schemas import ChatRequest, HealthResponse, ReindexResponse, ResponsePayload
from session.state import ConversationState
from session.store import SessionStore
from taxonomy.entity_matcher import EntityMatcher, configure_matcher
from taxonomy.index_builder import TaxonomyIndexes, build_indexes

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnResult:
    session_id: str
    state: ConversationState
    payload: ResponsePayload
    route: str
    synthesis_prompt: str | None = None


class ChatbotService:
    """Dependency-bound request pipeline, separated from the HTTP/SSE transport."""

    def __init__(
        self,
        *,
        settings: Settings,
        catalog: CatalogStore,
        indexes: TaxonomyIndexes,
        session_store: SessionStore,
        llm: LLMClient,
        lead_funnel: LeadFunnel,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.indexes = indexes
        self.matcher = configure_matcher(indexes, catalog)
        self.session_store = session_store
        self.llm = llm
        self.lead_funnel = lead_funnel
        # Handler output stays deterministic here. Broad factual overviews are streamed by
        # the transport from the same grounded fields instead of being buffered in a handler.
        self.router = Router(catalog, indexes.category_index, llm=None)
        self.reindex_lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        settings: Settings | None = None,
        *,
        catalog: CatalogStore | None = None,
        session_store: SessionStore | None = None,
        llm: LLMClient | None = None,
    ) -> ChatbotService:
        config = settings or get_settings()
        loaded_catalog = catalog or await CatalogStore.create(settings=config)
        if not len(loaded_catalog):
            await loaded_catalog.load()
        indexes = build_indexes(loaded_catalog)
        state_store = session_store or SessionStore(settings=config)
        llm_client = llm or LLMClient(config)
        funnel = LeadFunnel(CRMWebhook(config), config)
        return cls(
            settings=config,
            catalog=loaded_catalog,
            indexes=indexes,
            session_store=state_store,
            llm=llm_client,
            lead_funnel=funnel,
        )

    async def close(self) -> None:
        await self.lead_funnel.close()
        await self.session_store.close()

    async def reindex(self) -> int:
        """Refresh the catalog and atomically swap all request-time indexes."""

        async with self.reindex_lock:
            refreshed = CatalogStore(settings=self.settings)
            await refreshed.load(force=True)
            external_source_configured = bool(
                self.settings.catalog_url or self.settings.catalog_path
            )
            if external_source_configured and refreshed.source == str(SAMPLE_CATALOG_PATH):
                raise RuntimeError(
                    "Configured catalog source is unavailable; existing index retained"
                )
            indexes = await asyncio.to_thread(build_indexes, refreshed)
            matcher = EntityMatcher(indexes, refreshed)
            router = Router(refreshed, indexes.category_index, llm=None)

            self.catalog = refreshed
            self.indexes = indexes
            self.matcher = matcher
            self.router = router
            configure_matcher(indexes, refreshed)
            return len(refreshed)

    def _append_history(self, state: ConversationState, role: str, content: str) -> None:
        state.append_history(
            role,  # type: ignore[arg-type]
            content,
            limit=self.settings.session_history_limit,
        )

    def _synthesis_prompt(
        self,
        state: ConversationState,
        message: str,
        route: str,
        payload: ResponsePayload,
    ) -> str | None:
        if route != "factual" or topic_from_message(message) != "about":
            return None
        if "personalised help" in payload.text.casefold():
            return None
        if not self.llm.synthesis_configured or not state.focus.entity_id:
            return None
        entity = self.catalog.cache_in_state(state.focus.entity_id, state)
        if entity is None:
            return None
        facts = {
            "name": safe_get(entity, "program_name")
            or safe_get(entity, "spec_name")
            or safe_get(entity, "university_full_name")
            or safe_get(entity, "university_name"),
            "summary": safe_get(entity, "hero_description")
            or safe_get(entity, "about_content"),
            "fee": safe_get(entity, "total_fee") or safe_get(entity, "starting_fee"),
            "duration": safe_get(entity, "duration"),
        }
        grounded = {key: value for key, value in facts.items() if value is not None}
        return grounded_answer_prompt(message, grounded) if len(grounded) >= 2 else None

    async def _persist_result(
        self,
        state: ConversationState,
        payload: ResponsePayload,
    ) -> None:
        self._append_history(state, "assistant", payload.text)
        await self.session_store.set(state)

    async def process_turn(self, chat: ChatRequest) -> TurnResult:
        turn_start = time.monotonic()
        session_id = chat.session_id or str(uuid4())
        state = await self.session_store.get_or_create(session_id)
        state.turn_count += 1
        self._append_history(state, "user", chat.message)

        tl = logging_setup.TurnLogger(
            logging_setup.correlation_id(session_id, state.turn_count)
        )
        tl.info("chatbot.nlu", 'IN msg="%s"', chat.message)

        # Step 2: callback intent always wins and does not alter catalog focus.
        cb_match = is_callback_request(chat.message)
        tl.info("chatbot.nlu", "callback_detector: %s", "match" if cb_match else "no match")
        if cb_match:
            payload = self.lead_funnel.handle_callback(state, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: lead (callback)")
            return TurnResult(session_id, state, payload, "lead")

        # Step 3: an offered clarification is resolved before all ordinary NLU.
        pending = resolve_pending_clarification(
            chat.message,
            state,
            indexes=self.indexes,
            catalog=self.catalog,
        )
        pending_status = (
            f"resolved to {pending.entity_id}" if pending.resolved
            else (
                "pending, awaiting answer"
                if state.pending_clarification and not pending.new_topic
                else "none active"
            )
        )
        tl.info("chatbot.resolver", "pending_clarification: %s", pending_status)
        if pending.resolved:
            intent = Intent.FACTUAL
            route = select_route(state.focus, intent, state.pending_clarification)
            payload = await self.router.dispatch(state, intent, chat.message)
            payload = self.lead_funnel.augment(state, payload, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: %s (clarification resolved)", route)
            return TurnResult(
                session_id,
                state,
                payload,
                route,
                self._synthesis_prompt(state, chat.message, route, payload),
            )
        if state.pending_clarification is not None and not pending.new_topic:
            payload = await self.router.dispatch(state, Intent.FACTUAL, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: clarification (still pending)")
            return TurnResult(session_id, state, payload, "clarification")

        # A direct answer to the lead funnel remains a lead-only turn. Product questions
        # take the normal path and the lead ask is re-surfaced later.
        lead_reply_candidate = self.lead_funnel.is_standalone_lead_reply(
            state,
            chat.message,
            allow_lowercase_name=True,
        )
        product_markers = re.search(
            r"\b(?:about|accreditation|admission|career|choose|compare|course|degree|"
            r"duration|eligibility|explain|fees?|guidance|help|online|placement|program|"
            r"speciali[sz]ation|tell|university|validity|what|which|why|how)\b",
            chat.message,
            re.IGNORECASE,
        )
        preview_mentions = (
            extract_mentions(chat.message, self.matcher) if lead_reply_candidate else None
        )
        lead_reply_is_product = bool(
            product_markers
            or knowledge_topic(chat.message)
            or (preview_mentions and preview_mentions.has_explicit_mentions)
        )
        if lead_reply_candidate and not lead_reply_is_product:
            payload = self.lead_funnel.lead_reply_response(state, chat.message)
            await self._persist_result(state, payload)
            return TurnResult(session_id, state, payload, "lead")

        # Step 4: intent and three slot matchers remain independent until focus arbitration.
        previous_assistant = next(
            (
                item.get("content", "")
                for item in reversed(state.history[:-1])
                if item.get("role") == "assistant"
            ),
            "",
        )
        preference_followup = any(
            marker in previous_assistant.casefold()
            for marker in ("what matters most", "which direction is closer")
        ) and any(
            marker in chat.message.casefold()
            for marker in (
                "fee",
                "budget",
                "affordable",
                "placement",
                "special",
                "business",
                "management",
                "technology",
                "software",
                "computer",
            )
        )
        intent_start = time.monotonic()
        intent = (
            Intent.ADVISORY
            if preference_followup
            else await classify_intent(chat.message, self.llm)
        )
        intent_ms = (time.monotonic() - intent_start) * 1000
        tl.info("chatbot.nlu", "intent: %s (%.0fms)", intent.value, intent_ms)

        mentions = extract_mentions(chat.message, self.matcher)
        # Log per-slot mention results.
        for slot, candidates in [
            ("university", mentions.universities),
            ("category", mentions.courses),
            ("specialization", mentions.specializations),
        ]:
            if candidates:
                top = candidates[0]
                tl.info(
                    "chatbot.nlu",
                    "mention: %s=%s conf=%s layer=%s",
                    slot,
                    getattr(top, "entity_id", top),
                    getattr(top, "confidence", "?"),
                    getattr(top, "layer", "?"),
                )
            else:
                tl.info("chatbot.nlu", "mention: %s=none", slot)

        domain_topic = knowledge_topic(chat.message)
        if domain_topic and not mentions.has_explicit_mentions and not mentions.reference:
            payload = await handle_knowledge(
                state=state,
                message=chat.message,
                catalog=self.catalog,
                category_index=self.indexes.category_index,
                topic=domain_topic,
            )
            payload = self.lead_funnel.augment(state, payload, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: knowledge (domain_topic=%s)", domain_topic)
            return TurnResult(session_id, state, payload, "knowledge")

        # Capture focus-before snapshot for the log diff.
        focus_before = {
            "uni": state.focus.university,
            "cat": state.focus.category,
            "spec": state.focus.specialization,
            "eid": state.focus.entity_id,
        }

        resolve_reference(mentions, state, raw_input=chat.message)
        update = update_focus(
            state,
            mentions,
            intent=intent.value,
            catalog=self.catalog,
            indexes=self.indexes,
            category_index=self.indexes.category_index,
        )

        # --- Bug 2.3 fix: off-topic turns must not reuse stale focus ---
        # When no entities are mentioned and the message isn't referential,
        # distinguish bare follow-ups ("what is the fee?") from off-topic
        # messages ("what is the value of pi?") using domain keywords.
        # The heuristic intent classifier defaults to FACTUAL for everything
        # it doesn't recognise, so intent alone cannot distinguish off-topic.
        if (
            not mentions.has_explicit_mentions
            and not mentions.reference
            and topic_from_message(chat.message) == "about"
            and not domain_topic
        ):
            # "about" is the default/fallback topic — no domain keyword matched.
            # This is genuinely off-topic; clear focus to prevent stale answers.
            state.focus.clear()
            tl.info(
                "chatbot.resolver",
                "focus: cleared (off-topic, no entities, no domain keywords)",
            )

        decision = clarify(state, update, indexes=self.indexes)
        route = select_route(state.focus, intent, state.pending_clarification)

        # Log focus state change.
        focus_after = {
            "uni": state.focus.university,
            "cat": state.focus.category,
            "spec": state.focus.specialization,
            "eid": state.focus.entity_id,
        }
        tl.info(
            "chatbot.resolver",
            "focus: before=%s after=%s",
            focus_before,
            focus_after,
        )
        tl.info("chatbot.routing", "route: %s", route)

        topic = "accreditation" if domain_topic else None
        if route == "knowledge" and topic is None:
            payload = await handle_fallback(
                state=state,
                message=chat.message,
                catalog=self.catalog,
                category_index=self.indexes.category_index,
            )
            route = "fallback"
        else:
            payload = await self.router.dispatch(
                state,
                intent,
                chat.message,
                categories=update.comparison_categories,
                topic=topic,
            )

        if decision.needs_clarification:
            payload = payload.model_copy(
                update={
                    "text": decision.text or payload.text,
                    "suggested_chips": list(decision.labels) or payload.suggested_chips,
                }
            )
        else:
            payload = self.lead_funnel.augment(state, payload, chat.message)

        await self._persist_result(state, payload)

        turn_ms = (time.monotonic() - turn_start) * 1000
        is_templated = not self._synthesis_prompt(state, chat.message, route, payload)
        tl.info(
            "chatbot.routing",
            "response: templated=%s latency=%.0fms",
            is_templated,
            turn_ms,
        )
        lead_field = state.lead.last_asked_field
        tl.info(
            "chatbot.leads",
            "lead: %s",
            f"last asked={lead_field}" if lead_field else "no ask this turn",
        )

        return TurnResult(
            session_id,
            state,
            payload,
            route,
            self._synthesis_prompt(state, chat.message, route, payload),
        )


def _sse(event: str, data: dict[str, Any]) -> bytes:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n".encode()


def _payload_event(result: TurnResult, payload: ResponsePayload | None = None) -> bytes:
    value = payload or result.payload
    data = {"session_id": result.session_id, **value.model_dump(mode="json")}
    return _sse("response", data)


async def _event_stream(service: ChatbotService, result: TurnResult):
    if not result.synthesis_prompt:
        # Templated answers produce exactly one immediate full-payload event.
        yield _payload_event(result)
        return

    tokens: list[str] = []
    try:
        async for token in service.llm.stream_synthesis(result.synthesis_prompt):
            tokens.append(token)
            yield _sse("token", {"session_id": result.session_id, "token": token})
    except LLMUnavailable:
        # The deterministic payload was already built and persisted before streaming.
        yield _payload_event(result)
        return

    text = "".join(tokens).strip()
    if not text:
        yield _payload_event(result)
        return
    final_payload = result.payload.model_copy(update={"text": text})
    # Focus/session state was persisted before streaming. Do not write this older whole-state
    # snapshot after a slow stream: a newer turn for the same session may already exist.
    yield _payload_event(result, final_payload)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging_setup.configure(level=settings.log_level, log_format=settings.log_format)
    app.state.service = await ChatbotService.create(settings)
    try:
        yield
    finally:
        await app.state.service.close()


app = FastAPI(
    title="DegreeBaba Chatbot",
    version="1.0.0",
    description="Catalog-grounded university and course assistant",
    lifespan=lifespan,
)


@app.post(
    "/chat",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_endpoint(chat: ChatRequest, request: Request) -> StreamingResponse:
    service: ChatbotService = request.app.state.service
    try:
        result = await service.process_turn(chat)
    except Exception:
        LOGGER.exception("Unhandled chat pipeline failure; returning safe fallback")
        session_id = chat.session_id or str(uuid4())
        state = ConversationState(session_id=session_id)
        payload = build_response(
            "I couldn't complete that lookup just now. Which university or course should I check?",
            suggested_chips=["Explore MBA", "Browse universities"],
            cta={"label": "Talk to a counsellor", "action": "lead_capture"},
        )
        result = TurnResult(session_id, state, payload, "fallback")
    return StreamingResponse(
        _event_stream(service, result),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "x-accel-buffering": "no",
            "x-session-id": result.session_id,
        },
    )


@app.get("/health", response_model=HealthResponse)
async def health_endpoint(request: Request) -> dict[str, Any]:
    service: ChatbotService = request.app.state.service
    return await dependency_health(service.session_store, service.catalog, service.llm)


@app.post("/admin/reindex", response_model=ReindexResponse)
async def reindex_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
) -> ReindexResponse:
    service: ChatbotService = request.app.state.service
    expected = service.settings.admin_api_key
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    try:
        count = await service.reindex()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        LOGGER.exception("Catalog reindex failed; existing index retained")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Catalog reindex failed; existing index retained",
        ) from exc
    return ReindexResponse(entity_count=count)


__all__ = ["ChatbotService", "TurnResult", "app"]
