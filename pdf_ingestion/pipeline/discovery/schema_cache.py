"""Schema cache for discovered schemas.

Provides an in-memory cache (backed by dict) for discovered schemas,
keyed by SchemaFingerprint. Tenant-isolated: all queries include tenant_id filter.

The database migration defines the persistent PostgreSQL table for production use;
this implementation uses an in-memory store for development and testing.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import structlog

from pipeline.models import (
    DiscoveredFieldDefinition,
    DiscoveredSchema,
    DiscoveredTableDefinition,
    SchemaFingerprint,
)

logger = structlog.get_logger()


class SchemaCache:
    """In-memory cache for discovered schemas.

    Design decisions:
    - Tenant-isolated: all queries include tenant_id filter
    - Keyed by SchemaFingerprint (institution + document_type_label)
    - Tracks created_at and usage_count for observability
    - Supports invalidation via DELETE endpoint
    - Uses in-memory dict (production would use PostgreSQL)
    """

    def __init__(self) -> None:
        # Internal store: {(tenant_id, fingerprint_key): entry_dict}
        self._store: dict[tuple[str, str], dict] = {}

    async def lookup(
        self,
        fingerprint: SchemaFingerprint,
        tenant_id: str,
    ) -> DiscoveredSchema | None:
        """Look up a cached schema by fingerprint.

        Returns None on cache miss. Increments usage_count on hit.
        """
        cache_key = (tenant_id, fingerprint.key)
        entry = self._store.get(cache_key)

        if entry is None:
            return None

        # Increment usage count
        entry["usage_count"] += 1
        entry["updated_at"] = datetime.now(timezone.utc)

        logger.info(
            "schema_cache.hit",
            tenant_id=tenant_id,
            fingerprint=fingerprint.key,
            usage_count=entry["usage_count"],
        )

        return self._deserialize_schema(entry["schema_json"])

    async def store(
        self,
        schema: DiscoveredSchema,
        fingerprint: SchemaFingerprint,
        tenant_id: str,
        needs_refinement: bool = False,
    ) -> None:
        """Store a discovered schema in the cache.

        Sets created_at to now, usage_count to 1.
        Overwrites if fingerprint already exists for this tenant.

        Args:
            schema: The discovered schema to cache.
            fingerprint: Schema fingerprint for cache key.
            tenant_id: Tenant isolation key.
            needs_refinement: If True, flags the schema for review due to
                high abstention rate (>50% of fields abstained).
        """
        cache_key = (tenant_id, fingerprint.key)
        now = datetime.now(timezone.utc)

        self._store[cache_key] = {
            "tenant_id": tenant_id,
            "fingerprint_key": fingerprint.key,
            "institution": schema.institution,
            "document_type_label": schema.document_type_label,
            "schema_json": self._serialize_schema(schema),
            "created_at": now,
            "updated_at": now,
            "usage_count": 1,
            "needs_refinement": needs_refinement,
        }

        logger.info(
            "schema_cache.stored",
            tenant_id=tenant_id,
            fingerprint=fingerprint.key,
            institution=schema.institution,
            document_type_label=schema.document_type_label,
            needs_refinement=needs_refinement,
        )

    async def invalidate(
        self,
        fingerprint: SchemaFingerprint,
        tenant_id: str,
    ) -> bool:
        """Remove a cached schema. Returns True if entry existed."""
        cache_key = (tenant_id, fingerprint.key)
        existed = cache_key in self._store

        if existed:
            del self._store[cache_key]
            logger.info(
                "schema_cache.invalidated",
                tenant_id=tenant_id,
                fingerprint=fingerprint.key,
            )

        return existed

    async def list_for_tenant(self, tenant_id: str) -> list[dict]:
        """List all cached schemas for a tenant (admin/debug use)."""
        results = []
        for (tid, _), entry in self._store.items():
            if tid == tenant_id:
                results.append({
                    "fingerprint_key": entry["fingerprint_key"],
                    "institution": entry["institution"],
                    "document_type_label": entry["document_type_label"],
                    "created_at": entry["created_at"].isoformat(),
                    "updated_at": entry["updated_at"].isoformat(),
                    "usage_count": entry["usage_count"],
                    "needs_refinement": entry.get("needs_refinement", False),
                })
        return results

    async def mark_needs_refinement(
        self,
        fingerprint: SchemaFingerprint,
        tenant_id: str,
    ) -> bool:
        """Flag a cached schema as needing refinement.

        Called when extraction produces >50% abstentions, indicating
        the discovered schema may not match the document well.

        Returns True if the entry was found and updated.
        """
        cache_key = (tenant_id, fingerprint.key)
        entry = self._store.get(cache_key)

        if entry is None:
            return False

        entry["needs_refinement"] = True
        entry["updated_at"] = datetime.now(timezone.utc)

        logger.warning(
            "schema_cache.marked_for_refinement",
            tenant_id=tenant_id,
            fingerprint=fingerprint.key,
            institution=entry["institution"],
            document_type_label=entry["document_type_label"],
        )

        return True

    @staticmethod
    def _serialize_schema(schema: DiscoveredSchema) -> dict:
        """Serialize a DiscoveredSchema to a JSON-compatible dict."""
        return {
            "document_type_label": schema.document_type_label,
            "institution": schema.institution,
            "metadata_fields": [
                {
                    "field_name": f.field_name,
                    "description": f.description,
                    "location_hint": f.location_hint,
                }
                for f in schema.metadata_fields
            ],
            "table_definitions": [
                {
                    "table_type": t.table_type,
                    "expected_headers": t.expected_headers,
                    "data_pattern": t.data_pattern,
                    "location_hint": t.location_hint,
                }
                for t in schema.table_definitions
            ],
        }

    @staticmethod
    def _deserialize_schema(data: dict) -> DiscoveredSchema:
        """Deserialize a dict back into a DiscoveredSchema."""
        metadata_fields = [
            DiscoveredFieldDefinition(
                field_name=f["field_name"],
                description=f["description"],
                location_hint=f["location_hint"],
            )
            for f in data.get("metadata_fields", [])
        ]

        table_definitions = [
            DiscoveredTableDefinition(
                table_type=t["table_type"],
                expected_headers=t.get("expected_headers", []),
                data_pattern=t.get("data_pattern", ""),
                location_hint=t.get("location_hint", ""),
            )
            for t in data.get("table_definitions", [])
        ]

        return DiscoveredSchema(
            document_type_label=data["document_type_label"],
            institution=data["institution"],
            metadata_fields=metadata_fields,
            table_definitions=table_definitions,
        )
