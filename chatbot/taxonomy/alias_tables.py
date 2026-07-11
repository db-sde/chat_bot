"""Small, deliberately curated aliases that outrank derived taxonomy matches.

The values are canonical-name hints rather than catalog ids.  Catalog ids differ
between environments, so :mod:`taxonomy.index_builder` resolves each hint against
the catalog while building an immutable index.
"""

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


# Keep this table intentionally small.  Values may contain more than one spelling
# of the same target, but an alias must never intentionally point at two concepts.
CURATED_ALIASES: Mapping[SlotType, Mapping[str, tuple[str, ...]]] = {
    "university": {
        "lpu": ("lovely professional university",),
    },
    "course": {
        # These are concept aliases.  They are resolved to ``category:*`` ids.
        "master of business administration": ("mba",),
        "masters of business administration": ("mba",),
        "master of computer applications": ("mca",),
        "masters of computer applications": ("mca",),
    },
    "specialization": {
        "hr": ("human resource management", "human resources management"),
        "human resources": ("human resource management",),
    },
}


def aliases_for(slot_type: str) -> Mapping[str, tuple[str, ...]]:
    """Return normalized aliases for one slot type."""

    aliases = CURATED_ALIASES.get(slot_type, {})
    return {
        normalize_text(alias): tuple(normalize_text(target) for target in targets)
        for alias, targets in aliases.items()
    }


__all__ = ["CURATED_ALIASES", "SlotType", "aliases_for", "normalize_text"]
