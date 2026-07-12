"""Deterministic route selection and response handlers."""

from .advisory_handler import handle_advisory
from .category_handler import handle_category
from .clarification_handler import handle_clarification
from .comparison_handler import handle_comparison
from .discovery_handler import handle_discovery
from .factual_handler import handle_factual
from .fallback_handler import handle_fallback
from .knowledge_handler import handle_knowledge
from .list_handler import handle_list_providers, handle_list_specializations
from .router import Action, Router, action_from_intent, dispatch_route, select_route

__all__ = [
    "Action",
    "Router",
    "action_from_intent",
    "dispatch_route",
    "handle_advisory",
    "handle_category",
    "handle_clarification",
    "handle_comparison",
    "handle_discovery",
    "handle_factual",
    "handle_fallback",
    "handle_knowledge",
    "handle_list_providers",
    "handle_list_specializations",
    "select_route",
]
