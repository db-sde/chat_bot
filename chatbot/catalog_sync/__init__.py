"""WordPress-to-Catalog V3 ingestion boundary."""

from .service import (
    CatalogSyncService,
    CatalogSyncValidationError,
    SyncPayload,
    SyncResult,
    parse_sync_payload,
)

__all__ = [
    "CatalogSyncService",
    "CatalogSyncValidationError",
    "SyncPayload",
    "SyncResult",
    "parse_sync_payload",
]
