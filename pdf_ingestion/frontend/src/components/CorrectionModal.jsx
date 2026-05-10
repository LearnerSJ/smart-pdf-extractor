import React, { useState } from "react";
import { apiPost } from "../hooks/useApi";

/**
 * Modal for submitting inline corrections against extracted field values.
 */
export default function CorrectionModal({ open, onClose, jobId, fieldName, currentValue, onSuccess }) {
  const [correctedValue, setCorrectedValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;

  const canSubmit = correctedValue.trim().length > 0 && !submitting;

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await apiPost(`/v1/feedback/${jobId}`, {
        field_name: fieldName,
        original_value: currentValue,
        corrected_value: correctedValue.trim(),
      });
      setCorrectedValue("");
      onSuccess?.();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={styles.backdrop} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <h3 style={styles.title}>Submit Correction</h3>

        <div style={styles.field}>
          <label style={styles.label}>Field</label>
          <div style={styles.value}>{fieldName}</div>
        </div>

        <div style={styles.field}>
          <label style={styles.label}>Current Value</label>
          <div style={styles.value}>{currentValue || "—"}</div>
        </div>

        <div style={styles.field}>
          <label style={styles.label}>Corrected Value</label>
          <input
            type="text"
            value={correctedValue}
            onChange={(e) => setCorrectedValue(e.target.value)}
            placeholder="Enter correct value..."
            style={styles.input}
            autoFocus
          />
        </div>

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.actions}>
          <button onClick={onClose} style={styles.cancelBtn}>Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{ ...styles.submitBtn, opacity: canSubmit ? 1 : 0.5 }}
          >
            {submitting ? "Submitting..." : "Submit Correction"}
          </button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: "fixed",
    inset: 0,
    backgroundColor: "rgba(15, 30, 60, 0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  },
  modal: {
    backgroundColor: "#fff",
    borderRadius: "var(--border-radius)",
    padding: "var(--space-6)",
    width: "100%",
    maxWidth: "440px",
    boxShadow: "var(--shadow-md)",
  },
  title: {
    fontSize: "var(--text-lg)",
    fontWeight: 600,
    marginBottom: "var(--space-4)",
    color: "var(--color-text-primary)",
  },
  field: {
    marginBottom: "var(--space-3)",
  },
  label: {
    display: "block",
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    marginBottom: "2px",
    textTransform: "uppercase",
    letterSpacing: "0.03em",
  },
  value: {
    fontSize: "var(--text-md)",
    color: "var(--color-text-primary)",
    fontFamily: "var(--font-mono)",
  },
  input: {
    width: "100%",
    padding: "var(--space-2) var(--space-3)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-md)",
    fontFamily: "var(--font-mono)",
  },
  error: {
    color: "var(--color-error)",
    fontSize: "var(--text-sm)",
    marginBottom: "var(--space-3)",
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "var(--space-2)",
    marginTop: "var(--space-4)",
  },
  cancelBtn: {
    padding: "var(--space-2) var(--space-4)",
    backgroundColor: "transparent",
    border: "1px solid var(--color-border)",
    color: "var(--color-text-secondary)",
    borderRadius: "var(--border-radius-sm)",
  },
  submitBtn: {
    padding: "var(--space-2) var(--space-4)",
    backgroundColor: "var(--color-info)",
    color: "#fff",
    fontWeight: 600,
    borderRadius: "var(--border-radius-sm)",
  },
};
