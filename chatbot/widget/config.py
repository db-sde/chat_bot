"""Strict, file-backed configuration for each widget installation.

The site key is a public configuration selector, not an authentication secret.
This module deliberately accepts presentation and display-behaviour fields only;
API destinations, arbitrary CSS/HTML, origins, and credentials do not belong in
the browser-readable configuration document.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

DEFAULT_WIDGET_CONFIG_PATH = Path(__file__).with_name("configs.json")
WIDGET_CONFIG_PATH_ENV = "WIDGET_CONFIG_PATH"

_SITE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class WidgetConfigLoadError(ValueError):
    """Raised when the configuration file is missing, malformed, or invalid."""


class InvalidSiteKeyError(ValueError):
    """Raised when a requested or configured site key has an unsafe shape."""


class UnknownSiteKeyError(KeyError):
    """Raised when no widget configuration exists for an otherwise valid site key."""

    def __init__(self, site_key: str) -> None:
        self.site_key = site_key
        super().__init__(f"Unknown widget site_key: {site_key}")


def _validate_site_key(site_key: object) -> str:
    if not isinstance(site_key, str) or not _SITE_KEY_RE.fullmatch(site_key):
        raise InvalidSiteKeyError(
            "site_key must be 1-64 ASCII letters, digits, dots, underscores, or hyphens"
        )
    return site_key


def _plain_text(value: str, *, field_name: str) -> str:
    if _CONTROL_CHARACTER_RE.search(value):
        raise ValueError(f"{field_name} contains a control character")
    return value


class WidgetConfig(BaseModel):
    """The complete browser-readable configuration for one site key."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    bot_name: str = Field(min_length=1, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=2048)
    primary_color: str = Field(pattern=_HEX_COLOR_RE.pattern)
    welcome_message: str = Field(min_length=1, max_length=500)
    show_typing_indicator: StrictBool
    show_avatar: StrictBool
    auto_open: StrictBool

    @field_validator("bot_name", "welcome_message")
    @classmethod
    def validate_plain_text(cls, value: str, info: Any) -> str:
        return _plain_text(value, field_name=info.field_name)

    @field_validator("primary_color")
    @classmethod
    def normalize_primary_color(cls, value: str) -> str:
        return value.upper()

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _plain_text(value, field_name="avatar_url")
        if value.startswith("/") and not value.startswith("//"):
            return value

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("avatar_url must be an http(s) URL or a root-relative path")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("avatar_url must not include user information")
        return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WidgetConfigLoadError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_document(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise WidgetConfigLoadError(f"Unable to read widget config {path}: {error}") from error
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except WidgetConfigLoadError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise WidgetConfigLoadError(f"Invalid widget config JSON in {path}: {error}") from error
    if not isinstance(payload, Mapping) or not payload:
        raise WidgetConfigLoadError("Widget config must be a non-empty object keyed by site_key")
    return payload


class WidgetConfigStore:
    """Atomically load and resolve immutable widget configurations from JSON.

    Passing ``path`` is useful for tests and custom deployments. Otherwise the
    ``WIDGET_CONFIG_PATH`` environment variable may point at a deployment-owned
    file, with the bundled ``configs.json`` used as the final default. When
    ``auto_reload`` is enabled, a changed file is validated and atomically swapped
    before the next lookup.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        auto_reload: bool = True,
    ) -> None:
        configured_path = path or os.getenv(WIDGET_CONFIG_PATH_ENV) or DEFAULT_WIDGET_CONFIG_PATH
        self.path = Path(configured_path).expanduser()
        self.auto_reload = auto_reload
        self._lock = RLock()
        self._configs: Mapping[str, WidgetConfig] = MappingProxyType({})
        self._mtime_ns: int | None = None
        self.reload()

    @property
    def site_keys(self) -> tuple[str, ...]:
        self._reload_if_changed()
        with self._lock:
            return tuple(sorted(self._configs))

    def reload(self) -> None:
        """Validate the whole file, then replace the current snapshot atomically."""

        document = _load_document(self.path)
        loaded: dict[str, WidgetConfig] = {}
        for raw_site_key, raw_config in document.items():
            try:
                site_key = _validate_site_key(raw_site_key)
                loaded[site_key] = WidgetConfig.model_validate(raw_config)
            except (InvalidSiteKeyError, ValidationError) as error:
                raise WidgetConfigLoadError(
                    f"Invalid widget configuration for site_key {raw_site_key!r}: {error}"
                ) from error

        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except OSError as error:
            raise WidgetConfigLoadError(
                f"Unable to stat widget config {self.path}: {error}"
            ) from error
        with self._lock:
            self._configs = MappingProxyType(loaded)
            self._mtime_ns = mtime_ns

    def _reload_if_changed(self) -> None:
        if not self.auto_reload:
            return
        try:
            current_mtime = self.path.stat().st_mtime_ns
        except OSError as error:
            raise WidgetConfigLoadError(
                f"Unable to stat widget config {self.path}: {error}"
            ) from error
        with self._lock:
            unchanged = current_mtime == self._mtime_ns
        if not unchanged:
            self.reload()

    def get(self, site_key: str) -> WidgetConfig:
        """Return one config; unknown valid keys fail closed with a typed error."""

        key = _validate_site_key(site_key)
        self._reload_if_changed()
        with self._lock:
            config = self._configs.get(key)
        if config is None:
            raise UnknownSiteKeyError(key)
        return config

    def try_get(self, site_key: str) -> WidgetConfig | None:
        """Return ``None`` for an unknown valid key while still rejecting invalid keys."""

        try:
            return self.get(site_key)
        except UnknownSiteKeyError:
            return None

    def payload(self, site_key: str) -> dict[str, Any]:
        """Build the public HTTP response for ``/api/widget/config/{site_key}``."""

        config = self.get(site_key)
        return {
            "site_key": site_key,
            "branding": {
                "bot_name": config.bot_name,
                "avatar_url": config.avatar_url,
                "primary_color": config.primary_color,
                "welcome_message": config.welcome_message,
            },
            "behavior": {
                "show_typing_indicator": config.show_typing_indicator,
                "show_avatar": config.show_avatar,
                "auto_open": config.auto_open,
            },
        }

    def snapshot(self) -> Mapping[str, WidgetConfig]:
        """Return an immutable snapshot for diagnostics and tests."""

        self._reload_if_changed()
        with self._lock:
            return MappingProxyType(dict(self._configs))


__all__ = [
    "DEFAULT_WIDGET_CONFIG_PATH",
    "WIDGET_CONFIG_PATH_ENV",
    "InvalidSiteKeyError",
    "UnknownSiteKeyError",
    "WidgetConfig",
    "WidgetConfigLoadError",
    "WidgetConfigStore",
]
