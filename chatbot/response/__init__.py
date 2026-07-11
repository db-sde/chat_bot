"""Response construction and deterministic presentation helpers."""

from .builder import build_response, normalize_chips
from .cta import callback_cta, lead_capture_cta
from .templates import render_topic, suggested_chips, topic_from_message

__all__ = [
    "build_response",
    "callback_cta",
    "lead_capture_cta",
    "normalize_chips",
    "render_topic",
    "suggested_chips",
    "topic_from_message",
]
