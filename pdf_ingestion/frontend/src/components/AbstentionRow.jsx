import React from "react";

/**
 * Amber-highlighted row for fields/tables that could not be extracted.
 */
export default function AbstentionRow({ fieldName, reasonCode, detail, vlmAttempted }) {
  return (
    <div style={styles.row}>
      <div style={styles.header}>
        <span style={styles.fieldName}>{fieldName || "—"}</span>
        <span style={styles.code}>{reasonCode}</span>
        {vlmAttempted && <span style={styles.vlmBadge}>VLM attempted</span>}
      </div>
      {detail && <div style={styles.detail}>{detail}</div>}
    </div>
  );
}

const styles = {
  row: {
    padding: "var(--space-2) var(--space-3)",
    borderLeft: "3px solid var(--color-warning)",
    backgroundColor: "rgba(243, 156, 18, 0.05)",
    marginBottom: "var(--space-2)",
    borderRadius: "0 var(--border-radius-sm) var(--border-radius-sm) 0",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
  },
  fieldName: {
    fontWeight: 600,
    fontSize: "var(--text-md)",
    color: "var(--color-text-primary)",
  },
  code: {
    fontFamily: "var(--font-mono)",
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    backgroundColor: "#f1f5f9",
    padding: "1px 4px",
    borderRadius: "2px",
  },
  vlmBadge: {
    fontSize: "var(--text-xs)",
    color: "var(--color-info)",
    fontWeight: 500,
  },
  detail: {
    fontSize: "var(--text-sm)",
    color: "var(--color-text-secondary)",
    marginTop: "2px",
  },
};
