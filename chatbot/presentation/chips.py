"""Transport adapters for config-owned funnel chips."""

from __future__ import annotations

from collections.abc import Iterable

from funnel import FollowupChipSet, OpeningChipSet, ResolvedChip
from schemas import QuickAction


def chip_message(chip: ResolvedChip) -> str:
    if chip.handler == "tool_entry" and chip.tool:
        return f"tool:{chip.tool}"
    if chip.handler == "cta_apply":
        return "Apply now"
    if chip.handler == "cta_callback":
        return "Talk to a counsellor"
    # Labels are deterministic config content and every non-tool handler already
    # has a matching guided-widget adapter or ordinary NLU phrase.
    return chip.label


def resolved_chip_action(
    chip: ResolvedChip,
    *,
    surface: str,
    config_version: str,
    content_version: str = "not_applicable",
    interaction_count: int = 0,
    correlation_id: str | None = None,
    lead_tags: dict[str, object] | None = None,
) -> QuickAction:
    return QuickAction(
        label=chip.label,
        message=chip_message(chip),
        chip_id=chip.id,
        chip_handler=chip.handler,
        tool=chip.tool,  # type: ignore[arg-type]
        surface=surface,
        funnel_stage=chip.funnel_stage.value,
        config_version=config_version,
        content_version=content_version,
        interaction_count=max(0, int(interaction_count)),
        correlation_id=correlation_id,
        lead_tags=lead_tags,
    )


def chip_actions(
    chips: Iterable[ResolvedChip],
    *,
    surface: str,
    config_version: str,
    content_version: str = "not_applicable",
    interaction_count: int = 0,
    correlation_id: str | None = None,
    lead_tags: dict[str, object] | None = None,
) -> list[QuickAction]:
    return [
        resolved_chip_action(
            chip,
            surface=surface,
            config_version=config_version,
            content_version=content_version,
            interaction_count=interaction_count,
            correlation_id=correlation_id,
            lead_tags=lead_tags,
        )
        for chip in chips
    ]


def opening_payload(
    opening: OpeningChipSet,
    *,
    correlation_id: str | None = None,
) -> dict[str, object]:
    return {
        "surface": opening.surface,
        "funnel_stage": (
            opening.top[0].funnel_stage.value
            if opening.top
            else opening.more[0].funnel_stage.value if opening.more else "top"
        ),
        "config_version": opening.config_version,
        "content_version": "not_applicable",
        "interaction_count": 0,
        "correlation_id": correlation_id,
        "missing_surface": opening.missing_surface,
        "top": [
            action.model_dump(mode="json", exclude_none=True)
            for action in chip_actions(
                opening.top,
                surface=opening.surface,
                config_version=opening.config_version,
                correlation_id=correlation_id,
            )
        ],
        "more": [
            action.model_dump(mode="json", exclude_none=True)
            for action in chip_actions(
                opening.more,
                surface=opening.surface,
                config_version=opening.config_version,
                correlation_id=correlation_id,
            )
        ],
    }


def followup_payload(
    followup: FollowupChipSet,
    *,
    correlation_id: str | None = None,
    content_version: str = "not_applicable",
) -> dict[str, object]:
    return {
        "surface": followup.surface,
        "funnel_stage": followup.funnel_stage.value,
        "interaction_count": followup.interaction_count,
        "config_version": followup.config_version,
        "content_version": content_version,
        "correlation_id": correlation_id,
        "missing_surface": followup.missing_surface,
        "actions": [
            action.model_dump(mode="json", exclude_none=True)
            for action in chip_actions(
                followup.chips,
                surface=followup.surface,
                config_version=followup.config_version,
                content_version=content_version,
                interaction_count=followup.interaction_count,
                correlation_id=correlation_id,
            )
        ],
    }


__all__ = [
    "chip_actions",
    "chip_message",
    "followup_payload",
    "opening_payload",
    "resolved_chip_action",
]
