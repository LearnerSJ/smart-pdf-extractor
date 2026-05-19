import React, { useState, useEffect, useCallback } from "react";
import { apiPost } from "../hooks/useApi";

/**
 * Banner prompting the user to accept or discard a newly discovered pending schema.
 *
 * Shown when pendingSchemaId is non-null and sessionStorage key
 * `schema_banner_acted_{jobId}` is not set.
 *
 * Escape key or Discard → treated as Discard (lets 24h TTL clean up the pending entry).
 */
export default function SchemaApprovalBanner({
  jobId,
  pendingSchemaId,
  schemaLabel,
  institution,
  fieldCount,
  tableCount,
  onApproved,
  onDiscarded,
}) {
  const sessionKey = `schema_banner_acted_${jobId}`;

  const shouldShow = pendingSchemaId != null && !sessionStorage.getItem(sessionKey);
  const [visible, setVisible] = useState(shouldShow);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    if (pendingSchemaId != null && !sessionStorage.getItem(sessionKey)) {
      setVisible(true);
    } else {
      setVisible(false);
    }
  }, [pendingSchemaId, sessionKey]);

  const handleDiscard = useCallback(() => {
    sessionStorage.setItem(sessionKey, "true");
    setVisible(false);
    onDiscarded?.();
  }, [sessionKey, onDiscarded]);

  useEffect(() => {
    if (!visible) return;
    const onKeyDown = (e) => { if (e.key === "Escape") handleDiscard(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [visible, handleDiscard]);

  const handleAccept = async () => {
    setLoading(true);
    try {
      await apiPost(`/v1/jobs/${jobId}/approve-schema`, {
        pending_schema_id: pendingSchemaId,
      });
      sessionStorage.setItem(sessionKey, "true");
      setToast({ message: "Schema saved successfully.", type: "success" });
      setTimeout(() => {
        setVisible(false);
        setToast(null);
        onApproved?.();
      }, 1500);
    } catch (err) {
      setToast({ message: err.message || "Failed to save schema.", type: "error" });
      setLoading(false);
    }
  };

  if (!visible) return null;

  return (
    <div style={styles.banner} role="region" aria-label="Schema approval">
      <div style={styles.left}>
        <span style={styles.icon} aria-hidden="true">ℹ</span>
        <div style={styles.content}>
          <span style={styles.heading}>New Schema Detected</span>
          <span style={styles.meta}>
            <strong>{schemaLabel || "Unknown schema"}</strong>
            {institution ? <> · {institution}</> : null}
            {" · "}{fieldCount ?? 0} field{fieldCount !== 1 ? "s" : ""}
            {" · "}{tableCount ?? 0} table{tableCount !== 1 ? "s" : ""}
          </span>
          {toast && (
            <span style={toast.type === "success" ? styles.toastSuccess : styles.toastError} role="status">
              {toast.message}
            </span>
          )}
        </div>
      </div>
      <div style={styles.actions}>
        <button onClick={handleAccept} disabled={loading} style={styles.acceptBtn} aria-label="Accept and save schema">
          {loading ? "Saving…" : "Accept & Save Schema"}
        </button>
        <button onClick={handleDiscard} disabled={loading} style={styles.discardBtn} aria-label="Discard schema">
          Discard
        </button>
      </div>
    </div>
  );
}

const styles = {
  banner: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--space-4)", padding: "var(--space-3) var(--space-5)", backgroundColor: "#EBF5FB", border: "1px solid #AED6F1", borderRadius: "var(--border-radius)", marginBottom: "var(--space-3)", flexWrap: "wrap" },
  left: { display: "flex", alignItems: "flex-start", gap: "var(--space-3)", flex: 1, minWidth: 0 },
  icon: { fontSize: "var(--text-lg)", color: "var(--color-info)", flexShrink: 0, lineHeight: 1.4 },
  content: { display: "flex", flexDirection: "column", gap: "2px", minWidth: 0 },
  heading: { fontSize: "var(--text-md)", fontWeight: 600, color: "#1A5276" },
  meta: { fontSize: "var(--text-sm)", color: "#2E86C1" },
  toastSuccess: { fontSize: "var(--text-sm)", color: "#1E8449", fontWeight: 500, marginTop: 2 },
  toastError: { fontSize: "var(--text-sm)", color: "var(--color-error)", fontWeight: 500, marginTop: 2 },
  actions: { display: "flex", gap: "var(--space-2)", flexShrink: 0 },
  acceptBtn: { padding: "var(--space-2) var(--space-4)", backgroundColor: "var(--color-info)", color: "#fff", fontWeight: 600, borderRadius: "var(--border-radius-sm)", border: "none", cursor: "pointer", fontSize: "var(--text-sm)" },
  discardBtn: { padding: "var(--space-2) var(--space-4)", backgroundColor: "transparent", color: "#2E86C1", fontWeight: 500, borderRadius: "var(--border-radius-sm)", border: "1px solid #AED6F1", cursor: "pointer", fontSize: "var(--text-sm)" },
};
