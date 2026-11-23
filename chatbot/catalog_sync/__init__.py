"""WordPress-to-Catalog V3 ingestion boundary."""

from .persistence import CatalogPersistence, CatalogStorageError
from .service import (
    CatalogSyncService,
    CatalogSyncValidationError,
    SyncPayload,
    SyncResult,
    parse_sync_payload,
)

__all__ = [
    "CatalogPersistence",
    "CatalogStorageError",
    "CatalogSyncService",
    "CatalogSyncValidationError",
    "SyncPayload",
    "SyncResult",
    "parse_sync_payload",
]
