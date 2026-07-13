"""Pure CTA factories.

The lead funnel decides *when* a CTA should appear.  These helpers only construct a
schema-compatible value once that decision has been made.
"""

from __future__ import annotations

from typing import Any

OPEN_LEAD_WIDGET = "OPEN_LEAD_WIDGET"


def lead_capture_cta(
    *,
    label: str = "Talk to a counsellor",
    action: str = "lead_capture",
) -> dict[str, Any]:
    return {
        "label": label,
        "action": action,
        "payload": {"target_action": OPEN_LEAD_WIDGET},
    }


def callback_cta() -> dict[str, Any]:
    return lead_capture_cta(label="Request a callback")


__all__ = ["OPEN_LEAD_WIDGET", "callback_cta", "lead_capture_cta"]
