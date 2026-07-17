"""Strict, versioned content for the deterministic chatbot tools.

The loader follows the widget configuration pattern: a complete document is
validated before it replaces the live snapshot.  A bad hot reload is reported
and the last valid snapshot remains usable.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

LOGGER = logging.getLogger(__name__)

ToolId = Literal["roi", "career_quiz", "scholarship"]
KNOWN_TOOLS = frozenset({"roi", "career_quiz", "scholarship"})
DEFAULT_TOOLS_CONTENT_PATH = Path(__file__).resolve().parents[2] / "data" / "tools_content.json"
TOOLS_CONTENT_PATH_ENV = "TOOLS_CONTENT_PATH"


class ToolsContentLoadError(ValueError):
    """The configured tool content could not be read or validated."""


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ToolOption(ContentModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=300)
    weights: dict[str, float] = Field(default_factory=dict)
    correct: bool | None = None
    value: str | int | float | None = None


class ToolStep(ContentModel):
    id: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=1000)
    type: Literal["choice", "entity", "bucket", "text"] = "choice"
    options: tuple[ToolOption, ...] = ()
    buckets: tuple[ToolOption, ...] = ()
    value_period: Literal["monthly", "annual"] | None = None

    @property
    def choices(self) -> tuple[ToolOption, ...]:
        return self.buckets if self.type == "bucket" else self.options

    @model_validator(mode="after")
    def validate_choices(self) -> ToolStep:
        choices = self.choices
        if self.type in {"choice", "bucket"} and not choices:
            raise ValueError(f"step {self.id!r} requires answer options")
        ids = [option.id.casefold() for option in choices]
        if len(ids) != len(set(ids)):
            raise ValueError(f"step {self.id!r} contains duplicate option ids")
        return self


class RewardBand(ContentModel):
    min_correct: int = Field(ge=0)
    max_correct: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_range(self) -> RewardBand:
        if self.max_correct < self.min_correct:
            raise ValueError("reward band max_correct must be >= min_correct")
        return self


class ToolDefinition(ContentModel):
    # Production documents from the supplied schema become active once their
    # required content is complete. The bundled placeholder opts out explicitly.
    enabled: bool = True
    entry_copy: str = Field(default="", max_length=1000)
    unavailable_reason: str | None = Field(default=None, max_length=1000)
    steps: tuple[ToolStep, ...] = ()
    question_bank: dict[str, tuple[ToolStep, ...]] = Field(default_factory=dict)
    reward_bands: tuple[RewardBand, ...] = ()

    @model_validator(mode="after")
    def validate_step_identity(self) -> ToolDefinition:
        groups = [self.steps, *self.question_bank.values()]
        for steps in groups:
            ids = [step.id.casefold() for step in steps]
            if len(ids) != len(set(ids)):
                raise ValueError("tool definition contains duplicate step ids")
        ordered = sorted(self.reward_bands, key=lambda band: band.min_correct)
        for previous, current in pairwise(ordered):
            if current.min_correct <= previous.max_correct:
                raise ValueError("scholarship reward bands must not overlap")
        return self


class ToolsContentDocument(ContentModel):
    version: str = Field(min_length=1, max_length=100)
    tools: dict[str, ToolDefinition]

    @model_validator(mode="after")
    def validate_tool_ids(self) -> ToolsContentDocument:
        unknown = set(self.tools) - KNOWN_TOOLS
        if unknown:
            raise ValueError(f"unknown tool ids: {', '.join(sorted(unknown))}")
        return self


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ToolsContentLoadError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def _read_document(path: Path) -> ToolsContentDocument:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ToolsContentLoadError(f"Unable to read tools content {path}: {error}") from error
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except ToolsContentLoadError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ToolsContentLoadError(f"Invalid tools content JSON in {path}: {error}") from error
    if not isinstance(payload, Mapping):
        raise ToolsContentLoadError("Tools content must be a JSON object")
    try:
        return ToolsContentDocument.model_validate(payload)
    except ValidationError as error:
        raise ToolsContentLoadError(f"Invalid tools content in {path}: {error}") from error


class ToolsContentStore:
    """Atomically hot-reload tool content and retain recent version snapshots."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        auto_reload: bool = True,
        retained_versions: int = 8,
    ) -> None:
        configured = path or os.getenv(TOOLS_CONTENT_PATH_ENV) or DEFAULT_TOOLS_CONTENT_PATH
        self.path = Path(configured).expanduser()
        self.auto_reload = auto_reload
        self.retained_versions = max(2, retained_versions)
        self._lock = RLock()
        self._document: ToolsContentDocument | None = None
        self._versions: dict[str, ToolsContentDocument] = {}
        self._mtime_ns: int | None = None
        self._failed_mtime_ns: int | None = None
        self._last_error: str | None = None
        self.reload()

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    @property
    def version(self) -> str:
        self._reload_if_changed()
        with self._lock:
            assert self._document is not None
            return self._document.version

    def reload(self) -> None:
        """Validate a complete new snapshot before swapping it into service."""

        document = _read_document(self.path)
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError as error:
            raise ToolsContentLoadError(
                f"Unable to stat tools content {self.path}: {error}"
            ) from error
        with self._lock:
            existing = self._versions.get(document.version)
            if existing is not None and existing != document:
                raise ToolsContentLoadError(
                    "tools content changed without a new version identifier"
                )
            self._document = document
            self._versions[document.version] = document
            while len(self._versions) > self.retained_versions:
                oldest = next(iter(self._versions))
                if oldest == document.version and len(self._versions) > 1:
                    oldest = next(key for key in self._versions if key != document.version)
                self._versions.pop(oldest, None)
            self._mtime_ns = mtime_ns
            self._failed_mtime_ns = None
            self._last_error = None

    def refresh(self) -> bool:
        """Try a hot reload, returning ``False`` while retaining last-good on failure."""

        try:
            self.reload()
        except ToolsContentLoadError as error:
            try:
                failed_mtime = self.path.stat().st_mtime_ns
            except OSError:
                failed_mtime = None
            with self._lock:
                if self._document is None:
                    raise
                self._failed_mtime_ns = failed_mtime
                self._last_error = str(error)
            LOGGER.warning("Tools content reload failed; retaining last-good snapshot: %s", error)
            return False
        return True

    def _reload_if_changed(self) -> None:
        if not self.auto_reload:
            return
        try:
            current_mtime = self.path.stat().st_mtime_ns
        except OSError as error:
            with self._lock:
                has_snapshot = self._document is not None
                self._last_error = str(error)
            if has_snapshot:
                LOGGER.warning("Tools content stat failed; retaining last-good snapshot: %s", error)
                return
            raise ToolsContentLoadError(
                f"Unable to stat tools content {self.path}: {error}"
            ) from error
        with self._lock:
            unchanged = current_mtime in {self._mtime_ns, self._failed_mtime_ns}
        if not unchanged:
            self.refresh()

    def snapshot(self, *, version: str | None = None) -> ToolsContentDocument | None:
        self._reload_if_changed()
        with self._lock:
            if version is not None:
                return self._versions.get(version)
            return self._document

    def get(self, tool_id: str, *, version: str | None = None) -> ToolDefinition | None:
        document = self.snapshot(version=version)
        return document.tools.get(tool_id) if document is not None else None

    def versions(self) -> Mapping[str, ToolsContentDocument]:
        with self._lock:
            return MappingProxyType(dict(self._versions))


__all__ = [
    "DEFAULT_TOOLS_CONTENT_PATH",
    "KNOWN_TOOLS",
    "TOOLS_CONTENT_PATH_ENV",
    "RewardBand",
    "ToolDefinition",
    "ToolId",
    "ToolOption",
    "ToolStep",
    "ToolsContentDocument",
    "ToolsContentLoadError",
    "ToolsContentStore",
]
