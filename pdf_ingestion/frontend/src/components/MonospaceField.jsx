import React from "react";

/**
 * Styled display for financial identifiers (IBANs, ISINs, BICs, hashes).
 */
export default function MonospaceField({ children }) {
  if (!children) return <span style={{ color: "var(--color-text-muted)" }}>—</span>;

  return (
    <span style={styles.field}>
      {children}
    </span>
  );
}

const styles = {
  field: {
    fontFamily: "var(--font-mono)",
    fontSize: "var(--text-sm)",
    backgroundColor: "#f1f5f9",
    padding: "1px 6px",
    borderRadius: "3px",
    color: "var(--color-text-primary)",
    wordBreak: "break-all",
  },
};
