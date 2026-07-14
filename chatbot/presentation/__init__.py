"""Additive rich-response presentation layer."""

from .cards import (
    build_comparison_card,
    build_comparison_card_from_text,
    build_entity_card,
    build_lead_cta,
    build_program_card,
    build_quick_actions,
    build_university_card,
)
from .formatter import advisor_message, comparison_items_from_text
from .response_builder import enrich_response

__all__ = [
    "advisor_message",
    "build_comparison_card",
    "build_comparison_card_from_text",
    "build_entity_card",
    "build_lead_cta",
    "build_program_card",
    "build_quick_actions",
    "build_university_card",
    "comparison_items_from_text",
    "enrich_response",
]
