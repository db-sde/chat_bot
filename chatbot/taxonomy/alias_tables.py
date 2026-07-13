"""Text normalization shared by catalog-derived taxonomy indexes."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

SlotType = str


def normalize_text(value: object) -> str:
    """Return a stable, accent-free, lowercase lookup key."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", text))


# Retain the legacy symbols as empty compatibility shims. Runtime aliases are
# generated from the active catalog by ``taxonomy.index_builder``.
CURATED_ALIASES: Mapping[SlotType, Mapping[str, tuple[str, ...]]] = {}


def aliases_for(slot_type: str) -> Mapping[str, tuple[str, ...]]:
    """Return normalized aliases for one slot type."""

    aliases = CURATED_ALIASES.get(slot_type, {})
    return {
        normalize_text(alias): tuple(normalize_text(target) for target in targets)
        for alias, targets in aliases.items()
    }


__all__ = ["CURATED_ALIASES", "SlotType", "aliases_for", "normalize_text"]
