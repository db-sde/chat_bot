"""Validated node transitions paired with the hot-reloadable chip map."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .chip_config import ChipMapStore

logger = logging.getLogger(__name__)

DEFAULT_FLOW_MAP_PATH = Path(__file__).resolve().parents[1] / "data" / "flow_map.json"
TERMINAL = "TERMINAL"
SPLIT = "SPLIT"
RESERVED_DESTINATIONS = frozenset({TERMINAL, SPLIT})


class FlowMapLoadError(ValueError):
    """Raised when no valid flow-map snapshot can be loaded."""


class FlowMapConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    version: str = Field(min_length=1, max_length=80)
    surfaces: dict[str, dict[str, str]]


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FlowMapLoadError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_document(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise FlowMapLoadError(f"Unable to read flow map {path}: {error}") from error
    try:
        document = json.loads(raw, object_pairs_hook=_unique_json_object)
    except FlowMapLoadError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise FlowMapLoadError(f"Invalid flow map JSON in {path}: {error}") from error
    if not isinstance(document, Mapping):
        raise FlowMapLoadError("Flow map must be a JSON object")
    return document


class FlowMapStore:
    """Atomically serve a flow map validated against the current chip map."""

    def __init__(
        self,
        chip_store: ChipMapStore,
        path: str | Path | None = None,
        *,
        auto_reload: bool = True,
        retained_versions: int = 8,
    ) -> None:
        self.chip_store = chip_store
        self.path = Path(path or chip_store.path.with_name("flow_map.json")).expanduser()
        self.auto_reload = auto_reload
        self.retained_versions = max(2, int(retained_versions))
        self._lock = RLock()
        self._snapshot: FlowMapConfig | None = None
        self._versions: dict[str, FlowMapConfig] = {}
        self._observed_mtime_ns: int | None = None
        self._chip_version: str | None = None
        self.reload()

    def _validated_snapshot(self) -> tuple[FlowMapConfig, int, str]:
        document = _load_document(self.path)
        try:
            flow = FlowMapConfig.model_validate(document)
        except ValidationError as error:
            raise FlowMapLoadError(f"Invalid flow map {self.path}: {error}") from error

        chips = self.chip_store.snapshot()
        if flow.version != chips.version:
            raise FlowMapLoadError(
                f"Flow-map version {flow.version!r} does not match "
                f"chip-map version {chips.version!r}"
            )
        flow_surfaces = set(flow.surfaces)
        chip_surfaces = set(chips.surfaces)
        missing_sources = sorted(chip_surfaces.difference(flow_surfaces))
        extra_sources = sorted(flow_surfaces.difference(chip_surfaces))
        if missing_sources or extra_sources:
            details = []
            if missing_sources:
                details.append("missing surfaces: " + ", ".join(missing_sources))
            if extra_sources:
                details.append("unknown surfaces: " + ", ".join(extra_sources))
            raise FlowMapLoadError(
                "Flow map must cover the chip map exactly (" + "; ".join(details) + ")"
            )

        for surface_key, surface in chips.surfaces.items():
            declared = set((*surface.top, *surface.more, *surface.follow))
            mapped = set(flow.surfaces[surface_key])
            missing_chips = sorted(declared.difference(mapped))
            extra_chips = sorted(mapped.difference(declared))
            if missing_chips or extra_chips:
                details = []
                if missing_chips:
                    details.append("missing chips: " + ", ".join(missing_chips))
                if extra_chips:
                    details.append("unknown chips: " + ", ".join(extra_chips))
                raise FlowMapLoadError(
                    f"Flow surface {surface_key!r} does not match its chip surface ("
                    + "; ".join(details)
                    + ")"
                )
            for chip_id, destination in flow.surfaces[surface_key].items():
                if destination not in RESERVED_DESTINATIONS and destination not in chips.surfaces:
                    raise FlowMapLoadError(
                        f"Flow transition {surface_key}.{chip_id} references unknown surface "
                        f"{destination!r}"
                    )
                handler = chips.chips[chip_id].handler
                if destination == TERMINAL and handler not in {"cta_apply", "cta_callback"}:
                    raise FlowMapLoadError(
                        f"Terminal transition {surface_key}.{chip_id} must use a CTA handler"
                    )
                if destination == SPLIT and handler not in {
                    "get_eligible_programs",
                    "get_specializations",
                    "list_programs",
                    "list_providers",
                    "list_universities",
                }:
                    raise FlowMapLoadError(
                        f"Split transition {surface_key}.{chip_id} must use a picker handler"
                    )

        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError as error:
            raise FlowMapLoadError(f"Unable to stat flow map {self.path}: {error}") from error
        return flow, mtime_ns, chips.version

    def reload(self) -> FlowMapConfig:
        """Replace both-version-compatible content or retain the last-good snapshot."""

        try:
            candidate, mtime_ns, chip_version = self._validated_snapshot()
        except FlowMapLoadError as error:
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
                "Flow map reload failed; keeping last-good config version %s: %s",
                previous.version,
                error,
            )
            return previous

        with self._lock:
            previous = self._snapshot
            existing = self._versions.get(candidate.version)
            if existing is not None and existing != candidate:
                self._observed_mtime_ns = mtime_ns
                self._chip_version = chip_version
                logger.warning(
                    "Flow map changed without a new version identifier; keeping last-good config"
                )
                return previous or existing
            self._snapshot = candidate
            self._versions[candidate.version] = candidate
            while len(self._versions) > self.retained_versions:
                oldest = next(iter(self._versions))
                if oldest == candidate.version and len(self._versions) > 1:
                    oldest = next(
                        version
                        for version in self._versions
                        if version != candidate.version
                    )
                self._versions.pop(oldest, None)
            self._observed_mtime_ns = mtime_ns
            self._chip_version = chip_version
        return candidate

    def _reload_if_changed(self) -> None:
        if not self.auto_reload:
            return
        chips = self.chip_store.snapshot()
        try:
            current_mtime = self.path.stat().st_mtime_ns
        except OSError:
            self.reload()
            return
        with self._lock:
            unchanged = (
                current_mtime == self._observed_mtime_ns
                and chips.version == self._chip_version
            )
        if not unchanged:
            self.reload()

    def snapshot(self, *, version: str | None = None) -> FlowMapConfig | None:
        self._reload_if_changed()
        with self._lock:
            if version is not None:
                return self._versions.get(version)
            if self._snapshot is None:  # pragma: no cover - constructor guarantees it
                raise FlowMapLoadError("Flow map has no valid snapshot")
            return self._snapshot


__all__ = [
    "DEFAULT_FLOW_MAP_PATH",
    "RESERVED_DESTINATIONS",
    "SPLIT",
    "TERMINAL",
    "FlowMapConfig",
    "FlowMapLoadError",
    "FlowMapStore",
]
