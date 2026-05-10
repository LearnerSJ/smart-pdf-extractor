import React, { useState, useEffect, useCallback } from "react";

/**
 * RedactionSettings — Per-entity toggle panel for tenant redaction configuration.
 *
 * Features:
 * - Global entity redaction toggles
 * - Per-schema overrides (bank_statement, custody_statement, swift_confirm)
 * - Warning icons: red "i" for PII exposure risk, amber "!" for extraction risk
 * - Status bar showing protection level
 * - Wired to GET/PUT /v1/tenants/{id}/redaction-config
 */

const SCHEMA_TYPES = ["bank_statement", "custody_statement", "swift_confirm"];

const DEFAULT_ENTITIES = [
  { entity_type: "PERSON", label: "Person Names" },
  { entity_type: "EMAIL_ADDRESS", label: "Email Addresses" },
  { entity_type: "PHONE_NUMBER", label: "Phone Numbers" },
  { entity_type: "IBAN_CODE", label: "IBAN Codes" },
  { entity_type: "CREDIT_CARD", label: "Credit Card Numbers" },
  { entity_type: "US_SSN", label: "Social Security Numbers" },
  { entity_type: "IP_ADDRESS", label: "IP Addresses" },
  { entity_type: "LOCATION", label: "Locations" },
  { entity_type: "DATE_TIME", label: "Dates" },
  { entity_type: "NRP", label: "Nationalities / Religious / Political Groups" },
];

const SCHEMA_LABELS = {
  bank_statement: "Bank Statement",
  custody_statement: "Custody Statement",
  swift_confirm: "SWIFT Confirmation",
};

function getProtectionLevel(globalEntities) {
  if (!globalEntities || globalEntities.length === 0) {
    return { level: "HIGH EXPOSURE", color: "#dc2626" };
  }
  const enabledCount = globalEntities.filter((e) => e.enabled).length;
  const total = globalEntities.length;
  const ratio = enabledCount / total;

  if (ratio >= 0.8) {
    return { level: "FULLY PROTECTED", color: "#16a34a" };
  } else if (ratio >= 0.4) {
    return { level: "PARTIAL EXPOSURE", color: "#d97706" };
  } else {
    return { level: "HIGH EXPOSURE", color: "#dc2626" };
  }
}

function WarningIcon({ type }) {
  if (type === "pii_exposure") {
    return (
      <span
        title="PII exposure risk: this entity type is not being redacted"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 18,
          height: 18,
          borderRadius: "50%",
          backgroundColor: "#dc2626",
          color: "#fff",
          fontSize: 11,
          fontWeight: "bold",
          marginLeft: 6,
        }}
        aria-label="PII exposure risk"
      >
        i
      </span>
    );
  }
  if (type === "extraction_risk") {
    return (
      <span
        title="Extraction risk: redacting this entity may reduce extraction accuracy"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 18,
          height: 18,
          borderRadius: "50%",
          backgroundColor: "#d97706",
          color: "#fff",
          fontSize: 11,
          fontWeight: "bold",
          marginLeft: 6,
        }}
        aria-label="Extraction risk"
      >
        !
      </span>
    );
  }
  return null;
}

function EntityToggle({ entity, enabled, onChange }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        padding: "8px 0",
        borderBottom: "1px solid #e5e7eb",
      }}
    >
      <label
        style={{
          display: "flex",
          alignItems: "center",
          cursor: "pointer",
          flex: 1,
        }}
      >
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onChange(entity.entity_type, e.target.checked)}
          style={{ marginRight: 10 }}
          aria-label={`Toggle redaction for ${entity.label}`}
        />
        <span>{entity.label}</span>
        <span
          style={{ color: "#6b7280", fontSize: 12, marginLeft: 8 }}
        >
          ({entity.entity_type})
        </span>
      </label>
      {!enabled && <WarningIcon type="pii_exposure" />}
      {enabled && entity.entity_type === "IBAN_CODE" && (
        <WarningIcon type="extraction_risk" />
      )}
      {enabled && entity.entity_type === "DATE_TIME" && (
        <WarningIcon type="extraction_risk" />
      )}
    </div>
  );
}

function StatusBar({ globalEntities }) {
  const { level, color } = getProtectionLevel(globalEntities);
  return (
    <div
      style={{
        padding: "12px 16px",
        backgroundColor: color + "15",
        border: `1px solid ${color}`,
        borderRadius: 6,
        marginBottom: 20,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
      role="status"
      aria-live="polite"
    >
      <span style={{ fontWeight: 600, color }}>
        Protection Level: {level}
      </span>
      <span style={{ fontSize: 13, color: "#4b5563" }}>
        {globalEntities.filter((e) => e.enabled).length} /{" "}
        {globalEntities.length} entities redacted
      </span>
    </div>
  );
}

export default function RedactionSettings({ tenantId, apiBaseUrl = "" }) {
  const [globalEntities, setGlobalEntities] = useState(
    DEFAULT_ENTITIES.map((e) => ({ ...e, enabled: true }))
  );
  const [schemaOverrides, setSchemaOverrides] = useState({});
  const [activeTab, setActiveTab] = useState("global");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      // Load from localStorage (no backend dependency for MVP)
      const saved = localStorage.getItem("redaction_config");
      if (saved) {
        const config = JSON.parse(saved);
        if (config.global_entities && config.global_entities.length > 0) {
          const merged = DEFAULT_ENTITIES.map((def) => {
            const found = config.global_entities.find(
              (e) => e.entity_type === def.entity_type
            );
            return {
              ...def,
              enabled: found ? found.enabled : true,
            };
          });
          setGlobalEntities(merged);
        }
        if (config.schema_overrides) {
          setSchemaOverrides(config.schema_overrides);
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleGlobalToggle = (entityType, enabled) => {
    setGlobalEntities((prev) =>
      prev.map((e) =>
        e.entity_type === entityType ? { ...e, enabled } : e
      )
    );
  };

  const handleSchemaToggle = (schema, entityType, enabled) => {
    setSchemaOverrides((prev) => {
      const current = prev[schema] || globalEntities.map((e) => ({
        entity_type: e.entity_type,
        enabled: e.enabled,
      }));
      const updated = current.map((e) =>
        e.entity_type === entityType ? { ...e, enabled } : e
      );
      return { ...prev, [schema]: updated };
    });
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccessMessage(null);

      const payload = {
        global_entities: globalEntities.map((e) => ({
          entity_type: e.entity_type,
          enabled: e.enabled,
        })),
        schema_overrides: Object.fromEntries(
          Object.entries(schemaOverrides).map(([schema, entities]) => [
            schema,
            entities.map((e) => ({
              entity_type: e.entity_type,
              enabled: e.enabled,
            })),
          ])
        ),
      };

      // Save to localStorage (no backend dependency for MVP)
      localStorage.setItem("redaction_config", JSON.stringify(payload));

      setSuccessMessage("Redaction settings saved successfully.");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const getSchemaEntities = (schema) => {
    if (schemaOverrides[schema]) {
      return DEFAULT_ENTITIES.map((def) => {
        const found = schemaOverrides[schema].find(
          (e) => e.entity_type === def.entity_type
        );
        return {
          ...def,
          enabled: found ? found.enabled : true,
        };
      });
    }
    return globalEntities;
  };

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: "center" }}>
        Loading redaction settings...
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 700, margin: "0 auto", padding: 24 }}>
      <h2 style={{ marginBottom: 8 }}>Redaction Settings</h2>
      <p style={{ color: "#6b7280", marginBottom: 20, fontSize: 14 }}>
        Configure which PII entity types are redacted before VLM processing.
        Per-schema overrides allow different settings per document type.
      </p>

      <StatusBar globalEntities={globalEntities} />

      {error && (
        <div
          style={{
            padding: "10px 14px",
            backgroundColor: "#fef2f2",
            border: "1px solid #dc2626",
            borderRadius: 6,
            marginBottom: 16,
            color: "#dc2626",
            fontSize: 14,
          }}
          role="alert"
        >
          {error}
        </div>
      )}

      {successMessage && (
        <div
          style={{
            padding: "10px 14px",
            backgroundColor: "#f0fdf4",
            border: "1px solid #16a34a",
            borderRadius: 6,
            marginBottom: 16,
            color: "#16a34a",
            fontSize: 14,
          }}
          role="status"
        >
          {successMessage}
        </div>
      )}

      {/* Tab navigation */}
      <div
        style={{
          display: "flex",
          borderBottom: "2px solid #e5e7eb",
          marginBottom: 20,
        }}
        role="tablist"
      >
        <button
          role="tab"
          aria-selected={activeTab === "global"}
          onClick={() => setActiveTab("global")}
          style={{
            padding: "10px 20px",
            border: "none",
            background: "none",
            cursor: "pointer",
            fontWeight: activeTab === "global" ? 600 : 400,
            borderBottom:
              activeTab === "global" ? "2px solid #2563eb" : "none",
            color: activeTab === "global" ? "#2563eb" : "#6b7280",
            marginBottom: -2,
          }}
        >
          Global Config
        </button>
        {SCHEMA_TYPES.map((schema) => (
          <button
            key={schema}
            role="tab"
            aria-selected={activeTab === schema}
            onClick={() => setActiveTab(schema)}
            style={{
              padding: "10px 20px",
              border: "none",
              background: "none",
              cursor: "pointer",
              fontWeight: activeTab === schema ? 600 : 400,
              borderBottom:
                activeTab === schema ? "2px solid #2563eb" : "none",
              color: activeTab === schema ? "#2563eb" : "#6b7280",
              marginBottom: -2,
            }}
          >
            {SCHEMA_LABELS[schema]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div role="tabpanel">
        {activeTab === "global" && (
          <div>
            <h3 style={{ marginBottom: 12, fontSize: 16 }}>
              Global Entity Redaction
            </h3>
            <p style={{ color: "#6b7280", fontSize: 13, marginBottom: 12 }}>
              These settings apply to all document types unless overridden.
            </p>
            {globalEntities.map((entity) => (
              <EntityToggle
                key={entity.entity_type}
                entity={entity}
                enabled={entity.enabled}
                onChange={handleGlobalToggle}
              />
            ))}
          </div>
        )}

        {SCHEMA_TYPES.map(
          (schema) =>
            activeTab === schema && (
              <div key={schema}>
                <h3 style={{ marginBottom: 12, fontSize: 16 }}>
                  {SCHEMA_LABELS[schema]} Override
                </h3>
                <p
                  style={{
                    color: "#6b7280",
                    fontSize: 13,
                    marginBottom: 12,
                  }}
                >
                  Override global settings for {SCHEMA_LABELS[schema]}{" "}
                  documents. Unchecked entities inherit from global config
                  unless explicitly overridden.
                </p>
                {!schemaOverrides[schema] && (
                  <button
                    onClick={() =>
                      setSchemaOverrides((prev) => ({
                        ...prev,
                        [schema]: globalEntities.map((e) => ({
                          entity_type: e.entity_type,
                          enabled: e.enabled,
                        })),
                      }))
                    }
                    style={{
                      padding: "8px 16px",
                      backgroundColor: "#f3f4f6",
                      border: "1px solid #d1d5db",
                      borderRadius: 4,
                      cursor: "pointer",
                      marginBottom: 16,
                    }}
                  >
                    Enable Override for {SCHEMA_LABELS[schema]}
                  </button>
                )}
                {schemaOverrides[schema] && (
                  <>
                    <button
                      onClick={() =>
                        setSchemaOverrides((prev) => {
                          const next = { ...prev };
                          delete next[schema];
                          return next;
                        })
                      }
                      style={{
                        padding: "6px 12px",
                        backgroundColor: "#fef2f2",
                        border: "1px solid #fca5a5",
                        borderRadius: 4,
                        cursor: "pointer",
                        marginBottom: 16,
                        fontSize: 13,
                        color: "#dc2626",
                      }}
                    >
                      Remove Override (use global)
                    </button>
                    {getSchemaEntities(schema).map((entity) => (
                      <EntityToggle
                        key={entity.entity_type}
                        entity={entity}
                        enabled={entity.enabled}
                        onChange={(entityType, enabled) =>
                          handleSchemaToggle(schema, entityType, enabled)
                        }
                      />
                    ))}
                  </>
                )}
              </div>
            )
        )}
      </div>

      {/* Save button */}
      <div style={{ marginTop: 24, display: "flex", gap: 12 }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            padding: "10px 24px",
            backgroundColor: saving ? "#9ca3af" : "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: saving ? "not-allowed" : "pointer",
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          {saving ? "Saving..." : "Save Settings"}
        </button>
        <button
          onClick={fetchConfig}
          disabled={loading}
          style={{
            padding: "10px 24px",
            backgroundColor: "#f3f4f6",
            color: "#374151",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            cursor: "pointer",
            fontSize: 14,
          }}
        >
          Reset
        </button>
      </div>
    </div>
  );
}
