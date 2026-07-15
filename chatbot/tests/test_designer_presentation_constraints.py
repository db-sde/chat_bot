from __future__ import annotations

from presentation import enrich_response
from schemas import ResponsePayload


def test_widget_message_is_bounded_without_truncating_legacy_text() -> None:
    legacy = " ".join(f"published-{index}." for index in range(80))

    payload = enrich_response(ResponsePayload(text=legacy))

    assert payload.text == legacy
    assert payload.message is not None
    assert len(payload.message.split()) <= 50
    assert payload.message != payload.text

