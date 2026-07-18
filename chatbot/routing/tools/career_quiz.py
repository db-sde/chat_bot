"""Configured weighted scoring for the career-path quiz."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .base import ToolResult, unavailable_result
from .content import ToolDefinition, ToolOption


def _selected_option(options: Sequence[ToolOption], answer: str | None) -> ToolOption | None:
    if answer is None:
        return None
    return next((option for option in options if option.id == answer), None)


def score_career_quiz(
    answers: Mapping[str, str],
    definition: ToolDefinition,
    catalog: Any = None,
    *,
    program_lookup: Callable[[str], Sequence[str]] | None = None,
) -> ToolResult:
    """Sum configured option weights and resolve programs for one unique winner."""

    del catalog  # Retrieval must use the existing category/index adapter supplied by integration.
    if not 5 <= len(definition.steps) <= 7:
        return unavailable_result(
            "career_quiz",
            "A complete five-to-seven-question career quiz has not been configured.",
        )
    weights: dict[str, float] = defaultdict(float)
    for step in definition.steps:
        selected = _selected_option(step.choices, answers.get(step.id))
        if selected is None:
            return unavailable_result("career_quiz", f"Career answer {step.id!r} is missing.")
        if not selected.weights:
            return unavailable_result(
                "career_quiz",
                f"Career weight mappings are missing for answer {step.id!r}.",
            )
        for discipline, weight in selected.weights.items():
            weights[discipline] += weight
    if not weights:
        return unavailable_result("career_quiz", "Career discipline mappings are not configured.")
    highest = max(weights.values())
    winners = sorted(discipline for discipline, score in weights.items() if score == highest)
    if len(winners) != 1 and definition.tie_break == "last_answer":
        for step in reversed(definition.steps):
            selected = _selected_option(step.choices, answers.get(step.id))
            if selected is None:
                continue
            winner = next(
                (discipline for discipline in selected.weights if discipline in winners),
                None,
            )
            if winner is not None:
                winners = [winner]
                break
    if len(winners) != 1:
        return ToolResult(
            status="cannot_compute",
            partial={"message": "The configured quiz produced a tied career result."},
            full={"message": "The configured quiz produced a tied career result."},
            lead_tags={"tool": "career_quiz", "result_status": "tied"},
            reason="No tie-break rule is configured for the top disciplines.",
        )
    discipline = winners[0]
    if program_lookup is None:
        return unavailable_result(
            "career_quiz",
            "The career discipline-to-program lookup has not been connected.",
        )
    program_ids = list(dict.fromkeys(str(value) for value in program_lookup(discipline) if value))[
        :3
    ]
    if not program_ids:
        return unavailable_result(
            "career_quiz",
            f"No published program mapping is configured for {discipline}.",
        )
    job_profile = definition.job_profiles.get(discipline) or definition.job_profiles.get("default")
    partial_template = definition.partial_reveal_template or (
        "Your strongest configured match is {discipline}."
    )
    full_template = definition.full_reveal_template or (
        "Your highest weighted career-quiz discipline is {discipline}."
    )
    return ToolResult(
        partial={"headline": partial_template.format(discipline=discipline, area=discipline)},
        full={
            "message": full_template.format(discipline=discipline, area=discipline),
            "top_discipline": discipline,
            "weights": dict(sorted(weights.items())),
            **({"job_profile": job_profile} if job_profile else {}),
        },
        cta_program_ids=program_ids,
        lead_tags={"tool": "career_quiz", "top_discipline": discipline},
    )


__all__ = ["score_career_quiz"]
