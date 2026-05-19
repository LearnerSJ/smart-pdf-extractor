import React, { useState, useEffect, useCallback } from "react";

const API_KEY = "demo-key";

const DEFAULT_CONFIG = {
  enabled: false,
  callback_url: "",
  auth_header: "",
  retry_count: 3,
  deliver_on: "job_complete",
};

/**
 * Delivery Settings — configure webhook delivery of extraction results.
 *
 * Allows tenants to set a callback URL that receives a POST request
 * when a job (or batch) completes. Wired to GET/PUT /v1/tenants/{id}/redaction-config
 * (delivery_config field).
 */
export default function DeliverySettings() {
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [error, setError] = useState(null);

  // Load from localStorage (no DB dependency for demo)
  useEffect(() => {
    try {
      const stored = localStorage.getItem("delivery_config");
      if (stored) {
        setConfig({ ...DEFAULT_CONFIG, ...JSON.parse(stored) });
      }
    } catch {}
  }, []);

  const handleChange = (field, value) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
    setSaved(false);
    setTestResult(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      localStorage.setItem("delivery_config", JSON.stringify(config));
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!config.callback_url) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch(config.callback_url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(config.auth_header ? { Authorization: config.auth_header } : {}),
        },
        body: JSON.stringify({
          type: "test",
          message: "PDF Ingestion delivery test ping",
          timestamp: new Date().toISOString(),
        }),
      });
      setTestResult({ ok: res.ok, status: res.status });
    } catch (err) {
      setTestResult({ ok: false, error: err.message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Delivery Settings</h1>
      <p style={styles.subtitle}>
        Configure a webhook to receive extraction results automatically when jobs complete.
      </p>

      {/* Enable toggle */}
      <div style={styles.card}>
        <div style={styles.row}>
          <div>
            <div style={styles.fieldLabel}>Enable Webhook Delivery</div>
            <div style={styles.fieldHint}>
              When enabled, results are POSTed to your callback URL on job completion.
            </div>
          </div>
          <label style={styles.toggle}>
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) => handleChange("enabled", e.target.checked)}
              style={{ display: "none" }}
            />
            <div style={{
              ...styles.toggleTrack,
              backgroundColor: config.enabled ? "var(--color-success)" : "var(--color-border)",
            }}>
              <div style={{
                ...styles.toggleThumb,
                transform: config.enabled ? "translateX(20px)" : "translateX(2px)",
              }} />
            </div>
          </label>
        </div>
      </div>

      {/* Callback URL */}
      <div style={styles.card}>
        <label style={styles.fieldLabel}>Callback URL</label>
        <div style={styles.fieldHint}>
          The endpoint that will receive POST requests with extraction results.
        </div>
        <div style={styles.inputRow}>
          <input
            type="url"
            value={config.callback_url}
            onChange={(e) => handleChange("callback_url", e.target.value)}
            placeholder="https://your-app.com/webhook/pdf-results"
            style={styles.input}
            disabled={!config.enabled}
          />
          <button
            onClick={handleTest}
            disabled={!config.callback_url || !config.enabled || testing}
            style={styles.testBtn}
          >
            {testing ? "Testing..." : "Test"}
          </button>
        </div>
        {testResult && (
          <div style={{
            ...styles.testResult,
            color: testResult.ok ? "var(--color-success)" : "var(--color-error)",
            backgroundColor: testResult.ok ? "rgba(46,204,113,0.08)" : "rgba(231,76,60,0.08)",
            borderColor: testResult.ok ? "var(--color-success)" : "var(--color-error)",
          }}>
            {testResult.ok
              ? `✓ Ping succeeded (HTTP ${testResult.status})`
              : `✕ Ping failed${testResult.status ? ` (HTTP ${testResult.status})` : ""}: ${testResult.error || "Unknown error"}`}
          </div>
        )}
      </div>

      {/* Auth header */}
      <div style={styles.card}>
        <label style={styles.fieldLabel}>Authorization Header <span style={styles.optional}>(optional)</span></label>
        <div style={styles.fieldHint}>
          Sent as the <code>Authorization</code> header on every delivery request.
          Example: <code>Bearer your-secret-token</code>
        </div>
        <input
          type="password"
          value={config.auth_header}
          onChange={(e) => handleChange("auth_header", e.target.value)}
          placeholder="Bearer your-secret-token"
          style={styles.input}
          disabled={!config.enabled}
          autoComplete="off"
        />
      </div>

      {/* Delivery trigger */}
      <div style={styles.card}>
        <label style={styles.fieldLabel}>Deliver On</label>
        <div style={styles.fieldHint}>When to trigger delivery.</div>
        <select
          value={config.deliver_on}
          onChange={(e) => handleChange("deliver_on", e.target.value)}
          style={styles.select}
          disabled={!config.enabled}
        >
          <option value="job_complete">Each job completes</option>
          <option value="batch_complete">Entire batch completes</option>
        </select>
      </div>

      {/* Retry count */}
      <div style={styles.card}>
        <label style={styles.fieldLabel}>Max Retries</label>
        <div style={styles.fieldHint}>
          Number of retry attempts on delivery failure (exponential backoff).
        </div>
        <select
          value={config.retry_count}
          onChange={(e) => handleChange("retry_count", Number(e.target.value))}
          style={{ ...styles.select, maxWidth: 120 }}
          disabled={!config.enabled}
        >
          <option value={1}>1</option>
          <option value={2}>2</option>
          <option value={3}>3 (recommended)</option>
          <option value={5}>5</option>
        </select>
      </div>

      {/* Payload preview */}
      <div style={styles.card}>
        <div style={styles.fieldLabel}>Payload Format</div>
        <div style={styles.fieldHint}>
          Your endpoint will receive a POST with this JSON structure:
        </div>
        <pre style={styles.codeBlock}>{`{
  "type": "job_complete",
  "job_id": "abc-123",
  "trace_id": "uuid",
  "status": "complete",
  "result": {
    "doc_id": "sha256:...",
    "schema_type": "bank_statement",
    "fields": { ... },
    "abstentions": [ ... ],
    "validation": { "passed": true }
  }
}`}</pre>
      </div>

      {/* Error */}
      {error && <div style={styles.error}>{error}</div>}

      {/* Save */}
      <button
        onClick={handleSave}
        disabled={saving}
        style={styles.saveBtn}
      >
        {saving ? "Saving..." : saved ? "✓ Saved" : "Save Settings"}
      </button>
    </div>
  );
}

const styles = {
  page: { maxWidth: 640 },
  title: { fontSize: "var(--text-xl)", fontWeight: 700, color: "var(--color-text-primary)", marginBottom: "var(--space-1)" },
  subtitle: { fontSize: "var(--text-md)", color: "var(--color-text-secondary)", marginBottom: "var(--space-6)" },
  card: {
    backgroundColor: "#fff",
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius)",
    padding: "var(--space-4)",
    marginBottom: "var(--space-4)",
  },
  row: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  fieldLabel: { fontSize: "var(--text-md)", fontWeight: 600, color: "var(--color-text-primary)", marginBottom: "var(--space-1)" },
  fieldHint: { fontSize: "var(--text-sm)", color: "var(--color-text-muted)", marginBottom: "var(--space-3)" },
  optional: { fontWeight: 400, color: "var(--color-text-muted)", fontSize: "var(--text-sm)" },
  input: {
    width: "100%",
    padding: "var(--space-2) var(--space-3)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-md)",
    fontFamily: "inherit",
    boxSizing: "border-box",
  },
  inputRow: { display: "flex", gap: "var(--space-2)", alignItems: "center" },
  select: {
    padding: "var(--space-2) var(--space-3)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-md)",
    backgroundColor: "#fff",
    width: "100%",
  },
  testBtn: {
    padding: "var(--space-2) var(--space-4)",
    backgroundColor: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-sm)",
    fontWeight: 500,
    cursor: "pointer",
    whiteSpace: "nowrap",
    flexShrink: 0,
  },
  testResult: {
    marginTop: "var(--space-2)",
    padding: "var(--space-2) var(--space-3)",
    borderRadius: "var(--border-radius-sm)",
    border: "1px solid",
    fontSize: "var(--text-sm)",
    fontWeight: 500,
  },
  toggle: { cursor: "pointer" },
  toggleTrack: {
    width: 44,
    height: 24,
    borderRadius: 12,
    position: "relative",
    transition: "background-color 150ms ease",
    flexShrink: 0,
  },
  toggleThumb: {
    position: "absolute",
    top: 2,
    width: 20,
    height: 20,
    borderRadius: "50%",
    backgroundColor: "#fff",
    boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
    transition: "transform 150ms ease",
  },
  codeBlock: {
    backgroundColor: "var(--color-primary)",
    color: "var(--color-text-inverse)",
    padding: "var(--space-3) var(--space-4)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-sm)",
    fontFamily: "var(--font-mono)",
    overflow: "auto",
    lineHeight: 1.6,
    margin: 0,
  },
  error: {
    padding: "var(--space-2) var(--space-3)",
    backgroundColor: "rgba(231,76,60,0.08)",
    border: "1px solid var(--color-error)",
    borderRadius: "var(--border-radius-sm)",
    color: "var(--color-error)",
    fontSize: "var(--text-sm)",
    marginBottom: "var(--space-4)",
  },
  saveBtn: {
    padding: "var(--space-2) var(--space-6)",
    backgroundColor: "var(--color-info)",
    color: "#fff",
    border: "none",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-md)",
    fontWeight: 600,
    cursor: "pointer",
  },
};
