"""Resolve referential language against the current focus without changing it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

REFERENCE_RE = re.compile(
    r"\b(?:it|this\s+(?:program|course|degree|university|one)|that\s+(?:program|course|university|one)|the\s+university)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ReferenceResolution:
    used_focus: bool
    reference: str | None
    focus: Any
    mentions: Any


def _has_mentions(mentions: object) -> bool:
    explicit = getattr(mentions, "has_explicit_mentions", None)
    if isinstance(explicit, bool):
        return explicit
    return any(
        bool(getattr(mentions, name, None))
        for name in ("universities", "courses", "specializations")
    )


def resolve_reference(
    mentions: object,
    state: object,
    *,
    raw_input: str | None = None,
) -> ReferenceResolution:
    reference = getattr(mentions, "reference", None)
    if reference is None and raw_input and REFERENCE_RE.search(raw_input):
        reference = "entity"
    used_focus = bool(reference) and not _has_mentions(mentions)
    return ReferenceResolution(
        used_focus=used_focus,
        reference=str(reference) if reference else None,
        focus=getattr(state, "focus", state),
        mentions=mentions,
    )


# Plural spelling mirrors the request lifecycle wording.
resolve_references = resolve_reference


class ReferenceResolver:
    def resolve(
        self,
        mentions: object,
        state: object,
        *,
        raw_input: str | None = None,
    ) -> ReferenceResolution:
        return resolve_reference(mentions, state, raw_input=raw_input)


__all__ = [
    "ReferenceResolution",
    "ReferenceResolver",
    "resolve_reference",
    "resolve_references",
]
