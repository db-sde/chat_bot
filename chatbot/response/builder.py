"""Canonical response-payload construction."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from schemas import (
    CTA,
    LeadCTAComponent,
    QuickAction,
    QuickActionsComponent,
    ResponseComponent,
    ResponsePayload,
)


def normalize_chips(chips: Iterable[Any] | None, *, limit: int = 6) -> list[str]:
    """Trim, deduplicate, and cap suggested chips while preserving order."""

    result: list[str] = []
    seen: set[str] = set()
    for chip in chips or ():
        value = str(chip).strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _component_type(component: Any) -> str:
    if isinstance(component, dict):
        return str(component.get("type", ""))
    return str(getattr(component, "type", ""))


def build_transport_components(
    *,
    suggested_chips: Iterable[Any] | None = None,
    cta: Any = None,
    components: Iterable[ResponseComponent | dict[str, Any]] | None = None,
) -> list[ResponseComponent | dict[str, Any]]:
    """Mirror legacy actions into additive, typed rich-response components."""

    result: list[ResponseComponent | dict[str, Any]] = list(components or ())
    component_types = {_component_type(component) for component in result}
    chips = normalize_chips(suggested_chips)

    if chips and "quick_actions" not in component_types:
        result.append(
            QuickActionsComponent(
                actions=[QuickAction(label=chip, message=chip) for chip in chips],
            )
        )

    if cta is not None and "lead_cta" not in component_types:
        typed_cta = cta if isinstance(cta, CTA) else CTA.model_validate(cta)
        result.append(
            LeadCTAComponent(
                label=typed_cta.label,
                action=typed_cta.action,
                url=typed_cta.url,
                payload=typed_cta.payload,
            )
        )
    return result


def build_response(
    text: Any,
    *,
    suggested_chips: Iterable[Any] | None = None,
    cta: Any = None,
    components: Iterable[ResponseComponent | dict[str, Any]] | None = None,
) -> ResponsePayload:
    """Build the one response shape accepted by every route."""

    rendered = str(text or "").strip()
    if not rendered:
        rendered = "What would you like to know about online universities or programs?"
    chips = normalize_chips(suggested_chips)
    return ResponsePayload(
        text=rendered,
        suggested_chips=chips,
        cta=cta,
        components=build_transport_components(
            suggested_chips=chips,
            cta=cta,
            components=components,
        ),
    )


__all__ = ["build_response", "build_transport_components", "normalize_chips"]
