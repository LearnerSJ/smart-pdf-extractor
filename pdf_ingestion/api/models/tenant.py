"""Tenant-related models."""

from __future__ import annotations

from pydantic import BaseModel


class EntityRedactionConfig(BaseModel):
    """Configuration for a single entity type to redact."""

    entity_type: str
    enabled: bool = True


class TenantRedactionSettings(BaseModel):
    """Per-tenant redaction configuration with global and per-schema overrides."""

    global_entities: list[EntityRedactionConfig] = []
    schema_overrides: dict[str, list[EntityRedactionConfig]] = {}


class DeliveryConfig(BaseModel):
    """Per-tenant delivery configuration."""

    callback_url: str | None = None
    auth_header: str | None = None
    enabled: bool = False


class TenantContext(BaseModel):
    """Resolved tenant identity bound to a request."""

    id: str
    name: str
    api_key_hash: str
    vlm_enabled: bool = False
    is_suspended: bool = False
    redaction_config: TenantRedactionSettings = TenantRedactionSettings()
    delivery_config: DeliveryConfig = DeliveryConfig()
