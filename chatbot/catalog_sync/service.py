"""Validated, staged WordPress webhook ingestion for Catalog V3.

This module owns transport-facing payload handling.  It deliberately does not
participate in conversation resolution or guided flows: once committed, the
existing CatalogStore consumers see the new immutable snapshot.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from data.loader import CatalogStore
from data.models import parse_entity

LOGGER = logging.getLogger(__name__)

_POST_TYPES = {
    "university": "university",
    "universities": "university",
    "course": "course",
    "courses": "course",
    "program": "course",
    "specialization": "specialization",
    "specialisation": "specialization",
    "specializations": "specialization",
}
_UNPUBLISHED = {"trash", "draft", "pending"}
_PUBLISHED = "publish"


class CatalogSyncValidationError(ValueError):
    """The webhook cannot safely be staged as a Catalog V3 entity."""


class SyncPayload(BaseModel):
    """The intentionally small WordPress webhook envelope."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    post_id: str | int
    post_type: str = Field(min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=32)
    slug: str = Field(min_length=1, max_length=240)
    modified: str = Field(min_length=1, max_length=80)
    acf: dict[str, Any]

    @field_validator("post_id")
    @classmethod
    def validate_post_id(cls, value: str | int) -> str | int:
        if isinstance(value, str) and not value.strip():
            raise ValueError("post_id must not be blank")
        return value

    @field_validator("status", "post_type")
    @classmethod
    def normalize_words(cls, value: str) -> str:
        return value.casefold().strip()

    @field_validator("modified")
    @classmethod
    def validate_modified(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("modified must be an ISO-8601 timestamp") from exc
        return value


@dataclass(frozen=True)
class SyncResult:
    action: str
    post_id: str
    entity_id: str | None
    changed: bool
    catalog_version: int
    last_updated: str | None
    unresolved_relationships: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "action": self.action,
            "post_id": self.post_id,
            "entity_id": self.entity_id,
            "changed": self.changed,
            "catalog_version": self.catalog_version,
            "last_updated": self.last_updated,
            "unresolved_relationships": list(self.unresolved_relationships),
        }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _pick(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _list(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = _text(value)
    if not text:
        return None
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(lakh|lac|l\b)?", text.casefold())
    if not match:
        return None
    numeric = float(match.group(1).replace(",", ""))
    if match.group(2):
        numeric *= 100_000
    return int(numeric) if numeric.is_integer() else numeric


def _money(value: Any) -> tuple[str | None, int | float | None]:
    text = _text(value)
    numeric = _number(value)
    if numeric is None:
        LOGGER.warning(
            "catalog sync could not parse monetary value %r; retaining published text", text
        )
        return text, None
    if isinstance(numeric, float) and not numeric.is_integer():
        formatted = f"{numeric:,.2f}".rstrip("0").rstrip(".")
    else:
        formatted = f"{int(numeric):,}"
    return f"INR {formatted}", numeric


def _monthly_amount(value: Any) -> tuple[str | None, int | float | None]:
    amount, numeric = _money(value)
    if numeric is None:
        return amount, None
    return f"From {amount} per month", numeric


def _duration(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*(year|years|yr|yrs|month|months|mo|mos)\.?\s*", text, re.I)
    if not match:
        return text
    amount = int(match.group(1))
    unit = match.group(2).casefold()
    is_year = unit.startswith("y")
    return f"{amount} {'Year' if is_year else 'Month'}{'s' if amount != 1 else ''}"


def _naac(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    return re.sub(r"^naac\s*", "", text, flags=re.I).upper()


def _mode(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.casefold()
    if normalized in {"online", "online learning"}:
        return "Online"
    if normalized in {"distance", "distance learning"}:
        return "Distance"
    if normalized in {"hybrid", "blended"}:
        return "Hybrid"
    return text


def _refs(value: Any) -> list[str]:
    """Extract WordPress relationship references from IDs, slugs, or ACF objects."""

    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_refs(item))
        return result
    if isinstance(value, dict):
        for key in ("ID", "id", "post_id", "slug", "post_name"):
            if value.get(key) not in (None, ""):
                return _refs(value[key])
        return []
    reference = _text(value)
    return [reference] if reference else []


def _normalise_fee_plans(value: Any) -> list[dict[str, Any]] | None:
    rows = _list(value)
    if not rows:
        return None
    plans: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_amount = _pick(row, "plan_amount", "amount", "fee", "value")
        plan_name = _text(_pick(row, "plan_name", "name", "title"))
        amount, _ = (
            _monthly_amount(raw_amount)
            if re.search(r"(?:emi|monthly|installment|finance)", plan_name or "", re.I)
            else _money(raw_amount)
        )
        total, _ = _money(_pick(row, "plan_total", "total"))
        plans.append(
            {
                "plan_name": plan_name,
                "plan_amount": amount,
                "plan_total": total,
                "plan_note": _text(_pick(row, "plan_note", "note", "description")),
            }
        )
    return plans or None


def _normalise_job_profiles(value: Any) -> list[dict[str, Any]] | None:
    rows = _list(value)
    if not rows:
        return None
    profiles: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        salary, numeric = _money(_pick(row, "avg_salary", "salary", "value"))
        profiles.append(
            {
                "job_title": _text(_pick(row, "job_title", "title", "name")),
                "avg_salary": salary,
                "salary_numeric": numeric,
            }
        )
    return profiles or None


class CatalogSyncService:
    """Stage, normalize, resolve, and atomically commit WordPress updates."""

    def __init__(
        self,
        catalog: CatalogStore,
        *,
        secret: str | None,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self.catalog = catalog
        self.secret = secret
        self._lock = lock or asyncio.Lock()

    def authorize(self, supplied_secret: str | None) -> None:
        if not self.secret:
            raise PermissionError("Catalog webhook is not configured")
        if not supplied_secret or not hmac.compare_digest(supplied_secret, self.secret):
            raise PermissionError("Invalid webhook secret")

    async def sync(self, payload: SyncPayload) -> SyncResult:
        page_type = _POST_TYPES.get(payload.post_type)
        if page_type is None:
            raise CatalogSyncValidationError(f"Unsupported post_type: {payload.post_type}")
        if payload.status not in {_PUBLISHED, *_UNPUBLISHED}:
            raise CatalogSyncValidationError(f"Unsupported post status: {payload.status}")

        post_id = str(payload.post_id)
        async with self._lock:
            records = self.catalog.export_records()
            key = self._post_key(page_type, post_id)
            current_index = next(
                (
                    index
                    for index, record in enumerate(records)
                    if record.get("wordpress_post_key") == key
                ),
                None,
            )

            if payload.status in _UNPUBLISHED:
                if current_index is None:
                    return self._result("deleted", post_id, None, False, ())
                removed = records.pop(current_index)
                records = self._resolve_relationships(records)
                self.catalog.replace(records, last_updated=payload.modified, allow_empty=True)
                entity_id = _text(removed.get("id"))
                self._log(payload, "deleted", entity_id, True, ())
                return self._result("deleted", post_id, entity_id, True, ())

            staged = self._normalise(payload, page_type)
            try:
                parse_entity(staged)
            except Exception as exc:
                raise CatalogSyncValidationError(f"Normalized entity is invalid: {exc}") from exc

            if current_index is None:
                records.append(staged)
                action = "created"
            else:
                records[current_index] = staged
                action = "updated"
            resolved = self._resolve_relationships(records)
            staged_after_resolution = next(
                record for record in resolved if record.get("wordpress_post_key") == key
            )
            unresolved = tuple(
                sorted((staged_after_resolution.get("unresolved_relationships") or {}).keys())
            )

            before = self.catalog.export_records()
            if self._canonical_json(before) == self._canonical_json(resolved):
                return self._result(
                    "unchanged", post_id, str(staged_after_resolution["id"]), False, unresolved
                )
            self.catalog.replace(resolved, last_updated=payload.modified)
            self._log(payload, action, str(staged_after_resolution["id"]), True, unresolved)
            return self._result(
                action, post_id, str(staged_after_resolution["id"]), True, unresolved
            )

    def _normalise(self, payload: SyncPayload, page_type: str) -> dict[str, Any]:
        acf = dict(payload.acf)
        name = _text(
            _pick(
                acf,
                "university_full_name" if page_type == "university" else "program_name",
                "university_name" if page_type == "university" else "name",
                "specialization_name",
                "spec_name",
                "title",
            )
        )
        if page_type == "specialization":
            name = _text(_pick(acf, "specialization_name", "spec_name", "name", "title"))
        if not name:
            raise CatalogSyncValidationError(
                f"Published {page_type} requires a display name in acf"
            )

        record: dict[str, Any] = dict(acf)
        record.update(
            {
                "_meta": {
                    "page_type": page_type,
                    "document_title": _text(_pick(acf, "document_title", "seo_title", "title")),
                },
                "id": self._entity_id(page_type, str(payload.post_id)),
                "slug": payload.slug,
                "wordpress_post_key": self._post_key(page_type, str(payload.post_id)),
                "wordpress_post_id": str(payload.post_id),
                "wordpress_post_type": payload.post_type,
                "wordpress_modified": payload.modified,
            }
        )
        aliases = _list(_pick(acf, "aliases", "search_keywords"))
        if aliases:
            record["aliases"] = [str(value) for value in aliases if _text(value)]

        for source, target, numeric_target in (
            ("total_fee", "total_fee", "total_fee_numeric"),
            ("starting_fee", "starting_fee", "starting_fee_numeric"),
            ("fee", "total_fee", "total_fee_numeric"),
        ):
            value = _pick(acf, source)
            if value is not None:
                normalized, numeric = _money(value)
                record[target] = normalized
                if numeric is not None:
                    record[numeric_target] = numeric
        for source in ("emi_amount", "emi"):
            value = _pick(acf, source)
            if value is not None:
                record["emi_amount"], record["emi_numeric"] = _monthly_amount(value)
        record["duration"] = _duration(_pick(acf, "duration", "course_duration"))
        record["mode"] = _mode(_pick(acf, "mode", "mode_of_learning", "learning_mode"))
        record["naac_grade"] = _naac(_pick(acf, "naac_grade", "naac"))
        record["fee_plans"] = _normalise_fee_plans(_pick(acf, "fee_plans", "payment_plans"))
        record["job_profiles"] = _normalise_job_profiles(
            _pick(acf, "job_profiles", "career_profiles")
        )
        record["average_rating"] = _number(_pick(acf, "average_rating", "rating"))
        review_count = _number(_pick(acf, "review_count", "reviews_count"))
        record["review_count"] = int(review_count) if review_count is not None else None

        if page_type == "university":
            record["university_full_name"] = name
            record["university_name"] = _text(_pick(acf, "university_name")) or name
            record["starting_fee"], record["starting_fee_numeric"] = _money(
                _pick(acf, "starting_fee", "fee")
            )
        elif page_type == "course":
            record["program_name"] = name
            record["university_name"] = _text(_pick(acf, "university_name", "provider_name"))
            if record.get("total_fee_numeric") is not None:
                record["fee_numeric"] = record["total_fee_numeric"]
                record["fee_metadata"] = {
                    "currency": "INR",
                    "fee_type": "total",
                    "billing_cycle": "total",
                }
        else:
            record["specialization_name"] = name
            record["spec_name"] = name
            record["program_name"] = _text(_pick(acf, "program_name", "parent_course"))
            record["parent_course"] = record["program_name"]
            record["university_name"] = _text(_pick(acf, "university_name", "provider_name"))
            if record.get("total_fee_numeric") is not None:
                record["fee_numeric"] = record["total_fee_numeric"]
                record["fee_metadata"] = {
                    "currency": "INR",
                    "fee_type": "total",
                    "billing_cycle": "total",
                }

        record["wordpress_relationships"] = {
            "university": _refs(
                _pick(acf, "linked_university", "university", "university_id", "parent_university")
            ),
            "course": _refs(_pick(acf, "linked_course", "course", "course_id", "parent_course")),
        }
        return {key: value for key, value in record.items() if value is not None}

    @classmethod
    def _resolve_relationships(cls, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_reference: dict[str, dict[str, Any]] = {}
        for record in records:
            for reference in (
                record.get("id"),
                record.get("slug"),
                record.get("wordpress_post_id"),
                record.get("wordpress_post_key"),
            ):
                if reference is not None:
                    by_reference[str(reference).casefold()] = record

        resolved: list[dict[str, Any]] = []
        for original in records:
            record = dict(original)
            relationships = dict(record.get("wordpress_relationships") or {})
            unresolved: dict[str, list[str]] = {}

            def parent(
                kind: str,
                expected_type: str,
                relationships: dict[str, Any] = relationships,
                unresolved: dict[str, list[str]] = unresolved,
            ) -> dict[str, Any] | None:
                references = [str(value) for value in relationships.get(kind, [])]
                match = next(
                    (
                        by_reference.get(reference.casefold())
                        for reference in references
                        if by_reference.get(reference.casefold(), {})
                        .get("_meta", {})
                        .get("page_type")
                        == expected_type
                    ),
                    None,
                )
                if references and match is None:
                    unresolved[kind] = references
                return match

            page_type = record.get("_meta", {}).get("page_type")
            university = (
                parent("university", "university")
                if page_type in {"course", "specialization"}
                else None
            )
            course = parent("course", "course") if page_type == "specialization" else None
            if university:
                record["linked_university"] = university["id"]
                record["university_name"] = university.get("university_name") or university.get(
                    "university_full_name"
                )
            else:
                record.pop("linked_university", None)
            if course:
                record["linked_course"] = course["id"]
                record["program_name"] = course.get("program_name") or record.get("program_name")
                record["parent_course"] = record.get("program_name")
                if not record.get("linked_university") and course.get("linked_university"):
                    record["linked_university"] = course["linked_university"]
            elif page_type == "specialization":
                record.pop("linked_course", None)
            if unresolved:
                record["unresolved_relationships"] = unresolved
            else:
                record.pop("unresolved_relationships", None)
            resolved.append(record)
        return resolved

    @staticmethod
    def _canonical_json(value: Any) -> str:
        def compact(item: Any) -> Any:
            if isinstance(item, dict):
                return {
                    str(key): compact(child) for key, child in item.items() if child is not None
                }
            if isinstance(item, list):
                return [compact(child) for child in item]
            return item

        return json.dumps(
            compact(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        )

    @staticmethod
    def _post_key(page_type: str, post_id: str) -> str:
        return f"wordpress:{page_type}:{post_id}"

    @staticmethod
    def _entity_id(page_type: str, post_id: str) -> str:
        return f"wp-{page_type}-{post_id}"

    def _result(
        self,
        action: str,
        post_id: str,
        entity_id: str | None,
        changed: bool,
        unresolved: tuple[str, ...],
    ) -> SyncResult:
        return SyncResult(
            action,
            post_id,
            entity_id,
            changed,
            self.catalog.version,
            self.catalog.last_updated,
            unresolved,
        )

    @staticmethod
    def _log(
        payload: SyncPayload,
        action: str,
        entity_id: str | None,
        changed: bool,
        unresolved: tuple[str, ...],
    ) -> None:
        LOGGER.info(
            "catalog sync post_id=%s post_type=%s action=%s entity_id=%s "
            "changed=%s modified=%s unresolved=%s",
            payload.post_id,
            payload.post_type,
            action,
            entity_id,
            changed,
            payload.modified,
            ",".join(unresolved) or "none",
        )


def parse_sync_payload(value: Any) -> SyncPayload:
    try:
        return SyncPayload.model_validate(value)
    except ValidationError as exc:
        raise CatalogSyncValidationError(str(exc)) from exc
