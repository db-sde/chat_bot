"""Pure focus/intent route selection and async handler dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from schemas import ResponsePayload

from .advisory_handler import handle_advisory
from .category_handler import handle_category
from .clarification_handler import handle_clarification
from .comparison_handler import handle_comparison
from .discovery_handler import handle_discovery
from .factual_handler import handle_factual
from .fallback_handler import handle_fallback
from .knowledge_handler import handle_knowledge

RouteName = Literal[
    "discovery",
    "category",
    "factual",
    "comparison",
    "advisory",
    "knowledge",
    "clarification",
    "fallback",
]


def _value(obj: Any, name: str, default: Any = None) -> Any:
    """Read resolver/session structures; these are not catalog entity data."""

    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _intent_value(intent: Any) -> str:
    value = getattr(intent, "value", intent)
    return str(value or "").strip().casefold()


def select_route(
    focus: Any,
    intent: Any,
    pending: Any = None,
) -> RouteName:
    """Select a route using only resolved state shape and intent.

    The user's raw message, catalog contents, and LLM are intentionally not inputs to
    this function, keeping dispatch deterministic and easy to test.
    """

    if pending is not None and pending is not False:
        return "clarification"

    selected_intent = _intent_value(intent)
    if selected_intent == "advisory":
        return "advisory"
    if selected_intent == "comparison":
        return "comparison"
    if selected_intent in {"discovery", "chitchat"}:
        return "discovery"

    entity_id = _value(focus, "entity_id")
    university = _value(focus, "university")
    category = _value(focus, "category")
    specialization = _value(focus, "specialization")

    if entity_id:
        return "factual"
    if category and not university and not specialization:
        return "category"
    if university or specialization:
        return "factual"

    if selected_intent == "factual":
        return "knowledge"
    return "fallback"


HANDLERS = {
    "discovery": handle_discovery,
    "category": handle_category,
    "factual": handle_factual,
    "comparison": handle_comparison,
    "advisory": handle_advisory,
    "knowledge": handle_knowledge,
    "clarification": handle_clarification,
    "fallback": handle_fallback,
}


async def dispatch_route(
    state: Any,
    intent: Any,
    message: str,
    catalog: Any = None,
    category_index: Any = None,
    llm: Any = None,
    *,
    candidates: Sequence[Any] | None = None,
    categories: Sequence[str] | None = None,
    entity: Any = None,
    topic: str | None = None,
) -> ResponsePayload:
    """Select and invoke one async handler, returning the canonical payload."""

    focus = _value(state, "focus")
    pending = _value(state, "pending_clarification")
    route_name = select_route(focus, intent, pending)

    common = {
        "state": state,
        "message": message,
        "catalog": catalog,
        "category_index": category_index,
        "llm": llm,
    }
    if route_name == "clarification":
        pending_candidates = _value(pending, "candidates", ())
        return await handle_clarification(
            **common,
            candidates=candidates if candidates is not None else pending_candidates,
            slot_type=_value(pending, "slot_type"),
        )
    if route_name == "comparison":
        return await handle_comparison(**common, categories=categories)
    if route_name == "factual":
        return await handle_factual(**common, entity=entity, topic=topic)
    if route_name == "knowledge":
        return await handle_knowledge(**common, topic=topic)
    return await HANDLERS[route_name](**common)


class Router:
    """Thin dependency-bound wrapper for application wiring."""

    def __init__(self, catalog: Any = None, category_index: Any = None, llm: Any = None) -> None:
        self.catalog = catalog
        self.category_index = category_index
        self.llm = llm

    async def dispatch(
        self,
        state: Any,
        intent: Any,
        message: str,
        **kwargs: Any,
    ) -> ResponsePayload:
        return await dispatch_route(
            state=state,
            intent=intent,
            message=message,
            catalog=self.catalog,
            category_index=self.category_index,
            llm=self.llm,
            **kwargs,
        )


route_message = dispatch_route
dispatch = dispatch_route
route = dispatch_route


__all__ = [
    "HANDLERS",
    "RouteName",
    "Router",
    "dispatch",
    "dispatch_route",
    "route",
    "route_message",
    "select_route",
]
