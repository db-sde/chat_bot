"""Defensive access helpers for publisher data.

Handlers use :func:`safe_get` instead of assuming fields survived ingestion. It accepts
mapping keys, Pydantic attributes/aliases, sequence indexes, and dotted/bracket paths.
Malformed input always resolves to the supplied default.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

_BRACKET_TOKEN = re.compile(r"\[\s*(?:'([^']*)'|\"([^\"]*)\"|([^\]]+))\s*\]")
_MISSING = object()


def _parts(path: str | int | Sequence[str | int] | None) -> list[str | int]:
    if path is None or path == "":
        return []
    if isinstance(path, int):
        return [path]
    if isinstance(path, str):
        normalized = _BRACKET_TOKEN.sub(
            lambda match: "." + next(
                group for group in match.groups() if group is not None
            ).strip(),
            path,
        )
        return [part for part in normalized.split(".") if part != ""]
    if isinstance(path, Sequence):
        return list(path)
    return []


def _model_value(model: BaseModel, part: str | int) -> Any:
    if not isinstance(part, str):
        return _MISSING
    fields = type(model).model_fields
    if part in fields:
        return getattr(model, part, _MISSING)
    for name, field in fields.items():
        if field.alias == part or field.serialization_alias == part:
            return getattr(model, name, _MISSING)
    extra = model.model_extra or {}
    return extra.get(part, _MISSING)


def _step(value: Any, part: str | int) -> Any:
    if isinstance(value, Mapping):
        if part in value:
            return value[part]
        # Dotted paths naturally produce string indexes; numeric mapping keys are
        # still supported without changing ordinary string-key behavior.
        if isinstance(part, str) and part.lstrip("-").isdigit():
            return value.get(int(part), _MISSING)
        return _MISSING
    if isinstance(value, BaseModel):
        return _model_value(value, part)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            index = part if isinstance(part, int) else int(part)
            return value[index]
        except (IndexError, TypeError, ValueError):
            return _MISSING
    if isinstance(part, str):
        try:
            return getattr(value, part, _MISSING)
        except Exception:
            return _MISSING
    return _MISSING


def safe_get(
    obj: Any,
    path: str | int | Sequence[str | int] | None,
    default: Any = None,
) -> Any:
    """Read ``path`` from dictionaries, models, and lists without ever raising.

    Explicit ``null``/``None`` values are preserved when they are the final value.
    If traversal must continue through one, ``default`` is returned.
    """

    try:
        parts = _parts(path)
        current = obj
        for part in parts:
            if current is None:
                return default
            current = _step(current, part)
            if current is _MISSING:
                return default
        return current
    except Exception:
        return default

