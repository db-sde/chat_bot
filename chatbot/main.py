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
import os

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse

import logging_setup
from advisor.flow import advisor_can_consume, handle_advisor_turn
from config import Settings, get_settings
from data.accessor import safe_get, validate_focus
from data.loader import SAMPLE_CATALOG_PATH, CatalogStore
from leads.funnel import LeadFunnel
from leads.webhook import CRMWebhook
from llm.client import LLMClient, LLMUnavailable
from llm.prompts import grounded_answer_prompt
from nlu.action_classifier import Action, has_deferred_clarification
from nlu.action_classifier import classify as classify_action
from nlu.action_classifier import mention_summary as summarize_mentions
from nlu.callback_detector import is_callback_request
from nlu.intent import Intent, decide_action, heuristic_intent, should_use_reasoning_llm
from nlu.mention_extractor import extract_mentions
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
from routing.unsupported_handler import handle_unsupported_entity
from routing.validation_handler import handle_invalid_combination
from schemas import ChatRequest, HealthResponse, ReindexResponse, ResponsePayload
from session.state import ConversationState, hydrate_focus_concepts
from session.store import SessionStore
from taxonomy.entity_matcher import EntityMatcher, configure_matcher
from taxonomy.index_builder import TaxonomyIndexes, build_indexes

LOGGER = logging.getLogger(__name__)


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
        intent_metrics: IntentMetrics = process_intent_metrics,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.indexes = indexes
        self.matcher = configure_matcher(indexes, catalog)
        self.session_store = session_store
        self.llm = llm
        self.lead_funnel = lead_funnel
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
        return cls(
            settings=config,
            catalog=loaded_catalog,
            indexes=indexes,
            session_store=state_store,
            llm=llm_client,
            lead_funnel=funnel,
            intent_metrics=intent_metrics or process_intent_metrics,
        )

    async def close(self) -> None:
        await self.lead_funnel.close()
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
        turn_start = time.monotonic()
        message_metric = self.intent_metrics.begin_message()

        def record_action_source(source: ActionSource) -> None:
            self.intent_metrics.record_action_source(message_metric, source)

        session_id = chat.session_id or str(uuid4())
        state = await self.session_store.get_or_create(session_id)
        hydrate_focus_concepts(state.focus, self.indexes)
        state.turn_count += 1
        self._append_history(state, "user", chat.message)

        tl = logging_setup.TurnLogger(logging_setup.correlation_id(session_id, state.turn_count))
        tl.info("chatbot.nlu", 'IN msg="%s"', chat.message)

        # Recognition always runs before any classification or route decision.
        # The callback detector remains the first routing probe after that cheap,
        # catalog-derived pass.
        mentions = extract_mentions(chat.message, self.matcher)
        cb_match = is_callback_request(chat.message)
        tl.info("chatbot.nlu", "callback_detector: %s", "match" if cb_match else "no match")
        if cb_match:
            record_action_source("deterministic_rule")
            state.advisor.clear()
            payload = self.lead_funnel.handle_callback(state, chat.message)
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: lead (callback)")
            return TurnResult(session_id, state, payload, "lead")

        preflight_action = classify_action(mentions, chat.message)
        preflight_heuristic = heuristic_intent(chat.message)

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
            product_turn = _looks_like_product_turn(
                chat.message,
                mentions,
                action_hint=preflight_action,
                heuristic=preflight_heuristic,
            )
            deferral = self.lead_funnel.is_deferral(chat.message)
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
            )
        if state.pending_clarification is not None and not pending.new_topic:
            payload = await self.router.dispatch(state, Action.CLARIFY, chat.message)
            record_action_source("deterministic_rule")
            await self._persist_result(state, payload)
            tl.info("chatbot.routing", "route: clarification (still pending)")
            return TurnResult(session_id, state, payload, "clarification")

        # Action selection is layered: resolved-shape rules, bounded regex intent,
        # existing contextual fast paths, then one strict Gemini JSON decision.
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
            action_source: ActionSource = "deterministic_rule"
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
                getattr(mentions, "unresolved_terms", ())
                or state.focus.unknown_entities
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


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(current_dir, "index.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found</h1>", status_code=404)


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
    return service.intent_metrics.snapshot()


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
    return service.intent_metrics.snapshot()


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
