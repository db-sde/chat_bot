"""Pure focus/action route selection and async handler dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from nlu.action_classifier import Action
from schemas import ResponsePayload

from .advisory_handler import handle_advisory
from .category_handler import handle_category
from .clarification_handler import handle_clarification
from .comparison_handler import handle_comparison
from .discovery_handler import handle_discovery
from .factual_handler import handle_factual
from .fallback_handler import handle_fallback
from .knowledge_handler import handle_knowledge
from .list_handler import handle_list_providers, handle_list_specializations

RouteName = Literal[
    "discovery",
    "category",
    "factual",
    "comparison",
    "advisory",
    "knowledge",
    "clarification",
    "list_specializations",
    "list_providers",
    "fallback",
]

INTENT_TO_ACTION: dict[str, Action] = {
    "factual": Action.GET_FACTS,
    "comparison": Action.COMPARE,
    "advisory": Action.RECOMMEND,
    "discovery": Action.DISCOVERY,
    "callback": Action.OPEN_LEAD_FORM,
    "chitchat": Action.CHITCHAT,
    "unrelated": Action.UNRELATED,
    "unresolved_entity": Action.UNSUPPORTED_ENTITY,
}


def _value(obj: Any, name: str, default: Any = None) -> Any:
    """Read resolver/session structures; these are not catalog entity data."""

    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _action_value(action: Any) -> str:
    value = getattr(action, "value", action)
    return str(value or "").strip().casefold()


def action_from_intent(intent: Any) -> Action:
    """Map legacy intent values at the compatibility boundary."""

    value = _action_value(intent)
    if value in {Action.CALLBACK.value, Action.OPEN_LEAD_FORM.value}:
        return Action.OPEN_LEAD_FORM
    if value in Action._value2member_map_:
        return Action(value)
    return INTENT_TO_ACTION.get(value, Action.FALLBACK)


def select_route(
    focus: Any,
    action: Any,
    pending: Any = None,
) -> RouteName:
    """Select a route using only resolved state shape and one shared action.

    The user's raw message, catalog contents, and LLM are intentionally not inputs to
    this function, keeping dispatch deterministic and easy to test.
    """

    if pending is not None and pending is not False:
        return "clarification"

    selected_action = action_from_intent(action)
    if selected_action in {
        Action.OPEN_LEAD_FORM,
        Action.CALLBACK,
        Action.UNSUPPORTED_ENTITY,
        Action.UNRELATED,
        Action.FALLBACK,
    }:
        return "fallback"
    if selected_action is Action.CLARIFY:
        return "clarification"
    if selected_action is Action.LIST_SPECIALIZATIONS:
        return "list_specializations"
    if selected_action is Action.LIST_PROVIDERS:
        return "list_providers"
    if selected_action is Action.RECOMMEND:
        return "advisory"
    if selected_action is Action.COMPARE:
        return "comparison"
    if selected_action in {Action.DISCOVERY, Action.CHITCHAT}:
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

    if selected_action is Action.GET_FACTS:
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
    "list_specializations": handle_list_specializations,
    "list_providers": handle_list_providers,
    "fallback": handle_fallback,
}


async def dispatch_route(
    state: Any,
    action: Any,
    message: str,
    catalog: Any = None,
    category_index: Any = None,
    llm: Any = None,
    *,
    candidates: Sequence[Any] | None = None,
    categories: Sequence[str] | None = None,
    universities: Sequence[Any] | None = None,
    entity_ids: Sequence[str] | None = None,
    common_category: str | None = None,
    specializations: Sequence[Sequence[Any]] | None = None,
    allow_single_university: bool = False,
    advisory_candidate_ids: Sequence[str] | None = None,
    entity: Any = None,
    topic: str | None = None,
    category: str | None = None,
    specialization_candidates: Sequence[Any] | None = None,
) -> ResponsePayload:
    """Select and invoke one async handler, returning the canonical payload."""

    focus = _value(state, "focus")
    pending = _value(state, "pending_clarification")
    selected_action = action_from_intent(action)
    route_name = select_route(focus, selected_action, pending)

    common = {
        "state": state,
        "message": message,
        "catalog": catalog,
        "category_index": category_index,
        "llm": llm,
    }
    if selected_action is Action.LIST_SPECIALIZATIONS:
        return await handle_list_specializations(**common, category=category)
    if selected_action is Action.LIST_PROVIDERS:
        return await handle_list_providers(
            **common,
            specialization_candidates=specialization_candidates,
        )
    if route_name == "clarification":
        pending_candidates = _value(pending, "candidates", ())
        return await handle_clarification(
            **common,
            candidates=candidates if candidates is not None else pending_candidates,
            slot_type=_value(pending, "slot_type"),
        )
    if route_name == "comparison":
        return await handle_comparison(
            **common,
            categories=categories,
            universities=universities,
            entity_ids=entity_ids,
            common_category=common_category,
            specializations=specializations,
            allow_single_university=allow_single_university,
        )
    if route_name == "advisory":
        return await handle_advisory(
            **common,
            candidate_ids=advisory_candidate_ids,
        )
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
        action: Any,
        message: str,
        **kwargs: Any,
    ) -> ResponsePayload:
        return await dispatch_route(
            state=state,
            action=action,
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
    "INTENT_TO_ACTION",
    "Action",
    "RouteName",
    "Router",
    "action_from_intent",
    "dispatch",
    "dispatch_route",
    "route",
    "route_message",
    "select_route",
]
