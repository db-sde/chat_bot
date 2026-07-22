"""FastAPI lifecycle for the DegreeBaba guided admissions widget."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Body, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

import logging_setup
from analytics import (
    FLOW_ABANDONED,
    LEAD_CAPTURED,
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
from data.accessor import safe_get
from data.loader import SAMPLE_CATALOG_PATH, CatalogStore
from funnel import ChipEngine, ChipMapStore, JourneyEngine
from leads.funnel import LeadFunnel
from leads.webhook import CRMWebhook
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
from tools import ToolEngine, ToolResult, ToolsContentStore
from schemas import (
    CatalogOptionsResponse,
    ContextClearRequest,
    ContextClearResponse,
    FinderRequest,
    FinderResponse,
    GuidedChipRequest,
    GuidedToolRequest,
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
from session.state import ConversationState, NavigationStep
from session.store import SessionStore
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


class GuidedWidgetService:
    """Dependencies shared exclusively by deterministic guided endpoints."""

    def __init__(
        self,
        *,
        settings: Settings,
        catalog: CatalogStore,
        session_store: SessionStore,
        lead_funnel: LeadFunnel,
        chip_map: ChipMapStore | None = None,
        analytics: AnalyticsEmitter | None = None,
        tools: ToolEngine | None = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.session_store = session_store
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
        self.reindex_lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        settings: Settings | None = None,
        *,
        catalog: CatalogStore | None = None,
        session_store: SessionStore | None = None,
    ) -> GuidedWidgetService:
        config = settings or get_settings()
        loaded_catalog = catalog or await CatalogStore.create(settings=config)
        if not len(loaded_catalog):
            await loaded_catalog.load()
        return cls(
            settings=config,
            catalog=loaded_catalog,
            session_store=session_store or SessionStore(settings=config),
            lead_funnel=LeadFunnel(CRMWebhook(config), config),
            chip_map=ChipMapStore(config.chip_map_path),
            analytics=AnalyticsEmitter(config),
        )

    async def close(self) -> None:
        await self.lead_funnel.close()
        await self.analytics.close()
        await self.session_store.close()

    async def reindex(self) -> int:
        """Refresh the catalog without constructing text-recognition indexes."""

        async with self.reindex_lock:
            refreshed = CatalogStore(settings=self.settings)
            await refreshed.load(force=True)
            external_source_configured = bool(
                self.settings.catalog_url or self.settings.catalog_path
            )
            if external_source_configured and refreshed.source == str(SAMPLE_CATALOG_PATH):
                raise RuntimeError(
                    "Configured catalog source is unavailable; existing catalog retained"
                )
            self.catalog = refreshed
            self.tools.catalog = refreshed
            return len(refreshed)

    def _resolve_tool_entity(self, value: str) -> str | None:
        entity = resolve_page_entity(self.catalog, value, "course")
        return str(safe_get(entity, "id", "") or "") or None if entity is not None else None

    def _lookup_tool_programs(self, discipline: str) -> list[str]:
        key = re.sub(r"[^a-z0-9]+", " ", discipline.casefold()).strip()
        if not key:
            return []
        matches: list[str] = []
        for entity_id, entity in self.catalog.entities.items():
            page_type = str(safe_get(entity, "_meta.page_type", "") or "")
            if page_type not in {"course", "specialization"}:
                continue
            values = {
                re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
                for field in (
                    "discipline",
                    "category",
                    "program_name",
                    "specialization_name",
                    "spec_name",
                    "discovery_tags",
                    "career_outcomes",
                )
                for value in (
                    safe_get(entity, field, [])
                    if isinstance(safe_get(entity, field, []), list)
                    else [safe_get(entity, field, None)]
                )
            }
            if key in values:
                matches.append(str(entity_id))
        return matches[:3]

    def _apply_catalog_focus(self, state: ConversationState, entity_id: str) -> None:
        metadata = self.catalog.get_metadata(entity_id)
        if metadata is None:
            return
        focus = state.focus
        focus.entity_id = metadata.id
        focus.university_concept = metadata.university_name
        focus.course_concept = metadata.category
        focus.specialization_concept = metadata.specialization_name
        focus.university = metadata.id if metadata.page_type == "university" else None
        focus.category = metadata.category
        focus.specialization = metadata.specialization_name

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
        entity_id = state.navigation.entity_id or state.focus.entity_id
        event_attributes = dict(attributes or {})
        dimensions = self.catalog_analytics_dimensions(entity_id)
        if dimensions:
            event_attributes["catalog_v3"] = dimensions
        try:
            payload = build_event(
                event,
                session_id=state.session_id,
                correlation_id=logging_setup.correlation_id(
                    state.session_id,
                    max(state.navigation.interaction_count, 1),
                ),
                surface=surface or state.navigation.surface or "page:home",
                funnel_stage=funnel_stage,
                interaction_count=state.navigation.interaction_count,
                entity={"type": state.navigation.page_type or None, "id": entity_id},
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
                str(key): value for key, value in fee_metadata.items() if value is not None
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
        if not chip_id:
            return False
        rendered_version = (
            config_version
            or state.navigation.config_version
            or self.chip_map.snapshot().version
        )
        config = self.chip_map.snapshot(version=rendered_version)
        if config is None:
            LOGGER.warning("Rejected chip action %s: stale config", chip_id)
            return False
        definition = config.chips.get(chip_id)
        if definition is None:
            LOGGER.warning("Rejected unknown chip action %s", chip_id)
            return False
        action_surface = str(surface or state.navigation.surface or "")
        declared = config.surfaces.get(action_surface)
        declared_ids = (
            set((*declared.top, *declared.more, *declared.follow))
            if declared is not None
            else set()
        )
        is_conversion = chip_id in config.progression.conversion_chips
        if not is_conversion and (
            action_surface != state.navigation.surface or chip_id not in declared_ids
        ):
            LOGGER.warning("Rejected chip action %s from invalid surface %s", chip_id, action_surface)
            return False
        state.navigation.config_version = config.version
        advance_navigation(state, chip_id=chip_id, surface=action_surface)
        return True

    def maybe_emit_lead_captured(
        self,
        state: ConversationState,
        *,
        lead_tags: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> bool:
        if state.lead.conversion_recorded or not state.lead.name or not state.lead.phone:
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
            attributes=attributes or None,
        )
        if emitted:
            state.lead.conversion_recorded = True
        return emitted

    def emit_tool_turn(self, state: ConversationState, turn: Any) -> None:
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
        answered_step = getattr(turn, "answered_step", None)
        if answered_step:
            self.emit_funnel_event(
                TOOL_STEP,
                state,
                surface=f"tool:{turn.tool}",
                content_version=version,
                attributes={"tool": turn.tool, "step": str(answered_step)},
            )
        event = {
            "partial_reveal": TOOL_PARTIAL_REVEAL,
            "await_lead": TOOL_LEAD_GATE,
            "reveal": TOOL_COMPLETED,
        }.get(str(turn.lifecycle))
        if event:
            self.emit_funnel_event(
                event,
                state,
                surface=f"tool:{turn.tool}",
                content_version=version,
                attributes={"tool": turn.tool, "lifecycle": str(turn.lifecycle)},
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging_setup.configure(level=settings.log_level, log_format=settings.log_format)
    app.state.service = await GuidedWidgetService.create(settings)
    try:
        yield
    finally:
        await app.state.service.close()


app = FastAPI(
    title="DegreeBaba Guided Admissions Widget",
    version="2.0.0",
    description="Catalog-grounded guided admissions experience",
    lifespan=lifespan,
)

_runtime_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_widget_origins(_runtime_settings.widget_allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)
widget_config_store = WidgetConfigStore(_runtime_settings.widget_config_path)


def _service(request: Request) -> GuidedWidgetService:
    return request.app.state.service


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    path = WIDGET_DIR / "demo.html"
    return FileResponse(path, media_type="text/html") if path.exists() else HTMLResponse(
        content="<h1>widget/demo.html not found</h1>", status_code=404
    )


@app.get("/widget.js", include_in_schema=False)
@app.get("/widget/widget.js", include_in_schema=False)
async def widget_script() -> FileResponse:
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
    service = _service(request)
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Guided catalog context not found")
    resolved_page_type = str(result.get("context", {}).get("page_type") or "homepage")
    resolved_entity_id = result.get("context", {}).get("entity_id")
    resolved_entity = service.catalog.get_entity(str(resolved_entity_id)) if resolved_entity_id else None
    opening = service.journey_engine.opening(
        resolved_page_type,
        entity_context=catalog_chip_context(resolved_entity, service.catalog),
    )
    resolved_session_id = session_id or str(uuid4())
    state_value = await service.session_store.get(resolved_session_id) or ConversationState(
        session_id=resolved_session_id
    )
    if resolved_entity_id:
        service._apply_catalog_focus(state_value, str(resolved_entity_id))
    elif resolved_page_type in {"homepage", "pillar"}:
        state_value.focus.clear()
    sync_page_navigation(
        state_value,
        page_type=resolved_page_type,
        entity_id=str(resolved_entity_id) if resolved_entity_id else None,
        config_version=opening.config_version,
    )
    await service.session_store.set(state_value)
    correlation_id = logging_setup.correlation_id(
        resolved_session_id, max(state_value.navigation.interaction_count, 0)
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
    command: GuidedChipRequest, request: Request
) -> dict[str, Any]:
    service = _service(request)
    session_id = command.session_id or str(uuid4())
    existing = await service.session_store.get(session_id)
    state_value = existing or ConversationState(session_id=session_id)
    current_version = service.chip_map.snapshot().version
    mismatch = state_value.navigation.page_type != command.page_type or (
        command.entity_id is not None and state_value.navigation.entity_id != command.entity_id
    )
    if existing is not None and mismatch:
        raise HTTPException(status_code=409, detail="Guided context is stale")
    if existing is None:
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
            service.catalog.get_entity(command.entity_id or state_value.navigation.entity_id or ""),
            service.catalog,
        ),
        completed_chip_id=command.completed_chip_id,
    )
    state_value.navigation.surface = followup.surface
    state_value.navigation.current_node = followup.surface
    state_value.navigation.config_version = followup.config_version
    await service.session_store.set(state_value)
    correlation_id = logging_setup.correlation_id(
        session_id, max(state_value.navigation.interaction_count, 1)
    )
    return {
        "session_id": session_id,
        "followup": followup_payload(followup, correlation_id=correlation_id),
        "navigation": navigation_payload(state_value),
    }


@app.post("/api/widget/guide/tool")
async def widget_guide_tool_endpoint(
    command: GuidedToolRequest, request: Request
) -> dict[str, Any]:
    service = _service(request)
    session_id = command.session_id or str(uuid4())
    state_value = await service.session_store.get_or_create(session_id)
    entry_tools = {
        "tool:roi": "roi",
        "tool:career_quiz": "career_quiz",
        "tool:scholarship": "scholarship",
    }
    tool_id = entry_tools.get(command.command)
    if tool_id:
        service.record_chip_action(
            state_value,
            chip_id=command.chip_id,
            surface=command.chip_surface,
            config_version=command.chip_config_version,
        )
        entity_id = command.entity_id or state_value.navigation.entity_id
        turn = service.tools.enter(
            state_value,
            tool_id,
            initial_payload={"program_id": entity_id, "question_bank_key": entity_id}
            if entity_id
            else None,
        )
        state_value.navigation.step = NavigationStep.TOOL
        service.emit_funnel_event(
            TOOL_STARTED,
            state_value,
            surface=f"tool:{tool_id}",
            content_version=getattr(turn, "content_version", None) or "not_applicable",
            attributes={"tool": tool_id},
        )
    else:
        if state_value.active_flow is None:
            raise HTTPException(status_code=409, detail="No guided tool flow is active")
        turn = service.tools.dispatch(state_value, command.command)
        if turn is None:
            raise HTTPException(status_code=409, detail="Invalid guided tool command")
        if str(turn.lifecycle) == "exit" and state_value.active_flow is None:
            state_value.navigation.step = PAGE_STEPS.get(
                state_value.navigation.page_type, NavigationStep.HOMEPAGE
            )
    service.emit_tool_turn(state_value, turn)
    await service.session_store.set(state_value)
    return {
        "session_id": session_id,
        "response": turn.response.model_dump(mode="json", exclude_none=True),
        "navigation": navigation_payload(state_value),
    }


@app.post("/api/widget/analytics")
async def widget_analytics_endpoint(
    command: WidgetAnalyticsRequest, request: Request
) -> dict[str, Any]:
    service = _service(request)
    session_id = command.session_id or str(uuid4())
    state_value = await service.session_store.get_or_create(session_id)
    key_block = {
        "session_id": session_id,
        "correlation_id": command.correlation_id
        or logging_setup.correlation_id(session_id, max(command.interaction_count, 1)),
        "surface": command.surface,
        "funnel_stage": command.funnel_stage,
        "interaction_count": command.interaction_count,
        "entity": command.entity,
        "config_version": command.config_version,
        "content_version": command.content_version,
    }
    attributes: dict[str, Any] = {}
    dimensions = service.catalog_analytics_dimensions(command.entity.get("id"))
    if dimensions:
        attributes["catalog_v3"] = dimensions
    if command.lead_tags:
        attributes["lead_tags"] = command.lead_tags
    try:
        event = (
            build_chip_shown(command.chips, attributes=attributes or None, **key_block)
            if command.event == "chip_shown"
            else build_event(
                command.event,
                chip_id=command.chip_id,
                chip_handler=command.chip_handler,
                attributes=attributes or None,
                **key_block,
            )
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
    try:
        items = guide_catalog(
            _service(request).catalog,
            kind,
            query=q,
            university=university,
            course=course,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"items": items}


@app.post("/api/widget/guide/compare")
async def widget_guide_compare_endpoint(
    request: Request, payload: Any = Body(...)
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must contain entity_ids")
    entity_ids = payload.get("entity_ids")
    if (
        not isinstance(entity_ids, list)
        or not 2 <= len(entity_ids) <= 3
        or any(not isinstance(item, str) or not item.strip() for item in entity_ids)
        or len(set(entity_ids)) != len(entity_ids)
    ):
        raise HTTPException(status_code=400, detail="entity_ids must contain distinct catalog ids")
    service = _service(request)
    unknown = [entity_id for entity_id in entity_ids if entity_id not in service.catalog.entities]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Catalog entity not found: {unknown[0]}")
    comparison = guide_comparison(service.catalog, entity_ids)
    if comparison is None:
        raise HTTPException(status_code=400, detail="Selected entities cannot be compared")
    return comparison


@app.get("/api/widget/config/{site_key}")
async def widget_config_endpoint(site_key: str) -> dict[str, Any]:
    try:
        return widget_config_store.payload(site_key)
    except InvalidSiteKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownSiteKeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown widget site_key: {exc.site_key}") from exc
    except WidgetConfigLoadError as exc:
        LOGGER.exception("Widget configuration is unavailable")
        raise HTTPException(status_code=503, detail="Widget configuration is unavailable") from exc


@app.get("/api/widget/catalog/{kind}", response_model=CatalogOptionsResponse)
async def widget_catalog_endpoint(
    kind: str,
    request: Request,
    university: str | None = None,
    program: str | None = None,
    q: str | None = None,
) -> CatalogOptionsResponse:
    try:
        options, popular = catalog_options(
            _service(request).catalog,
            kind,
            university=university,
            program=program,
            query=q,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CatalogOptionsResponse(kind=kind, options=options, items=options, popular=popular)


@app.post("/api/widget/finder", response_model=FinderResponse)
async def widget_finder_endpoint(filters: FinderRequest, request: Request) -> FinderResponse:
    results, matched_count = finder_results(
        _service(request).catalog,
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
    command: ContextClearRequest, request: Request
) -> ContextClearResponse:
    service = _service(request)
    state_value = await service.session_store.get_or_create(command.session_id)
    flow_only = command.scope == "flow"
    if not flow_only:
        state_value.focus.clear()
    if state_value.active_flow is not None:
        active_tool = state_value.active_flow.tool
        version = state_value.active_flow.version
        reason = "tool_closed" if flow_only else "context_clear"
        service.tools.abandon(state_value, reason=reason)
        service.emit_funnel_event(
            FLOW_ABANDONED,
            state_value,
            surface=f"tool:{active_tool}",
            content_version=version or "not_applicable",
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
        context=context_from_state(state_value, service.catalog) if flow_only else ResponseContext(),
    )


@app.get("/api/widget/page-context", response_model=PageContextResponse)
async def widget_page_context_endpoint(
    request: Request,
    page_type: str | None = None,
    page_entity_slug: str | None = None,
    entity_slug: str | None = None,
    page_university_slug: str | None = None,
) -> PageContextResponse:
    service = _service(request)
    reference = page_entity_slug or entity_slug or page_university_slug
    if not reference:
        return PageContextResponse()
    if page_type not in {None, "pillar", "university", "course", "specialization"}:
        raise HTTPException(status_code=400, detail="Invalid page_type")
    if page_type == "pillar":
        return PageContextResponse(
            page_type="pillar", slug=reference, context=ResponseContext(course=reference)
        )
    entity = resolve_page_entity(service.catalog, reference, page_type)
    if entity is None:
        raise HTTPException(status_code=404, detail="Page entity not found")
    return PageContextResponse(
        page_type=str(safe_get(entity, "_meta.page_type", "")),
        entity_id=str(safe_get(entity, "id", "") or "") or None,
        slug=str(safe_get(entity, "slug", "") or "") or None,
        context=context_from_entity(entity, service.catalog),
    )


@app.post(
    "/api/widget/lead",
    response_model=WidgetLeadResponse,
    response_model_exclude_none=True,
)
async def widget_lead_endpoint(
    lead: WidgetLeadRequest, request: Request
) -> WidgetLeadResponse:
    service = _service(request)
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
                LOGGER.warning("Tool lead tags are invalid for session %s", session_id)
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
        state_value, lead_tags=tool_lead_tags, source=lead.source or "widget"
    )
    tool_payload: ResponsePayload | None = None
    if state_value.active_flow is not None:
        active_tool = state_value.active_flow.tool
        version = state_value.active_flow.version
        duplicate = bool(
            state_value.active_flow.step == "await_lead"
            and active_tool == "scholarship"
            and not await service.session_store.claim_once(
                "scholarship", state_value.lead.phone or lead.phone
            )
        )
        if duplicate:
            service.tools.abandon(state_value, reason="phone_attempt_limit")
            service.emit_funnel_event(
                FLOW_ABANDONED,
                state_value,
                surface="tool:scholarship",
                content_version=version or "not_applicable",
                attributes={"tool": "scholarship", "reason": "phone_attempt_limit"},
            )
            tool_payload = ResponsePayload(
                text="The scholarship checker has already been completed for this phone number."
            )
        elif state_value.active_flow.step == "await_lead":
            tool_turn = service.tools.resume_after_lead(state_value)
            if tool_turn is not None and tool_turn.consumed:
                service.emit_tool_turn(state_value, tool_turn)
                tool_payload = tool_turn.response
        else:
            service.tools.abandon(state_value, reason="lead_capture")
            service.emit_funnel_event(
                FLOW_ABANDONED,
                state_value,
                surface=f"tool:{active_tool}",
                content_version=version or "not_applicable",
                attributes={"tool": active_tool, "reason": "lead_capture"},
            )
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


@app.get("/health", response_model=HealthResponse)
async def health_endpoint(request: Request) -> dict[str, Any]:
    service = _service(request)
    return await dependency_health(service.session_store, service.catalog)


@app.get("/metrics")
async def metrics_endpoint(request: Request) -> dict[str, Any]:
    analytics = _service(request).analytics.snapshot()
    analytics.pop("events", None)
    return {"funnel_analytics": analytics}


@app.post("/admin/metrics/reset")
async def reset_metrics_endpoint(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    service = _service(request)
    expected = service.settings.admin_api_key
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid admin token")
    await service.analytics.reset()
    return await metrics_endpoint(request)


@app.post("/admin/reindex", response_model=ReindexResponse)
async def reindex_endpoint(
    request: Request, authorization: str | None = Header(default=None)
) -> ReindexResponse:
    service = _service(request)
    expected = service.settings.admin_api_key
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid admin token")
    try:
        count = await service.reindex()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Catalog reindex failed; existing catalog retained")
        raise HTTPException(status_code=503, detail="Catalog reindex failed") from exc
    return ReindexResponse(entity_count=count)


__all__ = ["GuidedWidgetService", "app"]
