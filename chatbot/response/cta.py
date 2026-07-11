"""Pure CTA factories.

The lead funnel decides *when* a CTA should appear.  These helpers only construct a
schema-compatible value once that decision has been made.
"""

from __future__ import annotations

from typing import Any


def lead_capture_cta(
    *,
    label: str = "Talk to a counsellor",
    action: str = "start_lead_capture",
) -> dict[str, Any]:
    return {"label": label, "action": action}


def callback_cta() -> dict[str, Any]:
    return lead_capture_cta(label="Request a callback", action="request_callback")


__all__ = ["callback_cta", "lead_capture_cta"]
