import React from "react";

const LABEL_MAP = {
  bank_statement: "Bank Statement",
  custody_statement: "Custody Statement",
  swift_confirm: "SWIFT Confirm",
  unknown: "Unknown",
};

export default function SchemaTypeTag({ type }) {
  const label = LABEL_MAP[type] || type || "Unknown";

  return (
    <span style={styles.tag}>
      {label}
    </span>
  );
}

const styles = {
  tag: {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-xs)",
    fontWeight: 500,
    backgroundColor: "rgba(15, 30, 60, 0.06)",
    color: "var(--color-text-secondary)",
    border: "1px solid var(--color-border-light)",
  },
};
