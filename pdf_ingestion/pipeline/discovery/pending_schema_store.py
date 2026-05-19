"""Pending schema store for user-approval gating.

Discovered schemas from LLM extraction enter a "pending" state here and are
only moved to the approved SchemaCache when the user explicitly accepts them.
Pending entries expire automatically after 24 hours.

Design decisions:
- Separate from SchemaCache so lookup() never needs to filter by approval status.
- Lazy expiry: get_pending() checks created_at and returns None for stale entries
  without deleting them. expire_stale() performs the actual cleanup sweep.
- Tenant-isolated: all queries include tenant_id to prevent cross-tenant leakage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog

from pipeline.models import DiscoveredSchema, SchemaFingerprint

logger = structlog.get_logger()

_EXPIRY_HOURS = 24


@dataclass
class PendingEntry:
    """A schema awaiting user approval.

    Attributes:
        pending_id: UUID4 string identifying this pending entry.
        schema: The discovered schema produced by LLM extraction.
        fingerprint: Schema fingerprint for eventual SchemaCache storage.
        tenant_id: Tenant that owns this entry.
        job_id: Job that produced this schema.
        created_at: UTC timestamp of creation; used for expiry checks.
    """

    pending_id: str
    schema: DiscoveredSchema
    fingerprint: SchemaFingerprint
    tenant_id: str
    job_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PendingSchemaStore:
    """In-memory store for pending (unapproved) discovered schemas.

    Pending entries are never returned by SchemaCache.lookup() — they live
    here until the user approves them (moving them to SchemaCache) or they
    expire after 24 hours.

    Thread-safety: this implementation is not thread-safe. For production use
    with concurrent workers, wrap mutations in a lock or use a persistent store.
    """

    def __init__(self) -> None:
        # Internal store: {pending_id: PendingEntry}
        self._store: dict[str, PendingEntry] = {}

    def store_pending(
        self,
        schema: DiscoveredSchema,
        fingerprint: SchemaFingerprint,
        tenant_id: str,
        job_id: str,
    ) -> str:
        """Store a schema in pending state.

        Args:
            schema: The discovered schema to hold pending approval.
            fingerprint: Schema fingerprint for eventual cache storage.
            tenant_id: Tenant isolation key.
            job_id: Job that produced this schema.

        Returns:
            A UUID4 string identifying this pending entry (pending_id).
        """
        pending_id = str(uuid.uuid4())
        entry = PendingEntry(
            pending_id=pending_id,
            schema=schema,
            fingerprint=fingerprint,
            tenant_id=tenant_id,
            job_id=job_id,
        )
        self._store[pending_id] = entry

        logger.info(
            "pending_schema_store.stored",
            pending_id=pending_id,
            tenant_id=tenant_id,
            job_id=job_id,
            fingerprint=fingerprint.key,
        )

        return pending_id

    def get_pending(self, pending_id: str, tenant_id: str) -> PendingEntry | None:
        """Retrieve a pending entry by ID.

        Performs a lazy expiry check: returns None if the entry is older than
        24 hours, without deleting it (call expire_stale() for cleanup).

        Args:
            pending_id: The UUID returned by store_pending().
            tenant_id: Must match the tenant that created the entry.

        Returns:
            The PendingEntry, or None if not found, expired, or wrong tenant.
        """
        entry = self._store.get(pending_id)

        if entry is None:
            return None

        # Tenant isolation check
        if entry.tenant_id != tenant_id:
            return None

        # Lazy expiry check
        age = datetime.now(timezone.utc) - entry.created_at
        if age >= timedelta(hours=_EXPIRY_HOURS):
            logger.info(
                "pending_schema_store.expired_on_read",
                pending_id=pending_id,
                tenant_id=tenant_id,
                age_hours=round(age.total_seconds() / 3600, 2),
            )
            return None

        return entry

    def discard(self, pending_id: str, tenant_id: str) -> bool:
        """Delete a pending entry.

        Args:
            pending_id: The UUID of the entry to remove.
            tenant_id: Must match the tenant that created the entry.

        Returns:
            True if the entry existed and was removed, False otherwise.
        """
        entry = self._store.get(pending_id)

        if entry is None or entry.tenant_id != tenant_id:
            return False

        del self._store[pending_id]

        logger.info(
            "schema_cache.pending_discarded",
            pending_id=pending_id,
            tenant_id=tenant_id,
        )

        return True

    def expire_stale(self) -> int:
        """Remove all entries older than 24 hours.

        Intended to be called periodically (e.g., from the lifespan hook)
        to prevent unbounded memory growth.

        Returns:
            The number of entries removed.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=_EXPIRY_HOURS)

        stale_ids = [
            pending_id
            for pending_id, entry in self._store.items()
            if entry.created_at < cutoff
        ]

        for pending_id in stale_ids:
            del self._store[pending_id]

        if stale_ids:
            logger.info(
                "pending_schema_store.expired_stale",
                count=len(stale_ids),
            )

        return len(stale_ids)
