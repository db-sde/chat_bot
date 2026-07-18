"""Load, validate, index, and retrieve DegreeBaba catalog envelopes."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from config import Settings, get_settings
from taxonomy.index_builder import normalize_category

from .models import CatalogEntity, Course, Specialization, University, parse_entity

logger = logging.getLogger(__name__)

PageType = Literal["university", "course", "specialization"]
SAMPLE_CATALOG_PATH = Path(__file__).with_name("catalog.sample.json")


class EntityMetadata(BaseModel):
    """Small immutable record used by taxonomy indexes."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    slug: str
    page_type: PageType
    canonical_name: str
    university_name: str | None = None
    program_name: str | None = None
    spec_name: str | None = None
    category: str | None = None
    specialization_name: str | None = None
    aliases: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "catalog-entity"


def _extract_category(program_name: str | None, explicit: str | None) -> str | None:
    # Catalog V3 uses ``category`` for a broad discipline bucket rather than
    # the degree code. Use the program name for those records while preserving
    # compatibility with earlier publisher data where category was the code.
    if explicit and explicit.strip() and explicit.casefold() not in {
        "university",
        "specialization",
        "management",
        "technology",
        "commerce",
        "undergraduate",
        "media",
    }:
        return normalize_category(explicit) or None
    return normalize_category(program_name) or None


def _records_from_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    if isinstance(payload.get("_meta"), Mapping):
        return [payload]
    for key in ("entities", "items", "results", "records", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    records: list[Mapping[str, Any]] = []
    for key in ("universities", "courses", "specializations"):
        value = payload.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, Mapping))
    if records:
        return records

    # Some database exports are keyed by record id instead of wrapping an array.
    for key, value in payload.items():
        if not isinstance(value, Mapping):
            continue
        item = dict(value)
        item.setdefault("id", str(key))
        records.append(item)
    return records


def _is_published(record: Mapping[str, Any]) -> bool:
    """Accept records by default, but honor common explicit publication flags."""

    for key in ("is_published", "published"):
        value = record.get(key)
        if isinstance(value, bool):
            return value
    status = str(record.get("publication_status") or record.get("status") or "").casefold()
    return status not in {"draft", "unpublished", "archived", "deleted", "private"}


def _unwrap_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Accept both flat publisher envelopes and common database wrapper shapes."""

    for key in ("content", "payload", "document", "entity"):
        nested = record.get(key)
        if isinstance(nested, Mapping) and isinstance(nested.get("_meta"), Mapping):
            value = dict(nested)
            for identity_key in ("id", "slug", "category", "aliases"):
                if identity_key not in value and identity_key in record:
                    value[identity_key] = record[identity_key]
            return value
    return dict(record)


class CatalogStore:
    """Process-wide, read-only catalog with O(1) id/slug retrieval."""

    def __init__(
        self,
        *,
        catalog_url: str | None = None,
        catalog_path: str | Path | None = None,
        timeout_seconds: float | None = None,
        settings: Settings | None = None,
        records: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        config = settings or get_settings()
        self.catalog_url = catalog_url if catalog_url is not None else config.catalog_url
        configured_path = catalog_path if catalog_path is not None else config.catalog_path
        self.catalog_path = Path(configured_path).expanduser() if configured_path else None
        self.timeout_seconds = timeout_seconds or config.catalog_timeout_seconds
        self._entities: dict[str, CatalogEntity] = {}
        self._metadata: dict[str, EntityMetadata] = {}
        self._slug_to_id: dict[str, str] = {}
        self.source: str | None = None
        if records is not None:
            self.replace(records)
            self.source = "provided records"

    @property
    def entities(self) -> dict[str, CatalogEntity]:
        return self._entities

    @property
    def metadata(self) -> dict[str, EntityMetadata]:
        return self._metadata

    @property
    def by_id(self) -> dict[str, CatalogEntity]:
        return self._entities

    @property
    def by_slug(self) -> dict[str, CatalogEntity]:
        return {
            slug: self._entities[entity_id]
            for slug, entity_id in self._slug_to_id.items()
        }

    def __len__(self) -> int:
        return len(self._entities)

    def __iter__(self):
        return iter(self._entities.values())

    async def _read_url(self) -> Any:
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(self.catalog_url)
            response.raise_for_status()
            return response.json()

    @staticmethod
    async def _read_path(path: Path) -> Any:
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return json.loads(raw)

    async def load(self, *, force: bool = False) -> CatalogStore:
        """Load the configured source, falling back to the bundled representative data."""

        if self._entities and not force:
            return self

        payload: Any = None
        source: str | None = None
        if self.catalog_url:
            try:
                payload = await self._read_url()
                source = self.catalog_url
            except Exception as error:
                logger.warning("Catalog URL load failed (%s): %s", self.catalog_url, error)
        if payload is None and self.catalog_path is not None:
            try:
                payload = await self._read_path(self.catalog_path)
                source = str(self.catalog_path)
            except Exception as error:
                logger.warning("Catalog path load failed (%s): %s", self.catalog_path, error)
        if payload is None:
            attempted = self.catalog_url or (str(self.catalog_path) if self.catalog_path else None)
            logger.error(
                "Catalog load failed for configured source '%s'; "
                "falling back to bundled sample catalog",
                attempted or "(none configured)",
            )
            payload = await self._read_path(SAMPLE_CATALOG_PATH)
            source = str(SAMPLE_CATALOG_PATH)

        records = _records_from_payload(payload)
        if not records:
            if source != str(SAMPLE_CATALOG_PATH):
                logger.error(
                    "Catalog source %s contained no entities; falling back to sample",
                    source,
                )
                payload = await self._read_path(SAMPLE_CATALOG_PATH)
                records = _records_from_payload(payload)
                source = str(SAMPLE_CATALOG_PATH)
            if not records:
                raise ValueError("Bundled sample catalog contains no entities")
        self.replace(records)
        self.source = source

        # Startup summary so it is immediately obvious which catalog loaded.
        counts = {"university": 0, "course": 0, "specialization": 0}
        for meta in self._metadata.values():
            counts[meta.page_type] = counts.get(meta.page_type, 0) + 1
        logger.info(
            "catalog loaded: source=%s entities=%d universities=%d courses=%d specializations=%d",
            source,
            len(self._metadata),
            counts["university"],
            counts["course"],
            counts["specialization"],
        )
        return self

    @classmethod
    async def create(cls, **kwargs: Any) -> CatalogStore:
        store = cls(**kwargs)
        return await store.load()

    def replace(self, records: Iterable[Mapping[str, Any]]) -> None:
        entities: dict[str, CatalogEntity] = {}
        metadata: dict[str, EntityMetadata] = {}
        slug_to_id: dict[str, str] = {}
        invalid = 0
        for raw_record in records:
            if not _is_published(raw_record):
                continue
            record = _unwrap_record(raw_record)
            try:
                entity = parse_entity(record)
                item = self._build_metadata(entity)
            except Exception as error:
                invalid += 1
                logger.warning("Skipping invalid catalog entity: %s", error)
                continue
            if item.id in entities:
                logger.warning("Duplicate catalog id %s; last record wins", item.id)
            entities[item.id] = entity
            metadata[item.id] = item
            slug_to_id[item.slug.lower()] = item.id

        if not entities:
            raise ValueError("No valid catalog entities were loaded")
        self._entities = entities
        self._metadata = metadata
        self._slug_to_id = slug_to_id
        if invalid:
            logger.warning("Catalog loaded with %d invalid record(s) skipped", invalid)

    @staticmethod
    def _build_metadata(entity: CatalogEntity) -> EntityMetadata:
        page_type = entity.meta.page_type
        if isinstance(entity, University):
            canonical_name = entity.university_full_name or entity.university_name or "University"
            university_name = entity.university_name or entity.university_full_name
            program_name = None
            spec_name = None
            category = None
            specialization_name = None
        elif isinstance(entity, Course):
            canonical_name = entity.program_name or "Course"
            university_name = entity.university_name
            program_name = entity.program_name
            spec_name = None
            category = _extract_category(entity.program_name, entity.category)
            specialization_name = None
        elif isinstance(entity, Specialization):
            spec_name = entity.specialization_name or entity.spec_name
            canonical_name = spec_name or "Specialization"
            university_name = entity.university_name
            program_name = entity.program_name or entity.parent_course
            # Publisher specialization pages do not always carry an explicit category or
            # linked course. Their document title commonly retains the program family
            # (for example "Online MBA Banking Specialization Page"), which is safe
            # deterministic metadata for taxonomy joining.
            # A specialization name is not itself a course category. Derive a
            # missing category only from publisher document context (or an
            # explicit field), never from labels such as "Banking & Insurance".
            category = _extract_category(
                program_name or entity.meta.document_title,
                entity.category,
            )
            specialization_name = spec_name
        else:  # pragma: no cover - the discriminated union makes this unreachable
            raise TypeError(f"Unsupported catalog entity: {type(entity)!r}")

        identity_basis = "-".join(
            value
            for value in (university_name, category, specialization_name, canonical_name)
            if value
        )
        slug = entity.slug or _slugify(identity_basis)
        entity_id = entity.id or slug
        aliases = tuple(dict.fromkeys(entity.aliases or []))
        return EntityMetadata(
            id=entity_id,
            slug=slug,
            page_type=page_type,
            canonical_name=canonical_name,
            university_name=university_name,
            program_name=program_name,
            spec_name=spec_name,
            category=category,
            specialization_name=specialization_name,
            aliases=aliases,
        )

    def resolve_id(self, identifier: str) -> str | None:
        if identifier in self._entities:
            return identifier
        return self._slug_to_id.get(identifier.lower())

    def get_entity(
        self,
        identifier: str,
        *,
        session_id: str | None = None,
    ) -> CatalogEntity | None:
        entity_id = self.resolve_id(identifier)
        if entity_id is None:
            return None
        # The full immutable catalog is already process-cached. Per-session snapshots live
        # in ConversationState.entity_cache, avoiding an unbounded process-global session map.
        del session_id
        return self._entities.get(entity_id)

    get = get_entity

    def get_metadata(self, identifier: str) -> EntityMetadata | None:
        entity_id = self.resolve_id(identifier)
        return self._metadata.get(entity_id) if entity_id else None

    def list_entities(self, page_type: PageType | None = None) -> list[CatalogEntity]:
        if page_type is None:
            return list(self._entities.values())
        return [
            entity
            for entity_id, entity in self._entities.items()
            if self._metadata[entity_id].page_type == page_type
        ]

    def list_metadata(
        self,
        page_type: PageType | None = None,
        *,
        category: str | None = None,
    ) -> list[EntityMetadata]:
        normalized_category = category.lower() if category else None
        return [
            item
            for item in self._metadata.values()
            if (page_type is None or item.page_type == page_type)
            and (normalized_category is None or item.category == normalized_category)
        ]

    def cache_in_state(self, identifier: str, state: Any) -> CatalogEntity | None:
        """Retrieve an entity and save its full envelope on a ConversationState-like object."""

        entity = self.get_entity(identifier, session_id=getattr(state, "session_id", None))
        if entity is None:
            return None
        item = self.get_metadata(identifier)
        cache = getattr(state, "entity_cache", None)
        if item is not None and isinstance(cache, dict) and item.id not in cache:
            cache[item.id] = entity.model_dump(by_alias=True)
        return entity

    def clear_session_cache(self, session_id: str) -> None:
        del session_id

    async def health(self) -> bool:
        """Return whether at least one validated catalog entity is available."""

        return bool(self._entities)


DataStore = CatalogStore
