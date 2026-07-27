"""Shared deterministic lifecycle for the three admissions tools."""

from __future__ import annotations

import random
import re
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, unquote

from pydantic import BaseModel, ConfigDict, Field

from schemas import QuickAction, ResponsePayload
from session.state import ActiveFlow

from .content import (
    KNOWN_TOOLS,
    ToolDefinition,
    ToolsContentStore,
    ToolStep,
)

ToolStatus = Literal["ok", "content_unavailable", "cannot_compute"]
LifecycleStep = Literal[
    "enter",
    "question",
    "compute",
    "partial_reveal",
    "await_lead",
    "reveal",
    "exit",
]

_CONTINUE_TOKENS = frozenset(
    {
        "continue",
        "continue to full result",
        "continue to see full result",
        "tool:continue",
    }
)
_ANSWER_TOKEN = re.compile(r"^tool:answer:([^:]+):(.+)$", re.IGNORECASE)
logger = logging.getLogger(__name__)
_PUBLIC_UNAVAILABLE = (
    "This result is not available for the selected option right now. "
    "You can continue exploring or talk to a counsellor."
)


class ToolResult(BaseModel):
    """Backend-owned result shared by every tool implementation."""

    model_config = ConfigDict(extra="forbid")

    status: ToolStatus = "ok"
    partial: dict[str, Any] = Field(default_factory=dict)
    full: dict[str, Any] = Field(default_factory=dict)
    cta_program_ids: list[str] = Field(default_factory=list)
    lead_tags: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ToolTurn:
    """One tool transition plus its normal ``ResponsePayload`` transport."""

    response: ResponsePayload
    tool: str
    lifecycle: LifecycleStep
    content_version: str = "not_applicable"
    answered_step: str | None = None
    consumed: bool = True
    escaped: bool = False
    completed: bool = False
    needs_lead: bool = False
    replaced_tool: str | None = None
    result: ToolResult | None = None


EntityResolver = Callable[[str], str | None]
ProgramLookup = Callable[[str], Sequence[str]]
AttemptGuard = Callable[[Any, str], bool]


def unavailable_result(tool: str, reason: str) -> ToolResult:
    message = " ".join(str(reason or "").split()) or (
        "This tool does not have enough configured content or catalog data to run safely."
    )
    return ToolResult(
        status="content_unavailable",
        partial={"message": message},
        full={"message": message},
        lead_tags={"tool": tool, "result_status": "content_unavailable"},
        reason=message,
    )


def _actions(items: Sequence[tuple[str, str]]) -> list[QuickAction]:
    return [QuickAction(label=label, message=message) for label, message in items]


def _response(
    text: str,
    *,
    actions: Sequence[tuple[str, str]] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ResponsePayload:
    quick_actions = _actions(actions)
    return ResponsePayload(
        text=" ".join(str(text or "").split())
        or "This tool cannot continue with the available information.",
        quick_actions=quick_actions,
        metadata=dict(metadata or {}),
    )


def _unavailable_turn(
    tool: str,
    reason: str,
    *,
    content_version: str = "not_applicable",
    answered_step: str | None = None,
    replaced_tool: str | None = None,
    result: ToolResult | None = None,
) -> ToolTurn:
    result = result or unavailable_result(tool, reason)
    logger.warning("%s tool unavailable: %s", tool, result.reason or reason)
    return ToolTurn(
        response=_response(
            _PUBLIC_UNAVAILABLE,
            metadata={
                "tool_flow": {
                    "tool": tool,
                    "step": "exit",
                    "status": result.status,
                    "version": content_version,
                }
            },
        ),
        tool=tool,
        lifecycle="exit",
        content_version=content_version,
        answered_step=answered_step,
        completed=True,
        replaced_tool=replaced_tool,
        result=result,
    )


def _state_flow(state: Any) -> ActiveFlow | None:
    value = getattr(state, "active_flow", None)
    if value is None:
        return None
    if isinstance(value, ActiveFlow):
        return value
    return ActiveFlow.model_validate(value)


def _set_flow(state: Any, flow: ActiveFlow | None) -> None:
    state.active_flow = flow


def _scholarship_bank_key(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("question_bank_key") or payload.get("program_id")
    rendered = " ".join(str(value or "").split())
    return rendered or None


def _draw_scholarship_questions(definition: ToolDefinition) -> tuple[ToolStep, ...]:
    """Draw the configured per-tier count at random (spec: 2 easy, 2 medium, 2 hard).

    Option order is shuffled per draw so a repeat visitor cannot pattern-match a
    position; `correct` is stored by option id, so shuffling is safe.
    """

    drawn: list[ToolStep] = []
    for difficulty, count in definition.serve.items():
        pool = list(definition.question_bank.get(difficulty, ()))
        if len(pool) < count:
            return ()
        for question in random.sample(pool, count):
            options = list(question.choices)
            random.shuffle(options)
            drawn.append(question.model_copy(update={"options": tuple(options)}))
    return tuple(drawn)


def _steps_for(
    tool: str,
    definition: ToolDefinition,
    payload: Mapping[str, Any],
) -> tuple[tuple[ToolStep, ...], str | None]:
    if not definition.enabled:
        return (), definition.unavailable_reason or "This tool has not been configured yet."
    if tool == "scholarship":
        # Setup question (fee model → waiver pool) + a random draw from the bank.
        # The draw is recorded in the flow payload on entry so every turn of the
        # same session serves the identical questions in the identical order.
        if definition.setup is None:
            return (), "The scholarship fee-model question is not configured."
        served_ids = payload.get("served_question_ids")
        bank = {
            step.id: step
            for steps in definition.question_bank.values()
            for step in steps
        }
        if isinstance(served_ids, (list, tuple)) and served_ids:
            order = payload.get("served_option_order")
            order = order if isinstance(order, Mapping) else {}
            served_list: list[ToolStep] = []
            for qid in served_ids:
                question = bank.get(qid)
                if question is None:
                    return (), "A served scholarship question is no longer in the bank."
                frozen = order.get(qid)
                if isinstance(frozen, (list, tuple)) and frozen:
                    by_id = {option.id: option for option in question.choices}
                    options = tuple(by_id[oid] for oid in frozen if oid in by_id)
                    if len(options) == len(question.choices):
                        question = question.model_copy(update={"options": options})
                served_list.append(question)
            served = tuple(served_list)
        else:
            served = _draw_scholarship_questions(definition)
            if not served:
                return (), "The scholarship question bank is not configured."
        if not definition.reward_bands:
            return (), "Scholarship reward bands have not been configured."
        return (definition.setup, *served), None
    if tool == "career_quiz":
        if not 5 <= len(definition.steps) <= 7:
            return (), "A complete five-to-seven-question career quiz has not been configured."
        return definition.steps, None
    if tool == "roi":
        ids = {step.id for step in definition.steps}
        if "program" not in ids or not any(step_id.startswith("current_salary") for step_id in ids):
            return (), "The ROI program and current-salary questions are not configured."
        return definition.steps, None
    return (), "Unknown tool."


def _step_for(flow: ActiveFlow, steps: Sequence[ToolStep]) -> ToolStep | None:
    return next((step for step in steps if step.id == flow.step), None)


def _step_position(step: ToolStep, steps: Sequence[ToolStep]) -> int | None:
    """Return the 1-based position of one step inside the configured bank."""

    for position, candidate in enumerate(steps, start=1):
        if candidate.id == step.id:
            return position
    return None


def _question_turn(
    flow: ActiveFlow,
    step: ToolStep,
    *,
    entry_copy: str = "",
    nudge: str = "",
    answered_step: str | None = None,
    replaced_tool: str | None = None,
    steps: Sequence[ToolStep] = (),
) -> ToolTurn:
    visible_steps = tuple(
        candidate
        for candidate in steps
        if not (candidate.type == "entity" and candidate.id in flow.answers)
    )
    action_pairs = [
        (
            option.label,
            f"tool:answer:{quote(step.id, safe='')}:{quote(option.id, safe='')}",
        )
        for option in step.choices
    ]
    parts = [entry_copy, nudge, step.prompt]
    text = "\n\n".join(part.strip() for part in parts if part and part.strip())
    return ToolTurn(
        response=_response(
            text,
            actions=action_pairs,
            metadata={
                "tool_flow": {
                    "tool": flow.tool,
                    "step": step.id,
                    "lifecycle": "question",
                    "version": flow.version,
                    # The rendered text collapses entry copy, nudge and prompt
                    # into one string. Publish the parts separately so a client
                    # can lay them out without re-deriving them.
                    "prompt": step.prompt,
                    "entry_copy": entry_copy or None,
                    "step_index": _step_position(step, visible_steps),
                    "step_total": len(visible_steps) or None,
                }
            },
        ),
        tool=flow.tool,
        lifecycle="question",
        content_version=flow.version or "not_applicable",
        answered_step=answered_step,
        replaced_tool=replaced_tool,
    )


def _catalog_entity(catalog: Any, identifier: str) -> Any:
    if catalog is None:
        return None
    for method_name in ("get_entity", "get", "by_id"):
        method = getattr(catalog, method_name, None)
        if callable(method):
            try:
                value = method(identifier)
            except (KeyError, TypeError, ValueError):
                continue
            if value is not None:
                return value
    if isinstance(catalog, Mapping):
        return catalog.get(identifier)
    return None


def _token_answer(message: str, expected_step: str) -> str | None:
    match = _ANSWER_TOKEN.fullmatch(message.strip())
    if match is None or unquote(match.group(1)).casefold() != expected_step.casefold():
        return None
    return unquote(match.group(2))


def _validate_answer(
    step: ToolStep,
    message: str,
    *,
    catalog: Any,
    entity_resolver: EntityResolver | None,
) -> tuple[str, Any, str | None] | None:
    token_value = _token_answer(message, step.id)
    raw = token_value if token_value is not None else " ".join(message.strip().split())
    if step.type in {"choice", "bucket", "factor", "lead_tag"}:
        selected = next(
            (
                option
                for option in step.choices
                if raw.casefold() in {option.id.casefold(), option.label.casefold()}
            ),
            None,
        )
        if selected is None:
            return None
        return selected.id, selected.value, step.value_period
    if step.type == "entity":
        entity_id = entity_resolver(raw) if entity_resolver is not None else None
        if entity_id is None and _catalog_entity(catalog, raw) is not None:
            entity_id = raw
        if not entity_id:
            return None
        return str(entity_id), str(entity_id), None
    if step.type == "text" and raw:
        return raw, raw, None
    return None


def _render_result_text(values: Mapping[str, Any], fallback: str) -> str:
    for key in ("message", "headline", "summary"):
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def _score(
    flow: ActiveFlow,
    definition: ToolDefinition,
    *,
    catalog: Any,
    program_lookup: ProgramLookup | None,
) -> ToolResult:
    if flow.tool == "roi":
        from .roi import score_roi

        return score_roi(flow.answers, flow.payload, catalog, definition=definition)
    if flow.tool == "career_quiz":
        from .career_quiz import score_career_quiz

        return score_career_quiz(
            flow.answers,
            definition,
            catalog,
            program_lookup=program_lookup,
        )
    if flow.tool == "scholarship":
        from .scholarship import score_scholarship

        return score_scholarship(flow.answers, definition, flow.payload, catalog)
    return unavailable_result(flow.tool, "Unknown tool.")


def enter(
    state: Any,
    tool_id: str,
    catalog: Any = None,
    *,
    content_store: ToolsContentStore | None = None,
    initial_payload: Mapping[str, Any] | None = None,
    attempt_guard: AttemptGuard | None = None,
) -> ToolTurn:
    """Replace any current tool and render the first configured question."""

    store = content_store or default_content_store()
    tool = str(tool_id).strip().casefold()
    previous = _state_flow(state)
    replaced_tool = previous.tool if previous is not None else None
    content_version = store.version or "not_applicable"
    if tool not in KNOWN_TOOLS:
        _set_flow(state, None)
        return _unavailable_turn(
            tool,
            "Unknown tool.",
            content_version=content_version,
            replaced_tool=replaced_tool,
        )
    if attempt_guard is not None and not attempt_guard(state, tool):
        _set_flow(state, None)
        return _unavailable_turn(
            tool,
            "This tool is not available for another attempt in the current journey.",
            content_version=content_version,
            replaced_tool=replaced_tool,
        )
    if tool == "scholarship":
        attempts = getattr(state, "tool_attempts", {})
        if isinstance(attempts, Mapping) and int(attempts.get("scholarship", 0) or 0) > 0:
            _set_flow(state, None)
            return _unavailable_turn(
                tool,
                "The scholarship checker has already been completed in this session.",
                content_version=content_version,
                replaced_tool=replaced_tool,
            )
    definition = store.get(tool)
    if definition is None:
        _set_flow(state, None)
        return _unavailable_turn(
            tool,
            "This tool is missing from the configured content.",
            content_version=content_version,
            replaced_tool=replaced_tool,
        )
    payload = dict(initial_payload or {})
    steps, reason = _steps_for(tool, definition, payload)
    if reason is not None:
        _set_flow(state, None)
        return _unavailable_turn(
            tool,
            reason,
            content_version=content_version,
            replaced_tool=replaced_tool,
        )
    if tool == "scholarship":
        # Freeze this session's draw (ids + shuffled option order) so every
        # later turn re-renders exactly the questions the user is answering.
        payload["served_question_ids"] = [step.id for step in steps[1:]]
        payload["served_option_order"] = {
            step.id: [option.id for option in step.choices] for step in steps[1:]
        }
    flow = ActiveFlow(
        tool=tool,
        step=steps[0].id,
        answers={},
        payload=payload,
        version=content_version,
    )
    # An `entity` step has no tappable options, so in a chips-only widget it can
    # only be answered from the session's active program. Pre-fill it and open
    # on the first question the user can actually act on (spec: ROI Q1 is
    # "resolved via the existing entity matcher, or pre-filled").
    first = steps[0]
    if first.type == "entity":
        resolved = str(payload.get("program_id") or "").strip()
        if resolved and _catalog_entity(catalog, resolved) is not None:
            flow.answers[first.id] = resolved
            values = flow.payload.setdefault("answer_values", {})
            if isinstance(values, dict):
                values[first.id] = resolved
            if len(steps) > 1:
                flow.step = steps[1].id
                first = steps[1]
    _set_flow(state, flow)
    return _question_turn(
        flow,
        first,
        entry_copy=definition.entry_copy,
        replaced_tool=replaced_tool,
        steps=steps,
    )


def abandon(state: Any, *, reason: str = "new_intent") -> ToolTurn | None:
    flow = _state_flow(state)
    if flow is None:
        return None
    _set_flow(state, None)
    return ToolTurn(
        response=_response(
            "Tool closed. You can continue with the guided options.",
            metadata={
                "tool_flow": {
                    "tool": flow.tool,
                    "step": "exit",
                    "status": "abandoned",
                    "reason": reason,
                    "version": flow.version or "not_applicable",
                }
            },
        ),
        tool=flow.tool,
        lifecycle="exit",
        content_version=flow.version or "not_applicable",
        consumed=False,
        escaped=True,
    )


def dispatch(
    state: Any,
    message: str,
    catalog: Any = None,
    *,
    content_store: ToolsContentStore | None = None,
    entity_resolver: EntityResolver | None = None,
    program_lookup: ProgramLookup | None = None,
    lead_complete: bool = False,
    lead_cancelled: bool = False,
) -> ToolTurn | None:
    """Validate and advance one active flow without invoking NLU or an LLM."""

    flow = _state_flow(state)
    if flow is None:
        return None
    store = content_store or default_content_store()
    content_version = flow.version or store.version or "not_applicable"
    definition = store.get(flow.tool, version=content_version)
    if definition is None:
        _set_flow(state, None)
        return _unavailable_turn(
            flow.tool,
            f"Tool content version {content_version!r} is no longer available.",
            content_version=content_version,
        )
    steps, reason = _steps_for(flow.tool, definition, flow.payload)
    if reason is not None:
        _set_flow(state, None)
        return _unavailable_turn(
            flow.tool,
            reason,
            content_version=content_version,
        )

    if flow.step == "partial_reveal":
        valid_continue = message.strip().casefold() in _CONTINUE_TOKENS
        if not valid_continue:
            result = ToolResult.model_validate(flow.payload.get("result", {}))
            return ToolTurn(
                response=_response(
                    _render_result_text(result.partial, "Your partial result is ready."),
                    actions=(("Continue to full result", "tool:continue"),),
                    metadata={
                        "tool_flow": {
                            "tool": flow.tool,
                            "step": "partial_reveal",
                            "version": flow.version,
                        }
                    },
                ),
                tool=flow.tool,
                lifecycle="partial_reveal",
                content_version=content_version,
                result=result,
            )
        if lead_complete:
            return _reveal(state, flow)
        flow.step = "await_lead"
        return ToolTurn(
            response=_response(
                "Continue with the contact step to reveal the full result.",
                actions=(("Talk to a counsellor", "Call me"),),
                metadata={
                    "tool_flow": {
                        "tool": flow.tool,
                        "step": "await_lead",
                        "requires_lead": True,
                        "version": flow.version,
                    }
                },
            ),
            tool=flow.tool,
            lifecycle="await_lead",
            content_version=content_version,
            needs_lead=True,
            result=ToolResult.model_validate(flow.payload.get("result", {})),
        )

    if flow.step == "await_lead":
        if lead_cancelled:
            return abandon(state, reason="lead_cancelled")
        if not lead_complete:
            return ToolTurn(
                response=_response(
                    "The full result is ready after the contact step is completed.",
                    actions=(("Talk to a counsellor", "Call me"),),
                    metadata={
                        "tool_flow": {
                            "tool": flow.tool,
                            "step": "await_lead",
                            "requires_lead": True,
                            "version": flow.version,
                        }
                    },
                ),
                tool=flow.tool,
                lifecycle="await_lead",
                content_version=content_version,
                needs_lead=True,
                result=ToolResult.model_validate(flow.payload.get("result", {})),
            )
        return _reveal(state, flow)

    step = _step_for(flow, steps)
    if step is None:
        _set_flow(state, None)
        return _unavailable_turn(
            flow.tool,
            f"Unknown tool step {flow.step!r}.",
            content_version=content_version,
        )
    validated = _validate_answer(
        step,
        message,
        catalog=catalog,
        entity_resolver=entity_resolver,
    )
    if validated is None:
        return _question_turn(
            flow,
            step,
            nudge="Please choose one of the available answers.",
            steps=steps,
        )

    answer_id, answer_value, value_period = validated
    flow.answers[step.id] = answer_id
    values = flow.payload.setdefault("answer_values", {})
    if answer_value is not None and isinstance(values, dict):
        values[step.id] = answer_value
    periods = flow.payload.setdefault("answer_periods", {})
    if value_period is not None and isinstance(periods, dict):
        periods[step.id] = value_period

    index = next(index for index, candidate in enumerate(steps) if candidate.id == step.id)
    if index + 1 < len(steps):
        flow.step = steps[index + 1].id
        return _question_turn(
            flow,
            steps[index + 1],
            answered_step=step.id,
            steps=steps,
        )

    flow.step = "compute"
    result = _score(flow, definition, catalog=catalog, program_lookup=program_lookup)
    flow.payload["result"] = result.model_dump(mode="json")
    if flow.tool == "scholarship" and result.status == "ok":
        # Count the attempt as soon as a waiver exists, not at reveal. Counting
        # later would let a user abandon at the lead gate and re-roll for a
        # better score — the retake-until-max hole the waiver rule closes.
        attempts = getattr(state, "tool_attempts", None)
        if isinstance(attempts, dict):
            attempts["scholarship"] = int(attempts.get("scholarship", 0) or 0) + 1
    if result.status == "content_unavailable":
        _set_flow(state, None)
        return _unavailable_turn(
            flow.tool,
            result.reason or "The result could not be computed.",
            content_version=content_version,
            answered_step=step.id,
            result=result,
        )
    flow.step = "partial_reveal"
    return ToolTurn(
        response=_response(
            _render_result_text(result.partial, "Your partial result is ready."),
            actions=(("Continue to full result", "tool:continue"),),
            metadata={
                "tool_flow": {
                    "tool": flow.tool,
                    "step": "partial_reveal",
                    "status": result.status,
                    "version": flow.version,
                }
            },
        ),
        tool=flow.tool,
        lifecycle="partial_reveal",
        content_version=content_version,
        answered_step=step.id,
        result=result,
    )


def _reveal(state: Any, flow: ActiveFlow) -> ToolTurn:
    result = ToolResult.model_validate(flow.payload.get("result", {}))
    flow.step = "reveal"
    _set_flow(state, None)
    return ToolTurn(
        response=_response(
            _render_result_text(result.full, "Your full result is ready."),
            metadata={
                "tool_flow": {
                    "tool": flow.tool,
                    "step": "reveal",
                    "status": result.status,
                    "version": flow.version,
                    "cta_program_ids": result.cta_program_ids,
                    "lead_tags": result.lead_tags,
                    "result": dict(result.full),
                }
            },
        ),
        tool=flow.tool,
        lifecycle="reveal",
        content_version=flow.version or "not_applicable",
        completed=True,
        result=result,
    )


def current(
    state: Any,
    catalog: Any = None,
    *,
    content_store: ToolsContentStore | None = None,
) -> ToolTurn | None:
    """Render the persisted ActiveFlow step without advancing or clearing it."""

    del catalog  # Reserved for entity-backed resume views without mutating state.
    flow = _state_flow(state)
    if flow is None:
        return None
    store = content_store or default_content_store()
    content_version = flow.version or store.version or "not_applicable"
    definition = store.get(flow.tool, version=content_version)
    if definition is None:
        return _unavailable_turn(
            flow.tool,
            f"Tool content version {content_version!r} is no longer available.",
            content_version=content_version,
        )
    steps, reason = _steps_for(flow.tool, definition, flow.payload)
    if reason is not None:
        return _unavailable_turn(
            flow.tool,
            reason,
            content_version=content_version,
        )

    if flow.step == "partial_reveal":
        result = ToolResult.model_validate(flow.payload.get("result", {}))
        return ToolTurn(
            response=_response(
                _render_result_text(result.partial, "Your partial result is ready."),
                actions=(("Continue to full result", "tool:continue"),),
                metadata={
                    "tool_flow": {
                        "tool": flow.tool,
                        "step": "partial_reveal",
                        "status": result.status,
                        "version": content_version,
                    }
                },
            ),
            tool=flow.tool,
            lifecycle="partial_reveal",
            content_version=content_version,
            result=result,
        )
    if flow.step == "await_lead":
        result = ToolResult.model_validate(flow.payload.get("result", {}))
        return ToolTurn(
            response=_response(
                "The full result is ready after the contact step is completed.",
                actions=(("Talk to a counsellor", "Call me"),),
                metadata={
                    "tool_flow": {
                        "tool": flow.tool,
                        "step": "await_lead",
                        "requires_lead": True,
                        "version": content_version,
                    }
                },
            ),
            tool=flow.tool,
            lifecycle="await_lead",
            content_version=content_version,
            needs_lead=True,
            result=result,
        )

    step = _step_for(flow, steps)
    if step is None:
        return _unavailable_turn(
            flow.tool,
            f"Unknown tool step {flow.step!r}.",
            content_version=content_version,
        )
    return _question_turn(flow, step, steps=steps)


def resume_view(
    state: Any,
    catalog: Any = None,
    *,
    content_store: ToolsContentStore | None = None,
) -> ToolTurn | None:
    """Compatibility name for the read-only current ActiveFlow view."""

    return current(state, catalog, content_store=content_store)


_DEFAULT_STORE: ToolsContentStore | None = None


def default_content_store() -> ToolsContentStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = ToolsContentStore()
    return _DEFAULT_STORE


def resume_after_lead(
    state: Any,
    catalog: Any = None,
    *,
    content_store: ToolsContentStore | None = None,
) -> ToolTurn | None:
    """Reveal a persisted tool result immediately after the lead funnel completes."""

    return dispatch(
        state,
        "",
        catalog,
        content_store=content_store,
        lead_complete=True,
    )


class ToolEngine:
    """Dependency-bound facade for the guided widget service."""

    def __init__(
        self,
        content_store: ToolsContentStore | None = None,
        *,
        catalog: Any = None,
        entity_resolver: EntityResolver | None = None,
        program_lookup: ProgramLookup | None = None,
        attempt_guard: AttemptGuard | None = None,
    ) -> None:
        self.content_store = content_store or default_content_store()
        self.catalog = catalog
        self.entity_resolver = entity_resolver
        self.program_lookup = program_lookup
        self.attempt_guard = attempt_guard

    def enter(
        self,
        state: Any,
        tool_id: str,
        *,
        initial_payload: Mapping[str, Any] | None = None,
    ) -> ToolTurn:
        return enter(
            state,
            tool_id,
            self.catalog,
            content_store=self.content_store,
            initial_payload=initial_payload,
            attempt_guard=self.attempt_guard,
        )

    def dispatch(
        self,
        state: Any,
        message: str,
        *,
        lead_complete: bool = False,
        lead_cancelled: bool = False,
    ) -> ToolTurn | None:
        return dispatch(
            state,
            message,
            self.catalog,
            content_store=self.content_store,
            entity_resolver=self.entity_resolver,
            program_lookup=self.program_lookup,
            lead_complete=lead_complete,
            lead_cancelled=lead_cancelled,
        )

    def resume_after_lead(self, state: Any, catalog: Any = None) -> ToolTurn | None:
        return resume_after_lead(
            state,
            self.catalog if catalog is None else catalog,
            content_store=self.content_store,
        )

    def current(self, state: Any, catalog: Any = None) -> ToolTurn | None:
        return current(
            state,
            self.catalog if catalog is None else catalog,
            content_store=self.content_store,
        )

    def resume_view(self, state: Any, catalog: Any = None) -> ToolTurn | None:
        return self.current(state, catalog)

    @staticmethod
    def abandon(state: Any, *, reason: str = "new_intent") -> ToolTurn | None:
        return abandon(state, reason=reason)


__all__ = [
    "ToolEngine",
    "ToolResult",
    "ToolTurn",
    "abandon",
    "current",
    "default_content_store",
    "dispatch",
    "enter",
    "resume_after_lead",
    "resume_view",
    "unavailable_result",
]
