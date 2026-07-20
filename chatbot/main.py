"""FastAPI lifecycle for the DegreeBaba conversational catalog service."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Body, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse

import logging_setup
from advisor.flow import advisor_can_consume, handle_advisor_turn
from analytics import (
    FLOW_ABANDONED,
    LEAD_CAPTURED,
    SESSION_START,
    TOOL_COMPLETED,
    TOOL_LEAD_GATE,
    TOOL_PARTIAL_REVEAL,
    TOOL_STARTED,
    TOOL_STEP,
    AnalyticsEmitter,
    build_chip_shown,
    build_event,
)
from config import Settings, get_settings
from data.accessor import safe_get, validate_focus
from data.loader import SAMPLE_CATALOG_PATH, CatalogStore
from funnel import ChipEngine, ChipMapStore, JourneyEngine
from leads.funnel import LeadFunnel
from leads.webhook import CRMWebhook
from llm.client import LLMClient, LLMUnavailable
from llm.prompts import grounded_answer_prompt
from nlu.action_classifier import Action, has_deferred_clarification, tool_id_from_message
from nlu.action_classifier import classify as classify_action
from nlu.action_classifier import mention_summary as summarize_mentions
from nlu.callback_detector import is_callback_request
from nlu.intent import Intent, decide_action, heuristic_intent, should_use_reasoning_llm
from nlu.mention_extractor import extract_mentions
from presentation import enrich_response
from presentation.chips import catalog_chip_context, followup_payload, opening_payload
from presentation.experience import (
    catalog_options,
    context_from_entity,
    context_from_state,
    finder_results,
    resolve_page_entity,
)
from presentation.guided_navigation import guide_catalog, guide_comparison, guide_context
from resilience.health import dependency_health
from resilience.intent_metrics import ActionSource, IntentMetrics
from resilience.intent_metrics import intent_metrics as process_intent_metrics
from resolver.clarifier import candidate_label, clarify
from resolver.focus_updater import update_focus
from resolver.pending_clarification import resolve_pending_clarification
from resolver.reference_resolver import resolve_reference
from response.builder import build_response
from response.cta import lead_capture_cta
from response.templates import entity_not_found_answer, topic_from_message
from routing.fallback_handler import handle_fallback
from routing.knowledge_handler import handle_knowledge, knowledge_topic
from routing.router import Router, action_from_intent, select_route
from routing.tools import EscapeSignals, ToolEngine, ToolResult, ToolsContentStore
from routing.unsupported_handler import handle_unsupported_entity
from routing.validation_handler import handle_invalid_combination
from schemas import (
    CatalogOptionsResponse,
    ChatRequest,
    ContextClearRequest,
    ContextClearResponse,
    FinderRequest,
    FinderResponse,
    GuidedChipRequest,
    HealthResponse,
    PageContextResponse,
    ReindexResponse,
    ResponseContext,
    ResponsePayload,
    WidgetAnalyticsRequest,
    WidgetLeadRequest,
    WidgetLeadResponse,
)
from session.navigation import (
    PAGE_STEPS,
    advance_answer_navigation,
    advance_navigation,
    navigation_payload,
    sync_page_navigation,
)
from session.state import ConversationState, NavigationStep, hydrate_focus_concepts
from session.store import SessionStore
from taxonomy.entity_matcher import EntityMatcher, configure_matcher
from taxonomy.index_builder import TaxonomyIndexes, build_indexes
from widget.config import (
    InvalidSiteKeyError,
    UnknownSiteKeyError,
    WidgetConfigLoadError,
    WidgetConfigStore,
)

LOGGER = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent
WIDGET_DIR = APP_DIR / "widget"


def _allowed_widget_origins(value: str) -> list[str]:
    origins = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return ["*"] if "*" in origins else origins


def _looks_like_product_turn(
    message: str,
    mentions: Any,
    *,
    action_hint: Action | None = None,
    heuristic: Intent = Intent.FACTUAL,
) -> bool:
    """Use catalog/NLU evidence, not a hardcoded list of entity names."""

    return bool(
        "?" in message
        or knowledge_topic(message)
        or getattr(mentions, "has_explicit_mentions", False)
        or getattr(mentions, "attributes", ())
        or getattr(mentions, "unknown_entities", ())
        or getattr(mentions, "reference", None)
        or action_hint is not None
        or heuristic is not Intent.FACTUAL
    )


def _looks_like_lead_attempt(field: str, message: str) -> bool:
    """Distinguish a malformed field answer from an unrelated chat turn."""

    value = message.strip()
    if field == "phone":
        return bool(re.search(r"\d", value))
    if field == "email":
        return "@" in value
    return bool(
        value
        and "?" not in value
        and len(value.split()) <= 5
        and not re.match(
            r"^(?:tell|show|browse|explore|compare|what|which|how|why|list)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _acknowledge_partial_match(payload: ResponsePayload, unresolved: list[str]) -> ResponsePayload:
    if not unresolved:
        return payload
    missing = (
        unresolved[0]
        if len(unresolved) == 1
        else ", ".join(unresolved[:-1]) + f" and {unresolved[-1]}"
    )
    return payload.model_copy(
        update={
            "text": (
                f"I couldn't find {missing} in the published catalog. "
                "I did match the rest of your request, so here's the available "
                f"catalog information:\n\n{payload.text}"
            )
        }
    )


_ENTITY_LOOKUP_RE = re.compile(
    r"\b(?:tell\s+me\s+about|information\s+(?:about|on)|"
    r"uni(?:versity)?|college|institute|course|program|degree)\b",
    re.IGNORECASE,
)


def _unresolved_subject(message: str) -> str:
    subject = re.sub(
        r"^\s*(?:please\s+)?(?:tell\s+me\s+about|give\s+me\s+information\s+"
        r"(?:about|on)|information\s+(?:about|on))\s+",
        "",
        message,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n?.!,")
    return subject or message.strip(" \t\r\n?.!,")


def _unresolved_payload(
    message: str,
    mentions: Any,
    indexes: TaxonomyIndexes,
) -> ResponsePayload:
    medium = next(
        (
            candidate
            for candidates in (
                mentions.universities,
                mentions.courses,
                mentions.specializations,
            )
            for candidate in candidates
            if getattr(candidate, "confidence", None) == "MEDIUM"
        ),
        None,
    )
    suggestion = candidate_label(medium, indexes) if medium is not None else None
    if suggestion or _ENTITY_LOOKUP_RE.search(message):
        text = entity_not_found_answer(_unresolved_subject(message), suggestion)
    else:
        text = (
            "I'm not sure what you're asking yet. Could you share a university name, "
            "a course or specialization, or say that you'd like human help?"
        )
    return build_response(
        text,
        suggested_chips=["Browse course categories", "Browse universities", "Talk to a counsellor"],
    )


def _has_focus(state: ConversationState) -> bool:
    return any(
        (
            state.focus.entity_id,
            state.focus.university_concept,
            state.focus.course_concept,
            state.focus.specialization_concept,
            state.focus.university,
            state.focus.category,
            state.focus.specialization,
        )
    )


def _resolver_intent(action: Action) -> str:
    """Keep focus_updater's stable legacy intent contract unchanged."""

    return {
        Action.COMPARE: Intent.COMPARISON.value,
        Action.RECOMMEND: Intent.ADVISORY.value,
        Action.DISCOVERY: Intent.DISCOVERY.value,
        Action.LIST_PROVIDERS: Intent.DISCOVERY.value,
        Action.LIST_SPECIALIZATIONS: Intent.DISCOVERY.value,
        Action.CHITCHAT: Intent.CHITCHAT.value,
        Action.UNRELATED: Intent.UNRELATED.value,
    }.get(action, Intent.FACTUAL.value)


def _presentation_operand_ids(*groups: Any) -> tuple[str, ...]:
    """Select one concrete resolved comparison level for card presentation."""

    for group in groups:
        values: list[str] = []
        for item in group or ():
            if isinstance(item, (str, int)):
                entity_id = str(item)
            elif isinstance(item, dict):
                entity_id = str(item.get("entity_id") or item.get("id") or "")
            else:
                entity_id = str(getattr(item, "entity_id", None) or getattr(item, "id", None) or "")
            if entity_id and entity_id not in values:
                values.append(entity_id)
        if len(values) >= 2:
            return tuple(values[:3])
    return ()


@dataclass(slots=True)
class TurnResult:
    session_id: str
    state: ConversationState
    payload: ResponsePayload
    route: str
    synthesis_prompt: str | None = None
    presentation_operands: tuple[str, ...] = ()


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
        chip_map: ChipMapStore | None = None,
        analytics: AnalyticsEmitter | None = None,
        tools: ToolEngine | None = None,
        intent_metrics: IntentMetrics = process_intent_metrics,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.indexes = indexes
        self.matcher = configure_matcher(indexes, catalog)
        self.session_store = session_store
        self.llm = llm
        self.lead_funnel = lead_funnel
        self.chip_map = chip_map or ChipMapStore(settings.chip_map_path)
        self.journey_engine = JourneyEngine(self.chip_map)
        self.chip_engine = ChipEngine(self.chip_map)
        self.analytics = analytics or AnalyticsEmitter(settings)
        self.tools = tools or ToolEngine(
            ToolsContentStore(settings.tools_content_path),
            catalog=catalog,
            entity_resolver=self._resolve_tool_entity,
            program_lookup=self._lookup_tool_programs,
        )
        self.intent_metrics = intent_metrics
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
        intent_metrics: IntentMetrics | None = None,
    ) -> ChatbotService:
        config = settings or get_settings()
        loaded_catalog = catalog or await CatalogStore.create(settings=config)
        if not len(loaded_catalog):
            await loaded_catalog.load()
        indexes = build_indexes(loaded_catalog)
        state_store = session_store or SessionStore(settings=config)
        llm_client = llm or LLMClient(config)
        funnel = LeadFunnel(CRMWebhook(config), config)
        chip_map = ChipMapStore(config.chip_map_path)
        analytics = AnalyticsEmitter(config)
        return cls(
            settings=config,
            catalog=loaded_catalog,
            indexes=indexes,
            session_store=state_store,
            llm=llm_client,
            lead_funnel=funnel,
            chip_map=chip_map,
            analytics=analytics,
            intent_metrics=intent_metrics or process_intent_metrics,
        )

    async def close(self) -> None:
        await self.lead_funnel.close()
        await self.analytics.close()
        await self.session_store.close()
        close_llm = getattr(self.llm, "close", None)
        if callable(close_llm):
            result = close_llm()
            if hasattr(result, "__await__"):
                await result

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
            self.tools.catalog = refreshed
            configure_matcher(indexes, refreshed)
            return len(refreshed)

    def _resolve_tool_entity(self, value: str) -> str | None:
        entity = resolve_page_entity(self.catalog, value, "course")
        if entity is not None:
            return str(safe_get(entity, "id", "") or "") or None

        mentions = extract_mentions(value, self.matcher)
        course_ids = {
            str(candidate.entity_id)
            for candidate in mentions.courses
            if getattr(candidate, "confidence", None) == "HIGH"
        }
        university_ids = {
            str(candidate.entity_id)
            for candidate in mentions.universities
            if getattr(candidate, "confidence", None) == "HIGH"
        }
        category_concepts = {
            str(safe_get(self.indexes.entity_metadata.get(entity_id, {}), "category", ""))
            for entity_id in course_ids
        }
        category_concepts.discard("")
        if university_ids and category_concepts:
            course_ids = {
                str(entity_id)
                for entity_id, metadata in self.indexes.entity_metadata.items()
                if safe_get(metadata, "page_type") == "course"
                and str(safe_get(metadata, "university_id", "")) in university_ids
                and str(safe_get(metadata, "category", "")) in category_concepts
            }
        if university_ids:
            course_ids = {
                entity_id
                for entity_id in course_ids
                if str(safe_get(
                    self.indexes.entity_metadata.get(entity_id, {}),
                    "university_id",
                    "",
                ))
                in university_ids
            }
        return next(iter(course_ids)) if len(course_ids) == 1 else None

    def _lookup_tool_programs(self, discipline: str) -> list[str]:
        """Resolve configured discipline keys only against published catalog fields."""

        key = re.sub(r"[^a-z0-9]+", " ", discipline.casefold()).strip()
        if not key:
            return []
        matches: list[str] = []
        for entity_id, entity in self.catalog.entities.items():
            page_type = str(safe_get(entity, "_meta.page_type", "") or "")
            if page_type not in {"course", "specialization"}:
                continue
            fields = (
                safe_get(entity, "discipline"),
                safe_get(entity, "category"),
                safe_get(entity, "program_name"),
                safe_get(entity, "specialization_name"),
                safe_get(entity, "spec_name"),
            )
            normalized = {
                re.sub(r"[^a-z0-9]+", " ", str(field or "").casefold()).strip() for field in fields
            }
            structured_terms = {
                re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
                for field in ("discovery_tags", "career_outcomes")
                for value in (safe_get(entity, field, []) or [])
            }
            if key in normalized or key in structured_terms:
                matches.append(str(entity_id))
        return matches[:3]

    def emit_funnel_event(
        self,
        event: str,
        state: ConversationState,
        *,
        surface: str | None = None,
        funnel_stage: str = "bottom",
        content_version: str = "not_applicable",
        attributes: dict[str, Any] | None = None,
    ) -> bool:
        """Build and queue one complete event without affecting the request path."""

        entity_id = state.navigation.entity_id or state.focus.entity_id
        event_attributes = dict(attributes or {})
        catalog_dimensions = self.catalog_analytics_dimensions(entity_id)
        if catalog_dimensions:
            event_attributes["catalog_v3"] = catalog_dimensions
        try:
            payload = build_event(
                event,
                session_id=state.session_id,
                correlation_id=logging_setup.correlation_id(
                    state.session_id,
                    max(state.turn_count, state.navigation.interaction_count, 1),
                ),
                surface=surface or state.navigation.surface or "page:home",
                funnel_stage=funnel_stage,
                interaction_count=state.navigation.interaction_count,
                entity={
                    "type": state.navigation.page_type or None,
                    "id": entity_id,
                },
                config_version=(
                    state.navigation.config_version or self.chip_map.snapshot().version
                ),
                content_version=content_version,
                attributes=event_attributes or None,
            )
        except Exception as exc:
            LOGGER.warning("Unable to build analytics event %s: %s", event, exc)
            return False
        return self.analytics.emit(payload)

    def catalog_analytics_dimensions(self, entity_id: str | None) -> dict[str, Any]:
        """Project bounded Catalog V3 dimensions onto analytics events."""

        entity = self.catalog.get_entity(entity_id) if entity_id else None
        if entity is None:
            return {}
        result: dict[str, Any] = {}
        for field in ("review_count", "average_rating"):
            value = safe_get(entity, field, None)
            if value is not None:
                result[field] = value
        for field in ("discovery_tags", "career_outcomes"):
            values = safe_get(entity, field, None)
            if isinstance(values, list):
                result[field] = [str(value) for value in values[:12]]
        fee_metadata = safe_get(entity, "fee_metadata", None)
        if isinstance(fee_metadata, Mapping):
            result["fee_metadata"] = {
                str(key): value
                for key, value in fee_metadata.items()
                if value is not None
            }
        return result

    def record_chip_action(
        self,
        state: ConversationState,
        *,
        chip_id: str | None,
        surface: str | None,
        config_version: str | None,
    ) -> bool:
        """Accept only a chip that was rendered on the persisted surface/version."""

        if not chip_id:
            return False
        rendered_version = (
            config_version
            or state.navigation.config_version
            or self.chip_map.snapshot().version  # type: ignore[union-attr]
        )
        config = self.chip_map.snapshot(version=rendered_version)
        if config is None:
            LOGGER.warning(
                "Rejected chip action %s: config version %s is no longer retained",
                chip_id,
                rendered_version,
            )
            return False
        definition = config.chips.get(chip_id)
        if definition is None:
            LOGGER.warning("Rejected unknown chip action %s", chip_id)
            return False
        action_surface = str(surface or state.navigation.surface or "")
        declared_surface = config.surfaces.get(action_surface)
        declared_ids = (
            set((*declared_surface.top, *declared_surface.more, *declared_surface.follow))
            if declared_surface is not None
            else set()
        )
        is_conversion = chip_id in config.progression.conversion_chips
        if not is_conversion and (
            action_surface != state.navigation.surface or chip_id not in declared_ids
        ):
            LOGGER.warning(
                "Rejected chip action %s from stale or invalid surface %s (expected %s)",
                chip_id,
                action_surface,
                state.navigation.surface,
            )
            return False
        state.navigation.config_version = config.version
        advance_navigation(
            state,
            chip_id=chip_id,
            surface=action_surface or state.navigation.surface,
        )
        return True

    def maybe_emit_lead_captured(
        self,
        state: ConversationState,
        *,
        lead_tags: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> bool:
        """Emit the north-star conversion once, only after name and phone exist."""

        if (
            state.lead.conversion_recorded
            or not state.lead.name
            or not state.lead.phone
        ):
            return False
        attributes: dict[str, Any] = {}
        if lead_tags:
            attributes["lead_tags"] = dict(lead_tags)
        if source:
            attributes["source"] = source
        emitted = self.emit_funnel_event(
            LEAD_CAPTURED,
            state,
            surface=state.navigation.surface or "lead:capture",
            funnel_stage="bottom",
            attributes=attributes or None,
        )
        if emitted:
            state.lead.conversion_recorded = True
        return emitted

    def emit_tool_turn(self, state: ConversationState, turn: Any) -> None:
        """Translate one ActiveFlow transition into the stable analytics vocabulary."""

        flow_meta = turn.response.metadata.get("tool_flow", {})
        version = str(
            getattr(turn, "content_version", None)
            or flow_meta.get("version")
            or (
                state.active_flow.version
                if state.active_flow is not None
                else self.tools.content_store.version
            )
        )
        status_value = getattr(getattr(turn, "result", None), "status", None)
        answered_step = getattr(turn, "answered_step", None)
        if answered_step:
            self.emit_funnel_event(
                TOOL_STEP,
                state,
                surface=f"tool:{turn.tool}",
                funnel_stage="bottom",
                content_version=version or "not_applicable",
                attributes={
                    "tool": turn.tool,
                    "lifecycle": "answer",
                    "step": str(answered_step),
                    "status": str(status_value or "ok"),
                },
            )
        event = {
            "partial_reveal": TOOL_PARTIAL_REVEAL,
            "await_lead": TOOL_LEAD_GATE,
            "reveal": TOOL_COMPLETED,
        }.get(str(turn.lifecycle))
        if event is not None:
            self.emit_funnel_event(
                event,
                state,
                surface=f"tool:{turn.tool}",
                funnel_stage="bottom",
                content_version=version or "not_applicable",
                attributes={
                    "tool": turn.tool,
                    "lifecycle": str(turn.lifecycle),
                    "step": str(flow_meta.get("step") or turn.lifecycle),
                    "status": str(status_value or "ok"),
                },
            )

    def _append_history(self, state: ConversationState, role: str, content: str) -> None:
        state.append_history(
            role,  # type: ignore[arg-type]
            content,
            limit=self.settings.session_history_limit,
        )

    def _seed_page_focus(self, state: ConversationState, chat: ChatRequest) -> None:
        """Seed an empty existing Focus from an exact page entity, never from fuzzy text."""

        if _has_focus(state):
            return
        reference = chat.page_entity_slug or chat.page_university_slug
        if not reference:
            return
        entity = resolve_page_entity(self.catalog, reference, chat.page_type)
        entity_id = str(safe_get(entity, "id", "") or "") if entity is not None else ""
        if entity is None or not entity_id:
            return

        self._apply_catalog_focus(state, entity_id)

    def _apply_catalog_focus(self, state: ConversationState, entity_id: str) -> None:
        """Synchronize Focus from one explicit, exact catalog navigation selection."""

        metadata = self.indexes.entity_metadata.get(entity_id)
        if metadata is None:
            return

        focus = state.focus
        page_type = str(safe_get(metadata, "page_type", "") or "")
        focus.entity_id = str(safe_get(metadata, "id", entity_id) or entity_id)
        focus.university_concept = safe_get(metadata, "university_name")
        focus.course_concept = safe_get(metadata, "category")
        focus.specialization_concept = safe_get(metadata, "specialization_name")
        focus.university = (
            focus.entity_id if page_type == "university" else safe_get(metadata, "university_id")
        )
        focus.category = safe_get(metadata, "category")
        focus.specialization = safe_get(metadata, "specialization_name")
        focus.attribute = None
        focus.unknown_entities.clear()
        focus.source = "context"
        focus.sources.clear()
        for slot, value in (
            ("university", focus.university_concept),
            ("course", focus.course_concept),
            ("specialization", focus.specialization_concept),
        ):
            if value:
                focus.sources[slot] = "context"

    def _synthesis_prompt(
        self,
        state: ConversationState,
        message: str,
        route: str,
        payload: ResponsePayload,
    ) -> str | None:
        if route != "factual" or topic_from_message(message) != "about":
            return None
        if not self.settings.enable_answer_synthesis:
            return None
        if "personalised help" in payload.text.casefold():
            return None
        if not self.llm.synthesis_configured or not state.focus.entity_id:
            return None
        entity = self.catalog.cache_in_state(state.focus.entity_id, state)
        if entity is None:
            return None
        summary = safe_get(entity, "hero_description") or safe_get(entity, "about_content")
        # Structured fields already have deterministic templates. Synthesis is
        # reserved for publisher narrative, not triggered merely by fee+duration.
        if not summary:
            return None
        facts = {
            "name": safe_get(entity, "program_name")
            or safe_get(entity, "spec_name")
            or safe_get(entity, "university_full_name")
            or safe_get(entity, "university_name"),
            "summary": summary,
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
        """Run the unchanged decision pipeline, then add presentation metadata."""

        result = await self._process_turn(chat)
        result.payload = enrich_response(
            result.payload,
            state=result.state,
            route=result.route,
            catalog=self.catalog,
            operands=result.presentation_operands,
            message=chat.message,
            chip_engine=getattr(self, "chip_engine", None),
        )
        rendered_action = next(
            (
                action
                for action in result.payload.quick_actions
                if action.chip_id and action.surface and action.config_version
            ),
            None,
        )
        if rendered_action is not None:
            result.state.navigation.surface = (
                rendered_action.surface or result.state.navigation.surface
            )
            result.state.navigation.current_node = (
                rendered_action.surface or result.state.navigation.current_node
            )
            result.state.navigation.config_version = (
                rendered_action.config_version or result.state.navigation.config_version
            )
            if rendered_action.surface and rendered_action.surface.startswith("answer:"):
                advance_answer_navigation(
                    result.state,
                    answer_state=rendered_action.surface.removeprefix("answer:"),
                )
            await self.session_store.set(result.state)
        return result

    async def _process_turn(self, chat: ChatRequest) -> TurnResult:
        turn_start = time.monotonic()
        message_metric = self.intent_metrics.begin_message()

        def record_action_source(source: ActionSource) -> None:
            self.intent_metrics.record_action_source(message_metric, source)

        session_id = chat.session_id or str(uuid4())
        existing_state = await self.session_store.get(session_id)
        state = existing_state or ConversationState(session_id=session_id)
        hydrate_focus_concepts(state.focus, self.indexes)
        if not state.navigation.config_version:
            state.navigation.config_version = self.chip_map.snapshot().version  # type: ignore[union-attr]
        first_message = state.turn_count == 0
        state.turn_count += 1
        self._append_history(state, "user", chat.message)

        tl = logging_setup.TurnLogger(logging_setup.correlation_id(session_id, state.turn_count))
        tl.info("chatbot.nlu", 'IN msg="%s"', chat.message)

        # Recognition always runs before any classification or route decision.
        # The callback detector remains the first routing probe after that cheap,
        # catalog-derived pass.
        mentions = extract_mentions(chat.message, self.matcher)
        if not mentions.has_explicit_mentions:
            self._seed_page_focus(state, chat)
        if chat.page_type:
            opening = self.journey_engine.opening(chat.page_type)
            sync_page_navigation(
                state,
                page_type=chat.page_type,
                entity_id=state.focus.entity_id or state.navigation.entity_id,
                config_version=opening.config_version,
            )
        if chat.chip_id:
            self.record_chip_action(
                state,
                chip_id=chat.chip_id,
                surface=chat.chip_surface,
                config_version=chat.chip_config_version,
            )
        else:
            state.navigation.interaction_count += 1
        if first_message:
            self.emit_funnel_event(
                SESSION_START,
                state,
                surface=state.navigation.surface,
                funnel_stage=(
                    "top"
                    if state.navigation.page_type in {"homepage", "pillar"}
                    else "mid"
                    if state.navigation.page_type in {"university", "course"}
                    else "bottom"
                ),
            )
        cb_match = is_callback_request(chat.message)
        tl.info("chatbot.nlu", "callback_detector: %s", "match" if cb_match else "no match")

        requested_tool = tool_id_from_message(chat.message)
        if requested_tool is not None:
            previous_flow = state.active_flow.model_copy(deep=True) if state.active_flow else None
            turn = self.tools.enter(
                state,
                requested_tool,
                initial_payload={
                    "program_id": state.focus.entity_id,
                    "question_bank_key": state.focus.entity_id,
                }
                if state.focus.entity_id
                else None,
            )
            record_action_source("deterministic_rule")
            if state.active_flow is not None:
                state.navigation.step = NavigationStep.TOOL
                state.navigation.interaction_count = 0
                self.emit_funnel_event(
                    TOOL_STARTED,
                    state,
                    surface=f"tool:{requested_tool}",
                    funnel_stage="bottom",
                    content_version=(
                        getattr(turn, "content_version", None)
                        or state.active_flow.version
                    ),
                    attributes={"tool": requested_tool},
                )
            else:
                state.navigation.step = PAGE_STEPS.get(
                    state.navigation.page_type,
                    NavigationStep.HOMEPAGE,
                )
            if turn.replaced_tool:
                self.emit_funnel_event(
                    FLOW_ABANDONED,
                    state,
                    surface=f"tool:{turn.replaced_tool}",
                    funnel_stage="bottom",
                    content_version=(
                        previous_flow.version
                        if previous_flow is not None
                        else "not_applicable"
                    ),
                    attributes={
                        "tool": turn.replaced_tool,
                        "reason": "replaced_by_tool",
                    },
                )
            self.emit_tool_turn(state, turn)
            await self._persist_result(state, turn.response)
            tl.info("chatbot.routing", "route: tool (%s)", requested_tool)
            return TurnResult(session_id, state, turn.response, "tool")

        if state.active_flow is not None:
            active_tool = state.active_flow.tool
            active_version = state.active_flow.version
            turn = self.tools.dispatch(
                state,
                chat.message,
                escape=EscapeSignals(
                    callback_request=cb_match,
                    high_confidence_catalog_mention=mentions.has_high_confidence_mention,
                ),
            )
            if turn is not None and turn.escaped:
                state.navigation.step = PAGE_STEPS.get(
                    state.navigation.page_type,
                    NavigationStep.HOMEPAGE,
                )
                self.emit_funnel_event(
                    FLOW_ABANDONED,
                    state,
                    surface=f"tool:{active_tool}",
                    funnel_stage="bottom",
                    content_version=active_version or "not_applicable",
                    attributes={"tool": active_tool, "reason": "new_intent"},
                )
                tl.info("chatbot.routing", "tool %s abandoned for new intent", active_tool)
            elif turn is not None:
                record_action_source("deterministic_rule")
                self.emit_tool_turn(state, turn)
                if str(turn.lifecycle) == "exit" and state.active_flow is None:
                    state.navigation.step = PAGE_STEPS.get(
                        state.navigation.page_type,
                        NavigationStep.HOMEPAGE,
                    )
                    self.emit_funnel_event(
                        FLOW_ABANDONED,
                        state,
                        surface=f"tool:{active_tool}",
                        funnel_stage="bottom",
                        content_version=(
                            getattr(turn, "content_version", None)
                            or active_version
                            or "not_applicable"
                        ),
                        attributes={"tool": active_tool, "reason": "tool_unavailable"},
                    )
                await self._persist_result(state, turn.response)
                tl.info("chatbot.routing", "route: tool (%s)", active_tool)
                return TurnResult(session_id, state, turn.response, "tool")

        if cb_match:
            record_action_source("deterministic_rule")
            state.advisor.clear()
            state.navigation.step = NavigationStep.LEAD_CAPTURE
            payload = self.lead_funnel.handle_callback(state, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: lead (callback)")
            return TurnResult(session_id, state, payload, "lead")

        preflight_action = classify_action(mentions, chat.message)
        preflight_heuristic = heuristic_intent(chat.message)

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
                "career",
                "job",
                "salary",
                "special",
                "business",
                "management",
                "technology",
                "software",
                "computer",
            )
        )
        domain_topic = knowledge_topic(chat.message)
        selected_topic = topic_from_message(chat.message)
        safe_focused_followup = bool(
            _has_focus(state)
            and not domain_topic
            and (mentions.reference or selected_topic != "about")
        )
        action_start = time.monotonic()
        used_gemini = False
        gemini_needs_clarification = False
        action = preflight_action
        if action is not None:
            action_source = "deterministic_rule"
            source_label = "action-rule"
        elif has_deferred_clarification(mentions):
            # MEDIUM taxonomy evidence must reach the resolver/clarifier without
            # paying for Gemini or dispatching an empty pre-resolution clarify.
            action = Action.GET_FACTS
            action_source = "deterministic_rule"
            source_label = "matcher-confirmation"
        elif preference_followup:
            action = Action.RECOMMEND
            action_source = "heuristic_regex"
            source_label = "preference-followup"
        else:
            heuristic = preflight_heuristic
            if heuristic is not Intent.FACTUAL:
                action = action_from_intent(heuristic)
                action_source = "heuristic_regex"
                source_label = "heuristic-regex"
            elif domain_topic:
                action = Action.GET_FACTS
                action_source = "deterministic_rule"
                source_label = "knowledge-fast-path"
            elif safe_focused_followup:
                action = Action.GET_FACTS
                action_source = "deterministic_rule"
                source_label = "focused-topic-fast-path"
            elif should_use_reasoning_llm(chat.message):
                used_gemini = True
                outcome = await decide_action(
                    chat.message,
                    summarize_mentions(mentions),
                    self.llm,
                    metrics=self.intent_metrics,
                    message_metric=message_metric,
                )
                action = outcome.action
                gemini_needs_clarification = outcome.needs_clarification
                action_source = "gemini" if outcome.source == "gemini" else "heuristic_regex"
                source_label = outcome.source
            else:
                # Recognition, typo handling, ordinary unsupported subjects, and
                # unrelated questions never depend on Gemini. Attribute-only
                # turns can still resolve against context; other no-evidence
                # turns are safely unrelated.
                action = (
                    Action.GET_FACTS if getattr(mentions, "attributes", ()) else Action.UNRELATED
                )
                action_source = "heuristic_regex"
                source_label = "local-nonreasoning"

        is_product_action = action not in {
            Action.CHITCHAT,
            Action.UNRELATED,
            Action.CALLBACK,
            Action.OPEN_LEAD_FORM,
            Action.FALLBACK,
            None,
        }

        # Lead collection is an explicit, isolated flow. Lifecycle commands and
        # valid field answers are handled here; every informational turn exits the
        # flow and continues through ordinary catalog routing untouched.
        if self.lead_funnel.is_active(state):
            lifecycle_payload = self.lead_funnel.handle_lifecycle_command(
                state,
                chat.message,
            )
            if lifecycle_payload is not None:
                record_action_source("deterministic_rule")
                await self._persist_result(state, lifecycle_payload)
                tl.info("chatbot.routing", "route: lead (lifecycle command)")
                return TurnResult(session_id, state, lifecycle_payload, "lead")

            pending_answer = self.lead_funnel.inspect_pending_answer(state, chat.message)
        else:
            pending_answer = None

        if pending_answer is not None:
            deferral = self.lead_funnel.is_deferral(chat.message)
            if is_product_action:
                product_turn = True
            else:
                product_turn = _looks_like_product_turn(
                    chat.message,
                    mentions,
                    action_hint=preflight_action,
                    heuristic=preflight_heuristic,
                )

            # A standalone valid name can resemble an unknown Title Case entity.
            # In an active legacy name prompt, resolved catalog evidence or an
            # actual query marker is required to steal it from the funnel.
            if (
                pending_answer.field == "name"
                and pending_answer.valid
                and not mentions.has_explicit_mentions
                and not getattr(mentions, "attributes", ())
                and preflight_heuristic is Intent.FACTUAL
                and preflight_action in {None, Action.UNSUPPORTED_ENTITY}
                and "?" not in chat.message
            ):
                product_turn = False
            name_is_product = pending_answer.field == "name" and product_turn

            if pending_answer.valid and not deferral and not name_is_product:
                captured_fields = self.lead_funnel.commit_pending_answer(
                    state,
                    pending_answer,
                )
                self.maybe_emit_lead_captured(state, source="chat_funnel")
                # Persist the lead snapshot before any downstream NLU/routing failure can
                # diverge session state from the CRM event that was just scheduled.
                await self.session_store.set(state)
                tl.info(
                    "chatbot.leads",
                    "pending %s captured before NLU",
                    pending_answer.field,
                )
                if product_turn:
                    # A combined answer + catalog question may safely save the
                    # explicit field, but the informational request owns the
                    # response and closes collection immediately afterward.
                    self.lead_funnel.complete(state)
                    tl.info("chatbot.leads", "lead field saved; flow exited for chat")
                else:
                    payload = self.lead_funnel.captured_reply_response(
                        state,
                        captured_fields,
                    )
                    record_action_source("deterministic_rule")
                    await self._persist_result(state, payload)
                    tl.info("chatbot.routing", "route: lead (pending answer captured)")
                    return TurnResult(session_id, state, payload, "lead")

            if deferral or product_turn:
                self.lead_funnel.complete(state)
                tl.info("chatbot.leads", "lead flow exited for ordinary chat")
            elif _looks_like_lead_attempt(pending_answer.field, chat.message):
                record_action_source("deterministic_rule")
                payload = self.lead_funnel.invalid_pending_response(pending_answer.field)
                await self._persist_result(state, payload)
                tl.info(
                    "chatbot.routing",
                    "route: lead (invalid pending %s)",
                    pending_answer.field,
                )
                return TurnResult(session_id, state, payload, "lead")
            else:
                self.lead_funnel.complete(state)

        # Advisor answers are similarly isolated, but persist in their own
        # profile rather than academic focus. A new informational query simply
        # suspends advisor mode and proceeds through normal resolution.
        if state.advisor.active:
            if advisor_can_consume(state, chat.message, mentions):
                record_action_source("deterministic_rule")
                payload = handle_advisor_turn(
                    state,
                    chat.message,
                    self.catalog,
                    mentions=mentions,
                    category=state.advisor.category,
                )
                await self._persist_result(state, payload)
                tl.info("chatbot.routing", "route: advisory (profile answer)")
                return TurnResult(session_id, state, payload, "advisory")
            state.advisor.active = False
            state.advisor.last_asked_field = None
            tl.info("chatbot.routing", "advisor mode suspended for ordinary chat")

        # Step 3: an offered clarification is resolved before all ordinary NLU.
        pending_context = (
            state.pending_clarification.model_copy(deep=True)
            if state.pending_clarification is not None
            else None
        )
        pending = resolve_pending_clarification(
            chat.message,
            state,
            indexes=self.indexes,
            catalog=self.catalog,
        )
        pending_status = (
            f"resolved to {pending.entity_id}"
            if pending.resolved
            else (
                "pending, awaiting answer"
                if state.pending_clarification and not pending.new_topic
                else "none active"
            )
        )
        tl.info("chatbot.resolver", "pending_clarification: %s", pending_status)
        if pending.resolved:
            resume_comparison = bool(
                pending_context is not None and pending_context.resume_intent == "comparison"
            )
            action = Action.COMPARE if resume_comparison else Action.GET_FACTS
            route = select_route(state.focus, action, state.pending_clarification)
            dispatch_kwargs: dict[str, Any] = {}
            if resume_comparison and pending_context is not None:
                universities = list(pending_context.comparison_universities)
                entity_ids = list(pending_context.comparison_entity_ids)
                categories = list(pending_context.comparison_categories)
                specializations = list(pending_context.comparison_specializations)
                if pending.slot_type == "university" and pending.entity_id:
                    universities.append(pending.entity_id)
                elif pending.slot_type == "course" and state.focus.category:
                    categories.append(state.focus.category)
                elif pending.slot_type == "specialization" and pending.entity_id:
                    specializations.append([pending.entity_id])
                dispatch_kwargs = {
                    "universities": list(dict.fromkeys(universities)),
                    "entity_ids": list(dict.fromkeys(entity_ids)),
                    "categories": list(dict.fromkeys(categories)),
                    "common_category": pending_context.comparison_common_category,
                    "specializations": specializations,
                }
            payload = await self.router.dispatch(
                state,
                action,
                chat.message,
                **dispatch_kwargs,
            )
            record_action_source("deterministic_rule")
            payload = self.lead_funnel.augment(state, payload, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: %s (clarification resolved)", route)
            return TurnResult(
                session_id,
                state,
                payload,
                route,
                self._synthesis_prompt(state, chat.message, route, payload),
                _presentation_operand_ids(
                    dispatch_kwargs.get("entity_ids"),
                    dispatch_kwargs.get("universities"),
                ),
            )
        if state.pending_clarification is not None and not pending.new_topic:
            payload = await self.router.dispatch(state, Action.CLARIFY, chat.message)
            record_action_source("deterministic_rule")
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: clarification (still pending)")
            return TurnResult(session_id, state, payload, "clarification")

        # Action classification runs above the lead funnel check so product turns
        # cannot be consumed as contact-field answers.
        record_action_source(action_source)
        action_ms = (time.monotonic() - action_start) * 1000
        tl.info(
            "chatbot.nlu",
            "action: %s source=%s (%.0fms)",
            action.value,
            source_label,
            action_ms,
        )

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
                tl.info(
                    "chatbot.nlu",
                    '[recognition] input="%s" matched="%s" slot="%s" '
                    'method="%s" score=%s confidence="%s" candidates=%d',
                    getattr(top, "matched_span", chat.message),
                    getattr(top, "matched_catalog_term", None)
                    or getattr(top, "canonical_name", top),
                    slot,
                    getattr(top, "method", f"layer-{getattr(top, 'layer', '?')}"),
                    getattr(top, "score", None),
                    getattr(top, "confidence", "?"),
                    len(candidates),
                )
            else:
                tl.info("chatbot.nlu", "mention: %s=none", slot)
        for unknown in getattr(mentions, "unknown_entities", ()):
            tl.info("chatbot.nlu", '[unknown_entity] input="%s"', unknown)

        if action in {Action.CALLBACK, Action.OPEN_LEAD_FORM}:
            state.advisor.clear()
            state.navigation.step = NavigationStep.LEAD_CAPTURE
            payload = self.lead_funnel.handle_callback(state, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: lead (Gemini callback)")
            return TurnResult(session_id, state, payload, "lead")

        # Matcher evidence still needs the deterministic confirmation flow. A
        # degraded Gemini outcome must not discard MEDIUM "mbaa" -> MBA evidence
        # or a HIGH ambiguity such as the two Manipal universities.
        matcher_confirmation = bool(
            (
                mentions.has_medium_confidence_mention
                and action in {Action.GET_FACTS, Action.UNSUPPORTED_ENTITY, Action.CLARIFY}
            )
            or (
                mentions.has_high_confidence_mention
                and action is Action.UNSUPPORTED_ENTITY
                and action_source == "heuristic_regex"
            )
        )
        if matcher_confirmation:
            action = Action.GET_FACTS

        # Context resolution and catalog validation happen before final dispatch.
        # The pre-resolution action above is only a hint for comparison/advisory/
        # discovery reset semantics; no concrete handler has run yet.
        focus_before = {
            "uni": state.focus.university_concept or state.focus.university,
            "cat": state.focus.course_concept or state.focus.category,
            "spec": state.focus.specialization_concept or state.focus.specialization,
            "eid": state.focus.entity_id,
        }
        if (
            action is Action.DISCOVERY
            and not mentions.has_explicit_mentions
            and not mentions.reference
        ):
            # A broad browse request is a deliberate context break, not a
            # pronoun follow-up to the previously focused course.
            state.focus.clear()
        resolve_reference(mentions, state, raw_input=chat.message)
        update = update_focus(
            state,
            mentions,
            intent=_resolver_intent(action),
            catalog=self.catalog,
            indexes=self.indexes,
            category_index=self.indexes.category_index,
        )
        hydrate_focus_concepts(state.focus, self.indexes)

        # An explicit unknown-only subject is a weak topic switch. Keep its name
        # for the unsupported response, but never combine it with inherited IDs.
        if action is Action.UNSUPPORTED_ENTITY and not mentions.has_explicit_mentions:
            unknowns = list(getattr(mentions, "unknown_entities", ()))
            state.focus.clear()
            state.focus.unknown_entities = unknowns
            state.focus.source = "explicit"

        validation = validate_focus(
            state.focus,
            self.indexes,
            explicit_slots=update.explicit_slots,
        )
        if validation.dropped_context_slots:
            tl.info(
                "chatbot.resolver",
                '[validation] result="valid" action="drop_context" slots=%s',
                validation.dropped_context_slots,
            )
        elif not validation.valid:
            tl.info(
                "chatbot.resolver",
                '[validation] university="%s" course="%s" result="invalid" action="explain"',
                state.focus.university_concept,
                state.focus.course_concept,
            )
        if validation.explicit_conflict:
            payload = await handle_invalid_combination(
                state=state,
                message=chat.message,
                catalog=self.catalog,
                category_index=self.indexes.category_index,
            )
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: fallback (invalid catalog combination)")
            return TurnResult(session_id, state, payload, "fallback")

        # Only a confident unrelated signal may discard catalog focus.
        if action is Action.UNRELATED:
            state.focus.clear()
            tl.info("chatbot.resolver", "focus: cleared (intent=unrelated)")

        if action is Action.LIST_PROVIDERS:
            state.pending_clarification = None
            decision = None
        else:
            decision = clarify(state, update, indexes=self.indexes)
        if decision is not None and decision.needs_clarification:
            tl.info(
                "chatbot.resolver",
                '[clarification] token="%s" candidates=%d',
                decision.slot_type or "unknown",
                len(decision.candidates),
            )

        focus_after = {
            "uni": state.focus.university_concept or state.focus.university,
            "cat": state.focus.course_concept or state.focus.category,
            "spec": state.focus.specialization_concept or state.focus.specialization,
            "eid": state.focus.entity_id,
        }
        tl.info("chatbot.resolver", "focus: before=%s after=%s", focus_before, focus_after)
        focus_log_keys = {
            "university": "uni",
            "course": "cat",
            "specialization": "spec",
        }
        for slot in update.explicit_slots:
            before_value = focus_before[focus_log_keys[slot]]
            after_value = focus_after[focus_log_keys[slot]]
            if before_value != after_value:
                tl.info(
                    "chatbot.resolver",
                    '[focus_update] slot="%s" old="%s" new="%s" source="explicit"',
                    slot,
                    before_value,
                    after_value,
                )

        if action is Action.UNSUPPORTED_ENTITY:
            unknowns = list(
                getattr(mentions, "unresolved_terms", ()) or state.focus.unknown_entities
            )
            payload = await handle_unsupported_entity(
                state=state,
                message=chat.message,
                catalog=self.catalog,
                category_index=self.indexes.category_index,
                unknown_entities=unknowns,
            )
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: fallback (unresolved entity)")
            return TurnResult(session_id, state, payload, "fallback")

        if action is Action.CLARIFY or (
            gemini_needs_clarification
            and action not in {Action.CALLBACK, Action.UNSUPPORTED_ENTITY, Action.UNRELATED}
        ):
            payload = await self.router.dispatch(state, Action.CLARIFY, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: clarification (Gemini decision)")
            return TurnResult(session_id, state, payload, "clarification")

        # A vague no-evidence degraded factual action must never reuse an older catalog
        # entity. Keep focus intact and ask for a concrete subject instead.
        if (
            used_gemini
            and action_source == "heuristic_regex"
            and action is Action.GET_FACTS
            and not mentions.has_explicit_mentions
            and not domain_topic
            and not safe_focused_followup
            and not matcher_confirmation
        ):
            payload = _unresolved_payload(chat.message, mentions, self.indexes)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: fallback (unanchored factual)")
            return TurnResult(session_id, state, payload, "fallback")

        if (
            action is Action.GET_FACTS
            and domain_topic
            and not mentions.has_explicit_mentions
            and not mentions.reference
        ):
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

        route = select_route(state.focus, action, state.pending_clarification)
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
                action,
                chat.message,
                categories=update.comparison_categories,
                universities=update.comparison_universities,
                entity_ids=update.comparison_entity_ids,
                common_category=update.comparison_common_category,
                specializations=update.comparison_specializations,
                allow_single_university=bool(mentions.unresolved_terms),
                advisory_candidate_ids=update.advisory_candidate_ids,
                topic=topic,
                specialization_candidates=mentions.specializations,
                mentions=mentions,
            )

        if action is Action.RECOMMEND and state.advisor.active:
            # Duplicate provider rows for one specialization are catalog records,
            # not an advisor ambiguity. The guided profile owns the next question.
            decision = None

        if decision is not None and decision.needs_clarification:
            payload = payload.model_copy(
                update={
                    "text": decision.text or payload.text,
                    "suggested_chips": list(decision.labels) or payload.suggested_chips,
                }
            )
        else:
            payload = self.lead_funnel.augment(state, payload, chat.message)

        if mentions.has_explicit_mentions and mentions.unresolved_terms:
            payload = _acknowledge_partial_match(payload, mentions.unresolved_terms)

        await self._persist_result(state, payload)

        turn_ms = (time.monotonic() - turn_start) * 1000
        synthesis_prompt = (
            None
            if mentions.unresolved_terms
            else self._synthesis_prompt(state, chat.message, route, payload)
        )
        is_templated = not synthesis_prompt
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
            synthesis_prompt,
            _presentation_operand_ids(
                update.comparison_entity_ids,
                update.comparison_universities,
            )
            if route == "comparison" and not (decision is not None and decision.needs_clarification)
            else (),
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
    except LLMUnavailable:
        # Nothing from a failed synthesis is emitted. The deterministic payload
        # was already built and persisted before streaming.
        yield _payload_event(result)
        return

    text = "".join(tokens).strip()
    if not text:
        yield _payload_event(result)
        return
    # Buffer until the provider completes so a mid-stream failure cannot expose a
    # partial sentence followed by a contradictory deterministic fallback.
    for token in tokens:
        yield _sse("token", {"session_id": result.session_id, "token": token})
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

_runtime_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_widget_origins(_runtime_settings.widget_allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
    expose_headers=["X-Session-ID"],
)
widget_config_store = WidgetConfigStore(_runtime_settings.widget_config_path)


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    path = WIDGET_DIR / "demo.html"
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return HTMLResponse(content="<h1>widget/demo.html not found</h1>", status_code=404)


@app.get("/widget.js", include_in_schema=False)
@app.get("/widget/widget.js", include_in_schema=False)
async def widget_script() -> FileResponse:
    """Stable, unversioned embed URL; the loader resolves versioned sibling assets."""

    return FileResponse(
        WIDGET_DIR / "widget.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/widget.css", include_in_schema=False)
@app.get("/widget/widget.css", include_in_schema=False)
async def widget_stylesheet() -> FileResponse:
    return FileResponse(
        WIDGET_DIR / "widget.css",
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/widget/demo.html", include_in_schema=False)
async def widget_demo() -> FileResponse:
    return FileResponse(WIDGET_DIR / "demo.html", media_type="text/html")

@app.get("/api/widget/guide/context")
async def widget_guide_context_endpoint(
    request: Request,
    session_id: str | None = None,
    page_type: str | None = None,
    university: str | None = None,
    course: str | None = None,
    specialization: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Project page context directly from the catalog, bypassing the chat pipeline."""

    service: ChatbotService = request.app.state.service
    try:
        result = guide_context(
            service.catalog,
            page_type=page_type or "homepage",
            university=university,
            course=course,
            specialization=specialization,
            entity_id=entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guided catalog context not found",
        )
    resolved_page_type = str(result.get("context", {}).get("page_type") or "homepage")
    resolved_entity_id = result.get("context", {}).get("entity_id")
    resolved_entity = (
        service.catalog.get_entity(str(resolved_entity_id)) if resolved_entity_id else None
    )
    opening = service.journey_engine.opening(
        resolved_page_type,
        entity_context=catalog_chip_context(resolved_entity, service.catalog),
    )
    resolved_session_id = session_id or str(uuid4())
    existing = await service.session_store.get(resolved_session_id)
    state_value = existing or ConversationState(session_id=resolved_session_id)
    if resolved_entity_id:
        service._apply_catalog_focus(state_value, str(resolved_entity_id))
        state_value.pending_clarification = None
    elif resolved_page_type in {"homepage", "pillar"}:
        state_value.focus.clear()
        state_value.pending_clarification = None
    sync_page_navigation(
        state_value,
        page_type=resolved_page_type,
        entity_id=str(resolved_entity_id) if resolved_entity_id else None,
        config_version=opening.config_version,
    )
    await service.session_store.set(state_value)
    correlation_id = logging_setup.correlation_id(
        resolved_session_id,
        max(state_value.turn_count, state_value.navigation.interaction_count, 0),
    )
    current_tool = service.tools.current(state_value)
    return {
        **result,
        "session_id": resolved_session_id,
        "opening": opening_payload(opening, correlation_id=correlation_id),
        "navigation": navigation_payload(state_value),
        "active_flow": (
            {
                "tool": current_tool.tool,
                "step": current_tool.response.metadata.get("tool_flow", {}).get("step"),
                "response": current_tool.response.model_dump(mode="json", exclude_none=True),
            }
            if current_tool is not None
            else None
        ),
    }


@app.post("/api/widget/guide/chips")
async def widget_guide_chips_endpoint(
    command: GuidedChipRequest,
    request: Request,
) -> dict[str, Any]:
    """Advance one persisted guided action and return config-owned follow-ups."""

    service: ChatbotService = request.app.state.service
    session_id = command.session_id or str(uuid4())
    existing_state = await service.session_store.get(session_id)
    state_value = existing_state or ConversationState(session_id=session_id)
    current_version = service.chip_map.snapshot().version  # type: ignore[union-attr]
    context_mismatch = state_value.navigation.page_type != command.page_type or (
        command.entity_id is not None
        and state_value.navigation.entity_id != command.entity_id
    )
    if existing_state is not None and context_mismatch:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guided context is stale; reload the current page context",
        )
    if existing_state is None:
        sync_page_navigation(
            state_value,
            page_type=command.page_type,
            entity_id=command.entity_id,
            config_version=current_version,
        )
    service.record_chip_action(
        state_value,
        chip_id=command.completed_chip_id,
        surface=command.surface,
        config_version=command.config_version,
    )
    advance_answer_navigation(state_value, answer_state=command.answer_state)
    followup = service.chip_engine.lookup(
        page_type=state_value.navigation.page_type,
        card_type=command.card_type,
        answer_state=command.answer_state,
        interaction_count=state_value.navigation.interaction_count,
        state=state_value,
        entity_context=catalog_chip_context(
            service.catalog.get_entity(
                command.entity_id or state_value.navigation.entity_id or ""
            ),
            service.catalog,
        ),
        completed_chip_id=command.completed_chip_id,
    )
    state_value.navigation.surface = followup.surface
    state_value.navigation.current_node = followup.surface
    state_value.navigation.config_version = followup.config_version
    await service.session_store.set(state_value)
    correlation_id = logging_setup.correlation_id(
        session_id,
        max(state_value.turn_count, state_value.navigation.interaction_count, 1),
    )
    return {
        "session_id": session_id,
        "followup": followup_payload(followup, correlation_id=correlation_id),
        "navigation": navigation_payload(state_value),
    }


@app.post("/api/widget/analytics")
async def widget_analytics_endpoint(
    command: WidgetAnalyticsRequest,
    request: Request,
) -> dict[str, Any]:
    """Accept actual widget impressions/interactions without blocking on delivery."""

    service: ChatbotService = request.app.state.service
    session_id = command.session_id or str(uuid4())
    state_value = await service.session_store.get_or_create(session_id)
    key_block = {
        "session_id": session_id,
        "correlation_id": command.correlation_id
        or logging_setup.correlation_id(
            session_id,
            max(state_value.turn_count, command.interaction_count, 1),
        ),
        "surface": command.surface,
        "funnel_stage": command.funnel_stage,
        "interaction_count": command.interaction_count,
        "entity": command.entity,
        "config_version": command.config_version,
        "content_version": command.content_version,
    }
    event_attributes: dict[str, Any] = {}
    catalog_dimensions = service.catalog_analytics_dimensions(command.entity.get("id"))
    if catalog_dimensions:
        event_attributes["catalog_v3"] = catalog_dimensions
    if command.lead_tags:
        event_attributes["lead_tags"] = command.lead_tags
    try:
        if command.event == "chip_shown":
            event = build_chip_shown(
                command.chips,
                attributes=event_attributes or None,
                **key_block,
            )
        else:
            event = build_event(
                command.event,
                chip_id=command.chip_id,
                chip_handler=command.chip_handler,
                attributes=event_attributes or None,
                **key_block,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"accepted": service.analytics.emit(event), "session_id": session_id}


@app.get("/api/widget/guide/catalog/{kind}")
async def widget_guide_catalog_endpoint(
    kind: str,
    request: Request,
    q: str | None = None,
    university: str | None = None,
    course: str | None = None,
) -> dict[str, Any]:
    """Return catalog-grounded category/card rows without conversational routing."""

    service: ChatbotService = request.app.state.service
    try:
        items = guide_catalog(
            service.catalog,
            kind,
            query=q,
            university=university,
            course=course,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"items": items}


@app.post("/api/widget/guide/compare")
async def widget_guide_compare_endpoint(
    request: Request,
    payload: Any = Body(...),
) -> dict[str, Any]:
    """Compare two or three exact catalog records using the shared card builder."""

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must contain an entity_ids list",
        )
    entity_ids = payload.get("entity_ids")
    if (
        not isinstance(entity_ids, list)
        or not 2 <= len(entity_ids) <= 3
        or any(not isinstance(item, str) or not item.strip() for item in entity_ids)
        or len(set(entity_ids)) != len(entity_ids)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entity_ids must contain two or three distinct catalog ids",
        )

    service: ChatbotService = request.app.state.service
    unknown = [entity_id for entity_id in entity_ids if entity_id not in service.catalog.entities]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catalog entity not found: {unknown[0]}",
        )
    comparison = guide_comparison(service.catalog, entity_ids)
    if comparison is None:  # Defensive: distinct resolved operands should always build a card.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected catalog entities cannot be compared",
        )
    return comparison


@app.get("/api/widget/config/{site_key}")
async def widget_config_endpoint(site_key: str) -> dict[str, Any]:
    """Return presentation-only settings selected by the public tenant key."""

    try:
        return widget_config_store.payload(site_key)
    except InvalidSiteKeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UnknownSiteKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown widget site_key: {exc.site_key}",
        ) from exc
    except WidgetConfigLoadError as exc:
        LOGGER.exception("Widget configuration is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Widget configuration is unavailable",
        ) from exc


@app.get(
    "/api/widget/catalog/{kind}",
    response_model=CatalogOptionsResponse,
)
async def widget_catalog_endpoint(
    kind: str,
    request: Request,
    university: str | None = None,
    program: str | None = None,
    q: str | None = None,
) -> CatalogOptionsResponse:
    service: ChatbotService = request.app.state.service
    try:
        options, popular = catalog_options(
            service.catalog,
            kind,
            university=university,
            program=program,
            query=q,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CatalogOptionsResponse(
        kind=kind,  # type: ignore[arg-type]
        options=options,
        items=options,
        popular=popular,
    )


@app.post("/api/widget/finder", response_model=FinderResponse)
async def widget_finder_endpoint(
    filters: FinderRequest,
    request: Request,
) -> FinderResponse:
    service: ChatbotService = request.app.state.service
    results, matched_count = finder_results(
        service.catalog,
        program=filters.program,
        area=filters.area,
        approval=filters.approval,
        budget=filters.budget,
    )
    return FinderResponse(
        results=results,
        matched_count=matched_count,
        filters=filters.model_dump(exclude_none=True),
    )


@app.post("/api/widget/context/clear", response_model=ContextClearResponse)
async def widget_context_clear_endpoint(
    command: ContextClearRequest,
    request: Request,
) -> ContextClearResponse:
    service: ChatbotService = request.app.state.service
    state_value = await service.session_store.get_or_create(command.session_id)
    flow_only = command.scope == "flow"
    if not flow_only:
        state_value.focus.clear()
    state_value.pending_clarification = None
    if state_value.active_flow is not None:
        active_tool = state_value.active_flow.tool
        active_version = state_value.active_flow.version
        reason = "tool_closed" if flow_only else "context_clear"
        service.tools.abandon(state_value, reason=reason)
        service.emit_funnel_event(
            FLOW_ABANDONED,
            state_value,
            surface=f"tool:{active_tool}",
            funnel_stage="bottom",
            content_version=active_version or "not_applicable",
            attributes={"tool": active_tool, "reason": reason},
        )
    if not flow_only:
        opening = service.journey_engine.opening("homepage")
        sync_page_navigation(
            state_value,
            page_type="homepage",
            config_version=opening.config_version,
        )
    await service.session_store.set(state_value)
    return ContextClearResponse(
        session_id=command.session_id,
        context=(
            context_from_state(state_value, service.catalog)
            if flow_only
            else ResponseContext()
        ),
    )


@app.get("/api/widget/page-context", response_model=PageContextResponse)
async def widget_page_context_endpoint(
    request: Request,
    page_type: str | None = None,
    page_entity_slug: str | None = None,
    entity_slug: str | None = None,
    page_university_slug: str | None = None,
) -> PageContextResponse:
    service: ChatbotService = request.app.state.service
    reference = page_entity_slug or entity_slug or page_university_slug
    if not reference:
        return PageContextResponse()
    if page_type not in {None, "pillar", "university", "course", "specialization"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid page_type")
    if page_type == "pillar":
        return PageContextResponse(
            page_type="pillar",
            slug=reference,
            context=ResponseContext(course=reference),
        )
    entity = resolve_page_entity(service.catalog, reference, page_type)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page entity not found")
    resolved_type = str(safe_get(entity, "_meta.page_type", ""))
    entity_id = str(safe_get(entity, "id", "") or "") or None
    slug = str(safe_get(entity, "slug", "") or "") or None
    return PageContextResponse(
        page_type=resolved_type,  # type: ignore[arg-type]
        entity_id=entity_id,
        slug=slug,
        context=context_from_entity(entity, service.catalog),
    )


@app.post(
    "/api/widget/lead",
    response_model=WidgetLeadResponse,
    response_model_exclude_none=True,
)
async def widget_lead_endpoint(
    lead: WidgetLeadRequest,
    request: Request,
) -> WidgetLeadResponse:
    service: ChatbotService = request.app.state.service
    session_id = lead.session_id or str(uuid4())
    state_value = await service.session_store.get_or_create(session_id)
    tool_lead_tags: dict[str, Any] = {}
    active_flow = state_value.active_flow
    awaiting_tool_lead = active_flow is not None and active_flow.step == "await_lead"
    if awaiting_tool_lead and active_flow is not None:
        raw_result = active_flow.payload.get("result")
        if isinstance(raw_result, dict):
            try:
                tool_lead_tags = ToolResult.model_validate(raw_result).lead_tags
            except ValueError:
                LOGGER.warning(
                    "Tool result lead tags could not be validated for session %s",
                    session_id,
                )
    try:
        service.lead_funnel.capture_phone_only(
            state_value,
            lead.phone,
            name=lead.name,
            require_name=awaiting_tool_lead,
            source=lead.source,
            extra_context=tool_lead_tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service.record_chip_action(
        state_value,
        chip_id=lead.chip_id,
        surface=lead.chip_surface,
        config_version=lead.chip_config_version,
    )
    state_value.navigation.step = NavigationStep.LEAD_CAPTURE
    service.maybe_emit_lead_captured(
        state_value,
        lead_tags=tool_lead_tags,
        source=lead.source or "widget",
    )
    tool_payload: ResponsePayload | None = None
    if state_value.active_flow is not None:
        active_tool = state_value.active_flow.tool
        active_version = state_value.active_flow.version
        duplicate_scholarship_attempt = bool(
            state_value.active_flow.step == "await_lead"
            and active_tool == "scholarship"
            and not await service.session_store.claim_once(
                "scholarship",
                state_value.lead.phone or lead.phone,
            )
        )
        if duplicate_scholarship_attempt:
            service.tools.abandon(state_value, reason="phone_attempt_limit")
            service.emit_funnel_event(
                FLOW_ABANDONED,
                state_value,
                surface="tool:scholarship",
                funnel_stage="bottom",
                content_version=active_version or "not_applicable",
                attributes={"tool": "scholarship", "reason": "phone_attempt_limit"},
            )
            tool_payload = enrich_response(
                build_response(
                    "The scholarship checker has already been completed for this phone number."
                ),
                state=state_value,
                route="tool",
                catalog=service.catalog,
                chip_engine=service.chip_engine,
            )
            service._append_history(state_value, "assistant", tool_payload.text)
        elif state_value.active_flow.step == "await_lead":
            tool_turn = service.tools.resume_after_lead(state_value)
        else:
            tool_turn = service.tools.abandon(state_value, reason="lead_capture")
            service.emit_funnel_event(
                FLOW_ABANDONED,
                state_value,
                surface=f"tool:{active_tool}",
                funnel_stage="bottom",
                content_version=active_version or "not_applicable",
                attributes={"tool": active_tool, "reason": "lead_capture"},
            )
        if not duplicate_scholarship_attempt and tool_turn is not None and tool_turn.consumed:
            service.emit_tool_turn(state_value, tool_turn)
            tool_payload = enrich_response(
                tool_turn.response,
                state=state_value,
                route="tool",
                catalog=service.catalog,
                chip_engine=service.chip_engine,
            )
            service._append_history(state_value, "assistant", tool_payload.text)
    await service.session_store.set(state_value)
    return WidgetLeadResponse(
        session_id=session_id,
        message="Thanks — a DegreeBaba counsellor can contact you shortly.",
        response=(
            tool_payload.model_dump(mode="json", exclude_none=True)
            if tool_payload is not None
            else None
        ),
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
            suggested_chips=["Browse course categories", "Browse universities"],
            cta=lead_capture_cta(),
        )
        payload = enrich_response(
            payload,
            state=state,
            route="fallback",
            catalog=service.catalog,
            message=chat.message,
            chip_engine=service.chip_engine,
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


@app.get("/metrics")
async def metrics_endpoint(request: Request) -> dict[str, Any]:
    service: ChatbotService = request.app.state.service
    result = service.intent_metrics.snapshot()
    analytics = service.analytics.snapshot()
    analytics.pop("events", None)
    result["funnel_analytics"] = analytics
    return result


@app.post("/admin/metrics/reset")
async def reset_metrics_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    service: ChatbotService = request.app.state.service
    expected = service.settings.admin_api_key
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    service.intent_metrics.reset()
    await service.analytics.reset()
    return await metrics_endpoint(request)


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
