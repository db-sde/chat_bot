"""Validated, hot-reloadable chip-map configuration with last-good fallback."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Collection, Mapping
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

DEFAULT_CHIP_MAP_PATH = Path(__file__).resolve().parents[1] / "data" / "chip_map.json"
CHIP_MAP_PATH_ENV = "CHIP_MAP_PATH"

# This is deliberately a small contract registry rather than a dynamic import
# mechanism. Integration code owns the adapter from these stable handler names to
# the existing widget/router actions.
DEFAULT_HANDLER_REGISTRY = frozenset(
    {
        "compare",
        "cta_apply",
        "cta_callback",
        "get_admission_steps",
        "get_average_rating",
        "get_approvals",
        "get_careers",
        "get_eligibility",
        "get_eligible_programs",
        "get_fees",
        "get_overview",
        "get_placement_support",
        "get_reviews",
        "get_specializations",
        "get_syllabus",
        "get_validity",
        "list_programs",
        "list_providers",
        "list_universities",
        "tool_entry",
    }
)


class ChipMapLoadError(ValueError):
    """Raised when no valid chip-map snapshot can be loaded."""


class FunnelStage(StrEnum):
    TOP = "top"
    MID = "mid"
    BOTTOM = "bottom"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ABVariant(_FrozenModel):
    """Preserved for future experiment assignment; the engine does not select it."""

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)


class ChipDefinition(_FrozenModel):
    handler: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    tool: str | None = Field(default=None, min_length=1, max_length=80)
    funnel_stage: FunnelStage
    fill: dict[str, str] | None = None
    requires: tuple[str, ...] = ()
    ab: tuple[ABVariant, ...] = ()

    @model_validator(mode="after")
    def validate_renderable_definition(self) -> ChipDefinition:
        if self.label is None and not self.ab:
            raise ValueError("chip requires a label or preserved A/B variants")
        if self.handler == "tool_entry" and not self.tool:
            raise ValueError("tool_entry chips require a tool id")
        if self.handler != "tool_entry" and self.tool:
            raise ValueError("only tool_entry chips may declare a tool id")
        return self


class SurfaceDefinition(_FrozenModel):
    funnel_stage: FunnelStage
    top: tuple[str, ...] = ()
    more: tuple[str, ...] = ()
    follow: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_shape(self) -> SurfaceDefinition:
        opening = bool(self.top or self.more)
        following = bool(self.follow)
        if opening == following:
            raise ValueError("surface must define opening top/more or follow, not both")
        values = (*self.top, *self.more, *self.follow)
        if len(values) != len(set(values)):
            raise ValueError("surface chip ids must be unique")
        return self


class FAQChipConfig(_FrozenModel):
    source: str = "faqs"
    count: int = Field(default=3, ge=0, le=6)


class ProgressionConfig(_FrozenModel):
    escalate_after: int = Field(default=3, ge=1, le=20)
    conversion_chips: tuple[str, ...] = ("apply_now", "counsellor")
    tool_reveal_priority: tuple[str, ...] = (
        "apply_now",
        "counsellor",
        "compare",
    )


class ChipMapConfig(_FrozenModel):
    version: str = Field(min_length=1, max_length=80)
    chips: dict[str, ChipDefinition]
    surfaces: dict[str, SurfaceDefinition]
    faq_chips: FAQChipConfig = Field(default_factory=FAQChipConfig)
    progression: ProgressionConfig = Field(default_factory=ProgressionConfig)

    @model_validator(mode="after")
    def validate_references(self) -> ChipMapConfig:
        referenced: set[str] = set(self.progression.conversion_chips)
        referenced.update(self.progression.tool_reveal_priority)
        for surface in self.surfaces.values():
            referenced.update(surface.top)
            referenced.update(surface.more)
            referenced.update(surface.follow)
        missing = sorted(referenced.difference(self.chips))
        if missing:
            raise ValueError(f"unknown chip id(s): {', '.join(missing)}")

        unrenderable = sorted(
            chip_id for chip_id in referenced if self.chips[chip_id].label is None
        )
        if unrenderable:
            raise ValueError(
                "referenced chips require a base label until A/B assignment is enabled: "
                + ", ".join(unrenderable)
            )

        if not self.progression.conversion_chips:
            raise ValueError("at least one conversion chip is required")
        for chip_id in self.progression.conversion_chips:
            if self.chips[chip_id].handler not in {"cta_apply", "cta_callback"}:
                raise ValueError(f"conversion chip {chip_id!r} must use a CTA handler")

        expected_priority = ("apply_now", "counsellor", "compare")
        if self.progression.tool_reveal_priority != expected_priority:
            raise ValueError(
                "tool reveal priority must be apply_now, counsellor, compare"
            )

        conversion_ids = set(self.progression.conversion_chips)
        for key, surface in self.surfaces.items():
            if not key.startswith("page:"):
                continue
            if not conversion_ids.intersection((*surface.top, *surface.more)):
                raise ValueError(f"opening surface {key!r} requires a conversion chip")
        return self


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ChipMapLoadError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_document(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ChipMapLoadError(f"Unable to read chip map {path}: {error}") from error
    try:
        document = json.loads(raw, object_pairs_hook=_unique_json_object)
    except ChipMapLoadError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ChipMapLoadError(f"Invalid chip map JSON in {path}: {error}") from error
    if not isinstance(document, Mapping):
        raise ChipMapLoadError("Chip map must be a JSON object")
    return document


class ChipMapStore:
    """Serve one validated snapshot and retain it when a hot reload is invalid."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        handler_registry: Collection[str] = DEFAULT_HANDLER_REGISTRY,
        auto_reload: bool = True,
        retained_versions: int = 8,
    ) -> None:
        configured = path or os.getenv(CHIP_MAP_PATH_ENV) or DEFAULT_CHIP_MAP_PATH
        self.path = Path(configured).expanduser()
        self.handler_registry = frozenset(handler_registry)
        self.auto_reload = auto_reload
        self.retained_versions = max(2, int(retained_versions))
        self._lock = RLock()
        self._snapshot: ChipMapConfig | None = None
        self._versions: dict[str, ChipMapConfig] = {}
        self._observed_mtime_ns: int | None = None
        self.reload()

    def _validated_snapshot(self) -> tuple[ChipMapConfig, int]:
        document = _load_document(self.path)
        try:
            config = ChipMapConfig.model_validate(document)
        except ValidationError as error:
            raise ChipMapLoadError(f"Invalid chip map {self.path}: {error}") from error

        unknown_handlers = sorted(
            {
                chip.handler
                for chip in config.chips.values()
                if chip.handler not in self.handler_registry
            }
        )
        if unknown_handlers:
            raise ChipMapLoadError(
                "Chip map references unregistered handler(s): "
                + ", ".join(unknown_handlers)
            )
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError as error:
            raise ChipMapLoadError(f"Unable to stat chip map {self.path}: {error}") from error
        return config, mtime_ns

    def reload(self) -> ChipMapConfig:
        """Atomically replace the map, or return the previous valid map on failure."""

        try:
            candidate, mtime_ns = self._validated_snapshot()
        except ChipMapLoadError as error:
            try:
                observed_mtime = self.path.stat().st_mtime_ns
            except OSError:
                observed_mtime = None
            with self._lock:
                previous = self._snapshot
                self._observed_mtime_ns = observed_mtime
            if previous is None:
                raise
            logger.warning(
                "Chip map reload failed; keeping last-good config version %s: %s",
                previous.version,
                error,
            )
            return previous

        with self._lock:
            previous = self._snapshot
            existing = self._versions.get(candidate.version)
            if (
                existing is not None
                and existing != candidate
            ):
                self._observed_mtime_ns = mtime_ns
                logger.warning(
                    "Chip map changed without a new version identifier; keeping last-good config"
                )
                return previous or existing
            self._snapshot = candidate
            self._versions[candidate.version] = candidate
            while len(self._versions) > self.retained_versions:
                oldest = next(iter(self._versions))
                if oldest == candidate.version and len(self._versions) > 1:
                    oldest = next(
                        version for version in self._versions if version != candidate.version
                    )
                self._versions.pop(oldest, None)
            self._observed_mtime_ns = mtime_ns
        return candidate

    def _reload_if_changed(self) -> None:
        if not self.auto_reload:
            return
        try:
            current_mtime = self.path.stat().st_mtime_ns
        except OSError:
            # Let reload() apply the same initial-failure/last-good contract.
            self.reload()
            return
        with self._lock:
            unchanged = current_mtime == self._observed_mtime_ns
        if not unchanged:
            self.reload()

    def snapshot(self, *, version: str | None = None) -> ChipMapConfig | None:
        self._reload_if_changed()
        with self._lock:
            if version is not None:
                return self._versions.get(version)
            if self._snapshot is None:  # pragma: no cover - constructor guarantees it
                raise ChipMapLoadError("Chip map has no valid snapshot")
            return self._snapshot


__all__ = [
    "CHIP_MAP_PATH_ENV",
    "DEFAULT_CHIP_MAP_PATH",
    "DEFAULT_HANDLER_REGISTRY",
    "ABVariant",
    "ChipDefinition",
    "ChipMapConfig",
    "ChipMapLoadError",
    "ChipMapStore",
    "FAQChipConfig",
    "FunnelStage",
    "ProgressionConfig",
    "SurfaceDefinition",
]
